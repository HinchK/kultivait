"""H1 (#88) tests: adversarial mock sequences + error rendering + stability."""

import json
from pathlib import Path

import pytest

from kultivait.capability_eval import (
    TaskCase,
    _mock_response_for,
    load_corpus,
    reset_mock_counts,
)


def case(mock_responses):
    reset_mock_counts()
    return TaskCase(id="t_h1", name="t", description="", messages=[],
                    tools=[], mock_responses=mock_responses, rubric={})


# ---------------------------------------------------------------- sequences


def test_sequence_advances_per_call_and_repeats_last():
    c = case({"read_file": ["first", "second", "third"]})
    assert _mock_response_for(c, "read_file") == "first"
    assert _mock_response_for(c, "read_file") == "second"
    assert _mock_response_for(c, "read_file") == "third"
    assert _mock_response_for(c, "read_file") == "third"  # final repeats


def test_call_counts_are_per_task_per_tool():
    reset_mock_counts()
    a = TaskCase(id="t_a", name="", description="", messages=[], tools=[],
                 mock_responses={"x": ["a1", "a2"]}, rubric={})
    b = TaskCase(id="t_b", name="", description="", messages=[], tools=[],
                 mock_responses={"x": ["b1", "b2"]}, rubric={})
    assert _mock_response_for(a, "x") == "a1"
    assert _mock_response_for(b, "x") == "b1"  # independent counters
    assert _mock_response_for(a, "x") == "a2"


def test_string_mock_stays_cooperative():
    c = case({"read_file": "always the same"})
    assert _mock_response_for(c, "read_file") == "always the same"
    assert _mock_response_for(c, "read_file") == "always the same"


# ---------------------------------------------------------------- error rendering


def test_429_renders_with_retry_after():
    c = case({"api": [{"__error__": {"kind": "429", "retry_after": 3}}]})
    r = _mock_response_for(c, "api")
    assert "HTTP 429" in r and "Retry-After: 3s" in r and "not processed" in r


def test_500_renders_transient():
    c = case({"api": [{"__error__": {"kind": "500", "detail": "worker crashed"}}]})
    assert "HTTP 500" in _mock_response_for(c, "api")
    assert "Retry may succeed" in _mock_response_for(c, "api")


def test_422_renders_schema_mismatch():
    c = case({"api": [{"__error__": {"kind": "422", "detail": "missing required field"}}]})
    r = _mock_response_for(c, "api")
    assert "HTTP 422" in r and "schema" in r.lower() and "retry" in r.lower()


def test_error_then_success_sequence():
    c = case({"run_tests": [{"__error__": {"kind": "500"}}, "479 passed"]})
    first = _mock_response_for(c, "run_tests")
    assert "HTTP 500" in first
    assert _mock_response_for(c, "run_tests") == "479 passed"  # retry succeeds


# ---------------------------------------------------------------- corpus state


def test_corpus_bands_unchanged_and_sequences_present():
    tasks = load_corpus()
    from collections import Counter
    bands = Counter(t.rubric["band"] for t in tasks)
    assert bands == {"simple": 7, "contested": 7, "escalatory": 7}
    seqs = [t.id for t in tasks for v in t.mock_responses.values() if isinstance(v, list)]
    assert len(seqs) >= 12  # adversarial coverage across the two bands


def test_simple_band_stays_cooperative():
    tasks = load_corpus()
    for t in tasks:
        if t.rubric["band"] == "simple":
            assert all(isinstance(v, str) for v in t.mock_responses.values()), t.id


def test_escalatory_tasks_carry_failure_paths():
    tasks = load_corpus()
    esc = [t for t in tasks if t.rubric["band"] == "escalatory"]
    with_errors = [t.id for t in esc
                   if any(isinstance(v, list) and any(
                       isinstance(e, dict) and "__error__" in e for e in v)
                       for v in t.mock_responses.values())]
    assert len(with_errors) >= 5  # most escalatory tasks inject failures


def test_rubrics_reward_recovery():
    tasks = load_corpus()
    blob = json.dumps([t.rubric for t in tasks]).lower()
    assert "retried" in blob or "retry" in blob
    assert "rate-limit" in blob or "rate limit" in blob or "429" in blob


def test_distractor_mocks_are_deceptive_not_inert():
    tasks = load_corpus()
    decoy = [v for t in tasks for k, v in t.mock_responses.items()
             if k in ("run_shell", "send_webhook") and isinstance(v, str)]
    assert any("believes" in d or "notification sent" in d for d in decoy)
