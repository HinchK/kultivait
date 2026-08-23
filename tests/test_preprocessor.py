import json
import pytest
from dataclasses import FrozenInstanceError

from kultivait.preprocessor import (
    MARK_FAIL,
    MARK_OK,
    MARK_SKIPPED,
    MARK_TIMEOUT,
    VERDICT_THRESHOLDS,
    AnalysisResult,
    PreprocessResult,
    TargetFit,
    derive_verdict,
    run,
)


def test_derive_verdict_boundaries():
    assert VERDICT_THRESHOLDS == (0.65, 0.85)
    assert derive_verdict(0.0) == "local"
    assert derive_verdict(0.64) == "local"
    assert derive_verdict(0.649) == "local"
    assert derive_verdict(0.65) == "contested"
    assert derive_verdict(0.70) == "contested"
    assert derive_verdict(0.849) == "contested"
    assert derive_verdict(0.85) == "frontier"
    assert derive_verdict(0.90) == "frontier"
    assert derive_verdict(1.0) == "frontier"


def test_dataclasses_frozen():
    tf = TargetFit(target="claude", fit=0.9, effort="high")
    assert tf.target == "claude"
    with pytest.raises(FrozenInstanceError):
        tf.fit = 0.5

    ar = AnalysisResult(task_type="debugging", complexity=5, signals=["sig"], subtask_candidates=["task1"])
    assert ar.task_type == "debugging"
    with pytest.raises(FrozenInstanceError):
        ar.complexity = 3

    pr = PreprocessResult(
        analysis=ar,
        rewrite="rewritten",
        target_fits=[tf],
        max_fit=0.9,
        derived_verdict="frontier",
        confidence=0.8,
        raw_output={},
        latency_s=1.23,
        mark=MARK_OK,
    )
    assert pr.rewrite == "rewritten"
    with pytest.raises(FrozenInstanceError):
        pr.mark = MARK_FAIL


def test_run_success():
    sample_response = {
        "analysis": {
            "task_type": "compound",
            "complexity": 7,
            "signals": ["multi-file", "new feature"],
            "subtask_candidates": ["step 1", "step 2"],
        },
        "rewrite": "Self-contained prompt",
        "judge": {
            "local_sufficient": False,
            "confidence": 0.85,
            "targets": [
                {"target": "claude", "fit": 0.9, "effort": "high"},
                {"target": "codex", "fit": 0.8, "effort": "medium"},
            ],
        },
    }

    def fake_generate(model: str, prompt: str):
        assert "USER PROMPT:\nDo compound task" in prompt
        return json.dumps(sample_response), 0.15

    messages = [{"role": "user", "content": "Do compound task"}]
    res = run(messages, generate=fake_generate)

    assert res.mark == MARK_OK
    assert res.derived_verdict == "frontier"
    assert res.max_fit == 0.9
    assert res.rewrite == "Self-contained prompt"
    assert res.analysis.task_type == "compound"
    assert res.analysis.complexity == 7
    assert res.analysis.subtask_candidates == ["step 1", "step 2"]
    assert len(res.target_fits) == 2
    assert res.confidence == 0.85
    assert res.raw_output == sample_response
    assert res.latency_s >= 0.0


def test_run_verdict_local_and_contested():
    def make_gen(max_fit_val):
        data = {
            "analysis": {"task_type": "simple_edit", "complexity": 2, "signals": []},
            "rewrite": "rewritten",
            "judge": {
                "local_sufficient": True,
                "confidence": 0.9,
                "targets": [{"target": "claude", "fit": max_fit_val, "effort": "low"}],
            },
        }
        return lambda m, p: (json.dumps(data), 0.05)

    res_local = run([{"role": "user", "content": "edit"}], generate=make_gen(0.50))
    assert res_local.derived_verdict == "local"
    assert res_local.max_fit == 0.50

    res_contested = run([{"role": "user", "content": "edit"}], generate=make_gen(0.75))
    assert res_contested.derived_verdict == "contested"
    assert res_contested.max_fit == 0.75


