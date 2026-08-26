"""H4 (#91) tests: dual-judge scoring, agreement telemetry, cross-family guards."""

import json
from pathlib import Path

import pytest

from kultivait.capability_eval import (
    TaskCase,
    run_capability_eval,
    select_cross_family_judge,
)


class FakeTarget:
    supports_tools = True
    local = False

    def complete(self, messages, tools=None, canonical_effort="balanced", **kw):
        from kultivait.backends import Completion
        return Completion(text="did the work", tokens_in=5, tokens_out=5,
                          cost_usd=0.0, local=False)

    def stream(self, *a, **kw):
        yield "did the work"


class JudgeA:  # openai family
    supports_tools = True
    local = False

    def complete(self, messages, tools=None, canonical_effort="balanced", **kw):
        from kultivait.backends import Completion
        last = json.dumps(messages[-1])[:80]
        return Completion(text=json.dumps({"score": 0.9, "passed": True,
                                           "reasoning": f"A:{last}"}),
                          tokens_in=1, tokens_out=1, cost_usd=0.0, local=False)

    def stream(self, *a, **kw):
        yield "ok"


class JudgeB(JudgeA):  # anthropic family by NAME below; stricter scorer
    def complete(self, messages, tools=None, canonical_effort="balanced", **kw):
        from kultivait.backends import Completion
        return Completion(text=json.dumps({"score": 0.5, "passed": False,
                                           "reasoning": "B: stricter"}),
                          tokens_in=1, tokens_out=1, cost_usd=0.0, local=False)


def tasks(n=2):
    out = []
    for i in range(n):
        out.append(TaskCase(
            id=f"t{i}", name=f"t{i}", description="d",
            messages=[{"role": "user", "content": f"q{i}"}],
            tools=[], mock_responses={},
            rubric={"version": "v2", "band": "escalatory", "features": [],
                    "criteria": ["do it"], "expected_tools": [], "passing_score": 0.8},
            max_turns=1))
    return out


BACKENDS = {
    "qwen3.5:4b": FakeTarget(),
    "openrouter:gpt-4o": JudgeA(),           # openai family
    "openrouter:claude-sonnet-5": JudgeB(),   # anthropic family
}


def run_dual(**kw):
    return run_capability_eval(
        backends=BACKENDS, targets=["qwen3.5:4b"], efforts=["balanced"],
        corpus=tasks(), judge_backend=BACKENDS["openrouter:gpt-4o"], judge_name="openrouter:gpt-4o",
        **kw)


# ---------------------------------------------------------------- dual mode


def test_dual_judge_scores_both_and_means():
    s = run_dual(dual_judge=True,
                 judge_b_backend=BACKENDS["openrouter:claude-sonnet-5"],
                 judge_b_name="openrouter:claude-sonnet-5")
    cell = s["targets"]["qwen3.5:4b"]["balanced"]
    # JudgeA scores 0.9, JudgeB 0.5 -> mean 0.7
    assert cell["avg_score"] == pytest.approx(0.7)
    assert cell["judges"] == ["openrouter:gpt-4o", "openrouter:claude-sonnet-5"]
    assert cell["inter_judge_agreement"] == pytest.approx(0.0)  # 0.9-pass vs 0.5-fail disagree


def test_dual_judge_agreement_when_judges_align():
    s = run_dual(dual_judge=True,
                 judge_b_backend=BACKENDS["openrouter:gpt-4o"],  # same scores as A
                 judge_b_name="openrouter:claude-sonnet-5")
    cell = s["targets"]["qwen3.5:4b"]["balanced"]
    assert cell["inter_judge_agreement"] == pytest.approx(1.0)
    assert cell["avg_score"] == pytest.approx(0.9)


def test_dual_artifact_carries_both_judges(tmp_path: Path):
    s = run_dual(dual_judge=True, artifacts_dir=tmp_path,
                 judge_b_backend=BACKENDS["openrouter:claude-sonnet-5"],
                 judge_b_name="openrouter:claude-sonnet-5")
    art = json.loads((tmp_path / "qwen3.5:4b_balanced_t0.json").read_text())
    assert art["judges"] == {"a": {"name": "openrouter:gpt-4o", "score": 0.9, "passed": True},
                             "b": {"name": "openrouter:claude-sonnet-5", "score": 0.5, "passed": False}}
    assert art["score"] == pytest.approx(0.7)
    assert art["agreement_flag"] is False


def test_single_judge_default_unchanged():
    s = run_dual()  # no dual flag
    cell = s["targets"]["qwen3.5:4b"]["balanced"]
    assert cell["avg_score"] == pytest.approx(0.9)  # judge A only
    assert "judges" not in cell


# ---------------------------------------------------------------- guards


def test_dual_judge_cross_family_enforced_for_judge_b():
    # judge_b in the TARGET's family must raise (qwen target, qwen-ish judge name)
    with pytest.raises(ValueError, match="[Cc]ross-family"):
        run_dual(dual_judge=True,
                 judge_b_backend=FakeTarget(),
                 judge_b_name="qwen3.5:14b")


def test_dual_judge_cross_family_enforced_vs_openai_target():
    # judging the gpt-4o target with a gpt-family judge_b must raise
    with pytest.raises(ValueError, match="Cross-family violation"):
        run_capability_eval(
            backends=BACKENDS, targets=["openrouter:gpt-4o"], efforts=["balanced"],
            corpus=tasks(), judge_backend=BACKENDS["openrouter:claude-sonnet-5"],
            judge_name="openrouter:claude-sonnet-5", dual_judge=True,
            judge_b_backend=BACKENDS["openrouter:gpt-4o"],
            judge_b_name="openrouter:gpt-4o-copy")


def test_dual_judges_must_differ_in_family():
    # both judges in the same family defeats the point — must raise
    with pytest.raises(ValueError, match="distinct families"):
        run_dual(dual_judge=True,
                 judge_b_backend=JudgeA(),
                 judge_b_name="openrouter:gpt-4o-mini")  # same openai family as judge A


def test_summary_reports_per_band_dual_metrics():
    s = run_dual(dual_judge=True,
                 judge_b_backend=BACKENDS["openrouter:claude-sonnet-5"],
                 judge_b_name="openrouter:claude-sonnet-5")
    cell = s["targets"]["qwen3.5:4b"]["balanced"]
    assert cell["bands"] == {"escalatory": {"avg_score": pytest.approx(0.7),
                                            "agreement": pytest.approx(0.0),
                                            "n": 2}}
