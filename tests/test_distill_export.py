"""Slice D4 tests: universal fused export & Ollama Modelfile creation (hermetic)."""

import json
import subprocess
from pathlib import Path

import pytest

from kultivait.distill.export import (
    ExportReport,
    base_tag,
    export_distillate,
    next_generation,
)


class FakeRunner:
    def __init__(self, *, fail_fuse=False, fail_create=False):
        self.calls: list[dict] = []
        self.fail_fuse = fail_fuse
        self.fail_create = fail_create

    def __call__(self, argv, **kwargs):
        self.calls.append({"argv": argv, "kwargs": kwargs})
        joined = " ".join(argv)
        if "mlx_lm.fuse" in joined and self.fail_fuse:
            return subprocess.CompletedProcess(argv, 1, stdout="", stderr="fuse exploded")
        if "ollama" in joined and "create" in joined and self.fail_create:
            return subprocess.CompletedProcess(argv, 1, stdout="", stderr="ollama refused")
        if "mlx_lm.fuse" in joined:
            # simulate the fused dir appearing
            for i, a in enumerate(argv):
                if a == "--save-path":
                    out = Path(argv[i + 1])
                    out.mkdir(parents=True, exist_ok=True)
                    (out / "model.safetensors").write_text("weights")
                    (out / "config.json").write_text("{}")
            return subprocess.CompletedProcess(argv, 0, stdout="fused", stderr="")
        return subprocess.CompletedProcess(argv, 0, stdout="created", stderr="")


@pytest.fixture
def adapter(tmp_path: Path) -> Path:
    a = tmp_path / "adapters"
    a.mkdir()
    (a / "adapters.safetensors").write_text("adapter")
    return a


# ---------------------------------------------------------------- naming


def test_base_tag_sanitizes_base_keys():
    assert base_tag("qwen3.5:4b") == "qwen35-4b"
    assert base_tag("llama-3.2-3b-instruct") == "llama32-3b"


def test_generation_monotonic_from_registry(tmp_path: Path):
    assert next_generation("qwen3.5:4b", tmp_path) == 0
    registry = tmp_path / "distillates.json"
    registry.write_text(json.dumps({"kv-judge-qwen35-4b-g0": {"generation": 0}}))
    assert next_generation("qwen3.5:4b", tmp_path) == 1
    registry.write_text(json.dumps({
        "kv-judge-qwen35-4b-g0": {"generation": 0},
        "kv-judge-qwen35-4b-g3": {"generation": 3},
    }))
    assert next_generation("qwen3.5:4b", tmp_path) == 4  # max + 1, never reuses


# ---------------------------------------------------------------- export happy path


def test_export_names_fuses_and_registers(adapter, tmp_path):
    runner = FakeRunner()
    out_root = tmp_path / "distillates"
    report = export_distillate("llama-3.2-3b-instruct", adapter, out_root=out_root,
                               runner=runner)
    assert report.name == "kv-judge-llama32-3b-g0"
    assert report.status == "ok" and report.registered is True
    assert report.generation == 0
    fuse_call = next(c for c in runner.calls if "mlx_lm.fuse" in " ".join(c["argv"]))
    argv = fuse_call["argv"]
    assert "mlx-community/Llama-3.2-3B-Instruct-4bit" in argv
    assert str(adapter) in argv
    assert "--dequantize" in argv  # fp16 fused model; ollama quantizes at import
    create_call = next(c for c in runner.calls if "ollama" in " ".join(c["argv"]))
    cargv = create_call["argv"]
    assert cargv[:2] == ["ollama", "create"]
    assert report.name in cargv
    assert "--quantize" in cargv and "q4_K_M" in cargv


def test_modelfile_content(adapter, tmp_path):
    from kultivait.preprocessor import PREPROCESSOR_PROMPT

    runner = FakeRunner()
    report = export_distillate("qwen3.5:4b", adapter, out_root=tmp_path / "d",
                               runner=runner)
    mf = Path(report.modelfile_path).read_text()
    assert mf.startswith(f"FROM {report.fused_path}")
    # the contract rides as the SYSTEM block (ADR 0014: template/system carried)
    assert PREPROCESSOR_PROMPT.splitlines()[0] in mf
    assert "PARAMETER" in mf  # serving parameters present


def test_registry_records_generation(adapter, tmp_path):
    out_root = tmp_path / "d"
    r0 = export_distillate("qwen3.5:4b", adapter, out_root=out_root, runner=FakeRunner())
    r1 = export_distillate("qwen3.5:4b", adapter, out_root=out_root, runner=FakeRunner())
    assert (r0.generation, r1.generation) == (0, 1)
    registry = json.loads((out_root / "distillates.json").read_text())
    assert registry[r0.name]["generation"] == 0
    assert registry[r1.name]["generation"] == 1


def test_explicit_generation_override(adapter, tmp_path):
    report = export_distillate("llama-3.2-3b-instruct", adapter, out_root=tmp_path / "d",
                               runner=FakeRunner(), generation=7)
    assert report.name == "kv-judge-llama32-3b-g7"
    assert next_generation("llama-3.2-3b-instruct", tmp_path / "d") == 8


# ---------------------------------------------------------------- failures


def test_fuse_failure_aborts_with_error(adapter, tmp_path):
    runner = FakeRunner(fail_fuse=True)
    report = export_distillate("qwen3.5:4b", adapter, out_root=tmp_path / "d",
                               runner=runner)
    assert report.status == "aborted" and report.registered is False
    assert "fuse exploded" in report.error
    # no ollama create attempted after a failed fuse
    assert not any("ollama" in " ".join(c["argv"]) for c in runner.calls)


def test_create_failure_records_not_registered(adapter, tmp_path):
    runner = FakeRunner(fail_create=True)
    report = export_distillate("qwen3.5:4b", adapter, out_root=tmp_path / "d",
                               runner=runner)
    assert report.status == "ok"          # export itself succeeded
    assert report.registered is False     # registration failed, recorded
    assert "ollama refused" in report.error


def test_quantize_none_omits_flag(adapter, tmp_path):
    runner = FakeRunner()
    report = export_distillate("qwen3.5:4b", adapter, out_root=tmp_path / "d",
                               runner=runner, quantize=None)
    create_call = next(c for c in runner.calls if "ollama" in " ".join(c["argv"]))
    assert "--quantize" not in create_call["argv"]
    assert report.quantize is None


# ---------------------------------------------------------------- report


def test_export_report_json_round_trips(adapter, tmp_path):
    report = export_distillate("llama-3.2-3b-instruct", adapter, out_root=tmp_path / "d",
                               runner=FakeRunner())
    data = json.loads(report.to_json())
    assert data["name"] == "kv-judge-llama32-3b-g0"
    restored = ExportReport.from_json(report.to_json())
    assert restored.name == report.name and restored.generation == 0