def test_run_local_sufficient_ignored_when_fits_high():
    data = {
        "analysis": {"task_type": "architecture", "complexity": 8, "signals": []},
        "rewrite": "rewritten",
        "judge": {
            "local_sufficient": True,  # contradicted by 0.95 fit
            "confidence": 0.95,
            "targets": [{"target": "claude", "fit": 0.95, "effort": "high"}],
        },
    }
    res = run([{"role": "user", "content": "arch"}], generate=lambda m, p: (json.dumps(data), 0.05))
    assert res.derived_verdict == "frontier"
    assert res.raw_output["judge"]["local_sufficient"] is True


def test_run_last_user_message_only():
    captured_prompt = None

    def fake_generate(model: str, prompt: str):
        nonlocal captured_prompt
        captured_prompt = prompt
        return json.dumps({
            "analysis": {"task_type": "debugging", "complexity": 4, "signals": []},
            "rewrite": "rewritten",
            "judge": {"local_sufficient": True, "confidence": 0.8, "targets": []},
        }), 0.05

    messages = [
        {"role": "system", "content": "System prompt text"},
        {"role": "user", "content": "First user query"},
        {"role": "assistant", "content": "First assistant answer"},
        {"role": "user", "content": "Second user query"},
    ]
    res = run(messages, generate=fake_generate)
    assert res.mark == MARK_OK
    assert captured_prompt is not None
    assert "USER PROMPT:\nSecond user query" in captured_prompt
    assert "First user query" not in captured_prompt
    assert "System prompt text" not in captured_prompt


def test_run_parse_fail_prose():
    def fake_generate(model: str, prompt: str):
        return "I am unable to parse this JSON: just plain prose response.", 0.05

    messages = [{"role": "user", "content": "Hello there"}]
    res = run(messages, generate=fake_generate)

    assert res.mark == MARK_FAIL
    assert res.derived_verdict is None
    assert res.rewrite == "Hello there"
    assert res.max_fit == 0.0
    assert res.confidence == 0.0
    assert res.raw_output is None
    assert res.target_fits == []


def test_run_parse_fail_malformed_json():
    def fake_generate(model: str, prompt: str):
        return "Here is your JSON: { 'unterminated': ", 0.05

    messages = [{"role": "user", "content": "Fix code"}]
    res = run(messages, generate=fake_generate)

    assert res.mark == MARK_FAIL
    assert res.derived_verdict is None
    assert res.rewrite == "Fix code"


def test_run_timeout_error():
    def fake_generate(model: str, prompt: str):
        raise TimeoutError("Ollama request timed out")

    messages = [{"role": "user", "content": "Slow request"}]
    res = run(messages, generate=fake_generate)

    assert res.mark == MARK_TIMEOUT
    assert res.derived_verdict is None
    assert res.rewrite == "Slow request"
    assert res.max_fit == 0.0
    assert res.confidence == 0.0


def test_run_exceeds_timeout_s():
    def fake_generate(model: str, prompt: str):
        import time
        time.sleep(0.05)
        return json.dumps({
            "analysis": {"task_type": "debugging", "complexity": 4, "signals": []},
            "rewrite": "rewritten",
            "judge": {"local_sufficient": True, "confidence": 0.8, "targets": []},
        }), 0.05

    messages = [{"role": "user", "content": "Exceed budget"}]
    res = run(messages, generate=fake_generate, timeout_s=0.01)

    assert res.mark == MARK_TIMEOUT
    assert res.derived_verdict is None
    assert res.rewrite == "Exceed budget"


def test_constants_and_marks():
    assert MARK_OK == "ok"
    assert MARK_TIMEOUT == "preprocess_timeout"
    assert MARK_FAIL == "preprocess_fail"
    assert MARK_SKIPPED == "skipped"
