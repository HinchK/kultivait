"""Universal fused export & Ollama registration (ADR 0014).

Trained adapters become serving distillates through ONE route regardless of
base family: ``mlx_lm.fuse`` merges the LoRA into standalone safetensors, a
Modelfile carries the contract (FROM the fused dir, the preprocessor
contract as SYSTEM, serving parameters), and ``ollama create`` registers the
model under ``kv-judge-<base_tag>-g<generation>`` with optional quantize-at-
import (default q4_K_M — deployed distillates stay <= 4 GB resident). The
direct-ADAPTER path is deliberately absent: Qwen is not in Ollama's adapter
architecture list and QLoRA adapters are not documented-safe for direct
import anyway — the fused route is universal.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from kultivait.distill.trainer import BASES
from kultivait.preprocessor import PREPROCESSOR_PROMPT

DEFAULT_QUANTIZE = "q4_K_M"
NUM_CTX = 8192


def base_tag(base: str) -> str:
    """qwen3.5:4b -> qwen35-4b; llama-3.2-3b-instruct -> llama32-3b.

    Short, filesystem- and ollama-safe tags: numeric version tokens join the
    family name (3.2 -> 32), the instruct suffix drops, ':' becomes '-'.
    """
    tag = base.lower().replace("-instruct", "").replace(":", "-")
    parts = [p for p in tag.split("-") if p]
    out = ""
    for p in parts:
        numeric = p.replace(".", "").isdigit()
        if numeric and out:
            out += p.replace(".", "")  # version attaches: llama-3.2 -> llama32
        elif out:
            out += "-" + p
        else:
            out = p.replace(".", "")
    return out


def _registry_path(out_root: Path) -> Path:
    return Path(out_root) / "distillates.json"


def _load_registry(out_root: Path) -> dict:
    p = _registry_path(out_root)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def next_generation(base: str, out_root: Path) -> int:
    """Monotonic generation: max recorded + 1 for this base (never reuses)."""
    registry = _load_registry(out_root)
    tag = base_tag(base)
    gens = [v.get("generation", 0) for k, v in registry.items() if k.startswith(f"kv-judge-{tag}-g")]
    return max(gens, default=-1) + 1


@dataclass(frozen=True)
class ExportReport:
    name: str
    base: str
    hf_repo: str
    generation: int
    fused_path: str
    modelfile_path: str
    quantize: "str | None"
    registered: bool
    wall_clock_s: float
    status: str  # "ok" | "aborted"
    error: str = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, raw: str) -> "ExportReport":
        return cls(**json.loads(raw))


def _default_runner(argv: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, **kwargs)


def export_distillate(
    base: str,
    adapter_path: Path,
    *,
    out_root: Path,
    generation: "int | None" = None,
    quantize: "str | None" = DEFAULT_QUANTIZE,
    runner: Callable = _default_runner,
) -> ExportReport:
    """Fuse, write the Modelfile, and register the distillate (ADR 0014)."""
    if base not in BASES:
        raise ValueError(f"unknown base {base!r}; known: {sorted(BASES)}")
    spec = BASES[base]
    out_root = Path(out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    adapter_path = Path(adapter_path)
    gen = next_generation(base, out_root) if generation is None else generation
    name = f"kv-judge-{base_tag(base)}-g{gen}"
    fused_dir = out_root / name / "fused"
    t0 = time.monotonic()

    def report(status: str, registered: bool, error: str = "") -> ExportReport:
        return ExportReport(
            name=name, base=base, hf_repo=spec.hf_repo, generation=gen,
            fused_path=str(fused_dir), modelfile_path=str(fused_dir.parent / "Modelfile"),
            quantize=quantize, registered=registered,
            wall_clock_s=round(time.monotonic() - t0, 1), status=status, error=error,
        )

    # 1. fuse: adapter merged into standalone safetensors. Bases are 4-bit,
    # so dequantize on fuse — ollama cannot convert packed-quant dtypes
    # (U32); the fp16 fused model quantizes at import instead (ADR 0014).
    fuse_argv = [
        sys.executable, "-m", "mlx_lm.fuse",
        "--model", spec.hf_repo,
        "--adapter-path", str(adapter_path),
        "--save-path", str(fused_dir),
        "--dequantize",
    ]
    try:
        fuse = runner(fuse_argv, timeout=1800)
    except subprocess.TimeoutExpired:
        return report("aborted", False, "fuse timed out (30 min)")
    if fuse.returncode != 0:
        return report("aborted", False,
                      f"mlx_lm.fuse exited {fuse.returncode}: {(fuse.stderr or '')[:300]}")

    # 2. Modelfile: the universal fused route's serving contract
    # (resolve symlinks — ollama refuses FROM paths containing '..')
    modelfile = fused_dir.parent / "Modelfile"
    lines = [
        f"FROM {fused_dir.resolve()}",
        f'SYSTEM """{PREPROCESSOR_PROMPT}"""',
        f"PARAMETER num_ctx {NUM_CTX}",
    ]
    modelfile.write_text("\n".join(lines) + "\n")

    # 3. register with Ollama (quantize-at-import keeps serving <= 4 GB)
    create_argv = ["ollama", "create", name, "-f", str(modelfile)]
    if quantize:
        create_argv += ["--quantize", quantize]
    registered, error = True, ""
    try:
        create = runner(create_argv, timeout=600)
        if create.returncode != 0:
            registered = False
            error = f"ollama create exited {create.returncode}: {(create.stderr or '')[:300]}"
    except subprocess.TimeoutExpired:
        registered, error = False, "ollama create timed out (10 min)"

    # 4. record the generation (monotonic tracking)
    registry = _load_registry(out_root)
    registry[name] = {
        "generation": gen, "base": base, "hf_repo": spec.hf_repo,
        "fused_path": str(fused_dir), "quantize": quantize,
        "registered": registered,
    }
    _registry_path(out_root).write_text(json.dumps(registry, indent=1))

    return report("ok", registered, error)
