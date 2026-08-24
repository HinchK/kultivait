"""Slice D3 tests: MLX-LM QLoRA training runner & resource ladder (hermetic)."""

import json
import subprocess
from pathlib import Path

import pytest

from kultivait.distill.trainer import (
    BASES,
    BudgetAborted,
    RUNGS,
    TrainReport,
    choose_rung,
    corpus_fingerprint,
    train,
)


class FakeRunner:
    """Records invocations; simulates success or budget breaches per rung."""

    def __init__(self, *, breaches=0, wall_s=60.0, peak_rss_gb=3.0, output="trained"):
        self.calls: list[dict] = []
        self.breaches = breaches  # number of initial calls that breach
        self.wall_s = wall_s
        self.peak_rss_gb = peak_rss_gb
        self.output = output

    def __call__(self, argv, **kwargs):
        self.calls.append({"argv": argv, "kwargs": kwargs})
        if len(self.calls) <= self.breaches:
            raise subprocess.TimeoutExpired(cmd="mlx", timeout=kwargs.get("timeout", 1))
        return subprocess.CompletedProcess(
            argv, 0, stdout=self.output, stderr=""
        )


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    d = tmp_path / "corpus"
    d.mkdir()
    rows = [{"messages": [{"role": "system", "content": "c"}, {"role": "user", "content": f"p{i}"},
                          {"role": "assistant", "content": "{}"}]} for i in range(4)]
    (d / "train.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    (d / "valid.jsonl").write_text(json.dumps(rows[0]["messages"] and {"messages": rows[0]["messages"]}) + "\n")
    return d


# ---------------------------------------------------------------- constants & pure fns


def test_bases_registry_has_both_bake_off_candidates():
    assert BASES["qwen3.5:4b"].hf_repo.endswith("4bit")
    assert BASES["llama-3.2-3b-instruct"].hf_repo.endswith("4bit")
    assert all(b.quantized for b in BASES.values())  # QLoRA: 4-bit bases per ADR 0014


def test_rungs_follow_the_adr_0014_ladder_order():
    # batch 4->2->1, then layers 16->8->4 with grad-checkpoint, then abort
    assert RUNGS[0]["batch_size"] == 4 and RUNGS[0]["num_layers"] == 16
    assert RUNGS[1]["batch_size"] == 2
    assert RUNGS[2]["batch_size"] == 1 and not RUNGS[2]["grad_checkpoint"]
    assert RUNGS[3]["num_layers"] == 8 and RUNGS[3]["grad_checkpoint"]
    assert RUNGS[4]["num_layers"] == 4 and RUNGS[4]["grad_checkpoint"]


def test_choose_rung_from_base_and_history():
    r = choose_rung("llama-3.2-3b-instruct", breaches=0)
    assert r == RUNGS[0]
    assert choose_rung("llama-3.2-3b-instruct", breaches=2) == RUNGS[2]
    assert choose_rung("qwen3.5:4b", breaches=4) == RUNGS[4]


def test_corpus_fingerprint_stable_and_sensitive(corpus, tmp_path):
    a = corpus_fingerprint(corpus)
    b = corpus_fingerprint(corpus)
    assert a == b and len(a) == 16
    (corpus / "train.jsonl").write_text((corpus / "train.jsonl").read_text() + "\n")
    assert corpus_fingerprint(corpus) != a


# ---------------------------------------------------------------- argv assembly


def test_argv_assembles_mlx_lora_qlora_defaults(corpus):
    runner = FakeRunner()
    report = train("llama-3.2-3b-instruct", corpus, iters=10, runner=runner,
                   adapter_path=corpus.parent / "adapters", sampler=lambda gb: 2.5)
    argv = runner.calls[0]["argv"]
    joined = " ".join(argv)
    assert "mlx_lm.lora" in joined
    assert BASES["llama-3.2-3b-instruct"].hf_repo in joined
    assert "--train" in argv and str(corpus) in argv
    assert "--iters" in argv and "10" in argv
    assert "--batch-size" in argv and "4" in argv  # rung 0 defaults (ADR 0014)
    assert "--num-layers" in argv and "16" in argv
    assert "--mask-prompt" in argv  # loss on the contract JSON only
    assert report.status == "ok"


def test_timeout_is_the_budget(corpus):
    runner = FakeRunner()
    train("qwen3.5:4b", corpus, iters=5, runner=runner,
          adapter_path=corpus.parent / "a", budget_minutes=45, sampler=lambda gb: 2.0)
    assert runner.calls[0]["kwargs"]["timeout"] == 45 * 60


# ---------------------------------------------------------------- ladder & abort


def test_budget_breach_escalates_one_rung(corpus):
    runner = FakeRunner(breaches=1)
    report = train("llama-3.2-3b-instruct", corpus, iters=5, runner=runner,
                   adapter_path=corpus.parent / "a", sampler=lambda gb: 2.0)
    assert len(runner.calls) == 2
    assert "--batch-size" in runner.calls[0]["argv"]
    b0 = runner.calls[0]["argv"][runner.calls[0]["argv"].index("--batch-size") + 1]
    b1 = runner.calls[1]["argv"][runner.calls[1]["argv"].index("--batch-size") + 1]
    assert (b0, b1) == ("4", "2")  # escalated exactly one rung
    assert report.status == "ok" and report.rung == 1


def test_memory_breach_escalates_and_abort_never_swaps(corpus):
    # peak RSS over cap on every rung -> BudgetAborted after the final rung
    runner = FakeRunner()
    report = train("qwen3.5:4b", corpus, iters=3, runner=runner,
                   adapter_path=corpus.parent / "a", sampler=lambda gb: gb + 20.0)
    assert report.status == "aborted"
    with pytest.raises(BudgetAborted):
        raise report.abort_error


def test_abort_after_all_rungs(corpus):
    runner = FakeRunner(breaches=99)
    report = train("llama-3.2-3b-instruct", corpus, iters=3, runner=runner,
                   adapter_path=corpus.parent / "a", sampler=lambda gb: 2.0)
    assert report.status == "aborted"
    assert len(runner.calls) == len(RUNGS)  # every rung tried, then abort
    assert "wired_limit_mb" in str(report.abort_error)  # last-resort instructions


def test_infra_error_aborts_immediately_without_ladder_walk(corpus):
    class InfraFail:
        def __init__(self):
            self.calls = 0

        def __call__(self, argv, **kwargs):
            self.calls += 1
            return subprocess.CompletedProcess(argv, 1, stdout="", stderr="404 repo not found")

    runner = InfraFail()
    report = train("qwen3.5:4b", corpus, iters=3, runner=runner,
                   adapter_path=corpus.parent / "a")
    assert report.status == "aborted"
    assert runner.calls == 1  # no rung-climbing on non-budget errors
    assert "404" in report.error


def test_gpu_oom_is_a_budget_breach_and_climbs_the_ladder(corpus):
    class OomThenOk:
        def __init__(self):
            self.calls = 0

        def __call__(self, argv, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return subprocess.CompletedProcess(
                    argv, 1, stdout="",
                    stderr="RuntimeError: [METAL] ... kIOGPUCommandBufferCallbackErrorOutOfMemory")
            return subprocess.CompletedProcess(argv, 0, stdout="ok", stderr="")

    runner = OomThenOk()
    report = train("qwen3.5:4b", corpus, iters=3, runner=runner,
                   adapter_path=corpus.parent / "a", sampler=lambda gb: 2.0)
    assert report.status == "ok" and report.rung == 1  # climbed one rung, then held
    assert runner.calls == 2


# ---------------------------------------------------------------- checkpoints & resume


def test_adapter_path_and_resume_flag(corpus, tmp_path):
    runner = FakeRunner()
    adapter = tmp_path / "adapters"
    train("llama-3.2-3b-instruct", corpus, iters=4, runner=runner, adapter_path=adapter)
    assert "--adapter-path" in runner.calls[0]["argv"]
    assert str(adapter) in runner.calls[0]["argv"]
    assert not any("--resume-adapter-file" in c["argv"] for c in runner.calls)

    train("llama-3.2-3b-instruct", corpus, iters=4, runner=runner,
          adapter_path=adapter, resume=True)
    assert "--resume-adapter-file" in runner.calls[1]["argv"]


def test_per_epoch_checkpoint_every_iters(corpus, tmp_path):
    runner = FakeRunner()
    adapter = tmp_path / "adapters"
    train("qwen3.5:4b", corpus, iters=8, epochs=2, runner=runner, adapter_path=adapter,
          sampler=lambda gb: 2.0)
    # iters split across epochs -> checkpoint interval = iters per epoch
    assert "--save-every-iters" in runner.calls[0]["argv"]
    i = runner.calls[0]["argv"].index("--save-every-iters")
    assert runner.calls[0]["argv"][i + 1] == "4"


# ---------------------------------------------------------------- report


def test_train_report_fields(corpus, tmp_path):
    runner = FakeRunner(wall_s=120.0, peak_rss_gb=3.2)
    report = train("llama-3.2-3b-instruct", corpus, iters=6, runner=runner,
                   adapter_path=tmp_path / "a", sampler=lambda gb: 3.2)
    assert isinstance(report, TrainReport)
    assert report.base == "llama-3.2-3b-instruct"
    assert report.corpus_fingerprint == corpus_fingerprint(corpus)
    assert report.iters == 6
    assert report.rung == 0
    assert report.peak_rss_gb == pytest.approx(3.2)
    assert report.wall_clock_s >= 0
    assert report.status == "ok"
    assert report.budget == {"peak_gb": 16.0, "minutes_per_epoch": 45}


def test_report_json_round_trips(corpus, tmp_path):
    runner = FakeRunner()
    report = train("qwen3.5:4b", corpus, iters=2, runner=runner,
                   adapter_path=tmp_path / "a", sampler=lambda gb: 2.0)
    data = json.loads(report.to_json())
    assert data["base"] == "qwen3.5:4b"
    assert TrainReport.from_json(report.to_json()).base == report.base
