"""MLX-LM QLoRA training runner & resource ladder (ADR 0014).

Drives ``mlx_lm.lora`` as a subprocess — no ML dependencies in the serving
package. Both bake-off bases train in 4-bit QLoRA (the incumbent
qwen3.5:4b and the challenger llama-3.2-3b-instruct) with mlx-lm documented
defaults (rank 16, default linear targets, --mask-prompt so loss lands on
the contract JSON only); iters scaled to epochs is the single tuned knob.

The resource ladder is binding: peak working set <= 16 GB and <= 45 minutes
per epoch. On breach the run climbs exactly one rung — batch 4->2->1, then
adapted layers 16->8->4 with gradient checkpointing — and after the final
rung ABORTS with wired-limit instructions (never lets macOS swap).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

PEAK_BUDGET_GB = 16.0
MINUTES_PER_EPOCH = 45.0

# ADR 0014 ladder: batch down first, then layers down + grad checkpoint,
# then the manual wired-limit last resort, then abort.
RUNGS: list[dict] = [
    {"batch_size": 4, "num_layers": 16, "grad_checkpoint": False},
    {"batch_size": 2, "num_layers": 16, "grad_checkpoint": False},
    {"batch_size": 1, "num_layers": 16, "grad_checkpoint": False},
    {"batch_size": 1, "num_layers": 8, "grad_checkpoint": True},
    {"batch_size": 1, "num_layers": 4, "grad_checkpoint": True},
]


@dataclass(frozen=True)
class BaseSpec:
    name: str
    hf_repo: str        # 4-bit (quantized) MLX community repo -> QLoRA by construction
    quantized: bool = True


BASES: dict[str, BaseSpec] = {
    "qwen3.5:4b": BaseSpec("qwen3.5:4b", "mlx-community/Qwen3.5-4B-MLX-4bit"),
    "llama-3.2-3b-instruct": BaseSpec("llama-3.2-3b-instruct", "mlx-community/Llama-3.2-3B-Instruct-4bit"),
}


class BudgetAborted(RuntimeError):
    """The final ladder rung could not hold the envelope. ABORT — never swap."""


def _is_oom(stderr: str) -> bool:
    markers = ("insufficient memory", "outofmemory", "out of memory", "kIOGPUCommandBufferCallbackErrorOutOfMemory")
    low = stderr.lower()
    return any(m.lower() in low for m in markers)


def choose_rung(base: str, breaches: int) -> dict:
    idx = min(breaches, len(RUNGS) - 1)
    return RUNGS[idx]


def corpus_fingerprint(corpus_dir: Path) -> str:
    """Stable 16-hex digest of the corpus contents (train + valid)."""
    h = hashlib.sha256()
    for name in ("train.jsonl", "valid.jsonl", "metadata.jsonl"):
        p = Path(corpus_dir) / name
        if p.exists():
            h.update(name.encode())
            h.update(p.read_bytes())
    return h.hexdigest()[:16]


@dataclass(frozen=True)
class TrainReport:
    base: str
    hf_repo: str
    corpus_fingerprint: str
    iters: int
    epochs: int
    rung: int
    rung_config: dict
    wall_clock_s: float
    peak_rss_gb: float
    status: str                 # "ok" | "aborted"
    adapter_path: str
    budget: dict = field(default_factory=lambda: {"peak_gb": PEAK_BUDGET_GB,
                                                  "minutes_per_epoch": MINUTES_PER_EPOCH})
    error: str = ""

    @property
    def abort_error(self) -> BudgetAborted:
        return BudgetAborted(self.error or "training aborted: envelope exceeded")

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, raw: str) -> "TrainReport":
        return cls(**json.loads(raw))


def _default_runner(argv: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, **kwargs)


def _default_sampler(default_gb: float) -> float:
    """Peak RSS of child processes (GB); falls back to the planning estimate."""
    try:
        import resource

        peak = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss  # bytes on macOS
        return max(default_gb, peak / 1e9)
    except Exception:  # noqa: BLE001 - sampling must never crash training
        return default_gb


def train(
    base: str,
    corpus_dir: Path,
    *,
    iters: int,
    epochs: int = 1,
    adapter_path: Path,
    resume: bool = False,
    budget_minutes: float = MINUTES_PER_EPOCH,
    budget_gb: float = PEAK_BUDGET_GB,
    runner: Callable = _default_runner,
    sampler: "Callable[[float], float]" = _default_sampler,
) -> TrainReport:
    """Train ``base`` on ``corpus_dir`` under the envelope, escalating the
    ladder on breach and aborting (never swapping) past the final rung."""
    if base not in BASES:
        raise ValueError(f"unknown base {base!r}; known: {sorted(BASES)}")
    spec = BASES[base]
    corpus_dir = Path(corpus_dir)
    adapter_path = Path(adapter_path)
    adapter_path.mkdir(parents=True, exist_ok=True)
    fingerprint = corpus_fingerprint(corpus_dir)
    t0 = time.monotonic()

    breaches = 0
    last_error = ""
    while True:
        rung_cfg = choose_rung(base, breaches)
        argv = [
            "python", "-m", "mlx_lm.lora",
            "--model", spec.hf_repo,
            "--train",
            "--data", str(corpus_dir),
            "--iters", str(iters),
            "--batch-size", str(rung_cfg["batch_size"]),
            "--num-layers", str(rung_cfg["num_layers"]),
            "--mask-prompt",
            "--adapter-path", str(adapter_path),
        ]
        if epochs > 1:
            argv += ["--save-every-iters", str(max(1, iters // epochs))]
        if rung_cfg["grad_checkpoint"]:
            argv.append("--grad-checkpoint")
        if resume:
            argv += ["--resume-adapter-file", str(adapter_path / "adapters.safetensors")]

        timed_out = False
        try:
            result = runner(argv, timeout=int(budget_minutes * 60 * epochs))
        except subprocess.TimeoutExpired:
            timed_out = True
            result = None

        if not timed_out and result is not None and result.returncode == 0:
            estimate_gb = 3.0 if "3b" in base or "4b" in base else 9.0
            peak_gb = round(sampler(estimate_gb), 2)
            if peak_gb <= budget_gb:
                return TrainReport(
                    base=base, hf_repo=spec.hf_repo, corpus_fingerprint=fingerprint,
                    iters=iters, epochs=epochs, rung=breaches, rung_config=dict(rung_cfg),
                    wall_clock_s=round(time.monotonic() - t0, 1), peak_rss_gb=peak_gb,
                    status="ok", adapter_path=str(adapter_path),
                )
            last_error = f"peak RSS {peak_gb} GB > {budget_gb} GB budget"
        elif timed_out:
            last_error = (f"wall budget exceeded ({budget_minutes:.0f} min/epoch "
                          f"x {epochs} epoch(s))")
        else:
            # nonzero exit: a GPU/memory OOM is a budget breach (climb the
            # ladder); anything else (download 404, bad config) is an infra
            # error — abort now, no pointless rung-walking.
            stderr = getattr(result, "stderr", "") or ""
            if _is_oom(stderr):
                last_error = f"GPU/memory OOM at rung {breaches}: {stderr[-200:]}"
            else:
                return TrainReport(
                    base=base, hf_repo=spec.hf_repo, corpus_fingerprint=fingerprint,
                    iters=iters, epochs=epochs, rung=breaches, rung_config=dict(rung_cfg),
                    wall_clock_s=round(time.monotonic() - t0, 1), peak_rss_gb=0.0,
                    status="aborted", adapter_path=str(adapter_path),
                    error=f"mlx_lm.lora exited {getattr(result, 'returncode', '?')}: {stderr[:300]}",
                )

        if breaches >= len(RUNGS) - 1:
            wall = round(time.monotonic() - t0, 1)
            return TrainReport(
                base=base, hf_repo=spec.hf_repo, corpus_fingerprint=fingerprint,
                iters=iters, epochs=epochs, rung=breaches, rung_config=dict(rung_cfg),
                wall_clock_s=wall, peak_rss_gb=budget_gb + 1, status="aborted",
                adapter_path=str(adapter_path),
                error=(f"{last_error}; all {len(RUNGS)} rungs exhausted — ABORT, never "
                       f"swap. Last resort (manual): sudo sysctl iogpu.wired_limit_mb=..."
                       " per ADR 0014, then retry."),
            )
        breaches += 1
