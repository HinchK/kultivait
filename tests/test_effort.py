import inspect
import pytest
from dataclasses import FrozenInstanceError

from kultivait.effort import (
    DEFAULT_EFFORT_OVERRIDES,
    EffortPlan,
    load_effort_overrides,
    resolve_effort,
)


def test_effort_plan_dataclass_frozen():
    plan = EffortPlan(canonical="fast", cli_flags=["--effort", "low"], model_override=None)
    assert plan.canonical == "fast"
    assert plan.cli_flags == ["--effort", "low"]
    assert plan.model_override is None

    with pytest.raises(FrozenInstanceError):
        plan.canonical = "deep"


def test_signature_excludes_fit_and_confidence():
    sig = inspect.signature(resolve_effort)
    params = list(sig.parameters.keys())
    assert params == ["complexity", "task_type", "target_cli", "overrides"]
    assert "fit" not in params
    assert "confidence" not in params


@pytest.mark.parametrize(
    "complexity,expected_canonical",
    [
        (1, "fast"),
        (2, "fast"),
        (3, "fast"),
        (4, "balanced"),
        (5, "balanced"),
        (6, "balanced"),
        (7, "deep"),
        (8, "deep"),
        (9, "deep"),
    ],
)
def test_complexity_bands_with_debugging(complexity, expected_canonical):
    plan = resolve_effort(complexity, "debugging", "claude")
    assert plan.canonical == expected_canonical


@pytest.mark.parametrize(
    "task_type",
    ["simple_edit", "docs_lookup", "underspecified"],
)
def test_task_type_caps_at_balanced(task_type):
    assert resolve_effort(2, task_type, "claude").canonical == "fast"
    assert resolve_effort(5, task_type, "claude").canonical == "balanced"
    assert resolve_effort(8, task_type, "claude").canonical == "balanced"


@pytest.mark.parametrize(
    "task_type",
    ["architecture", "compound"],
)
def test_task_type_step_up(task_type):
    assert resolve_effort(2, task_type, "claude").canonical == "balanced"
    assert resolve_effort(5, task_type, "claude").canonical == "deep"
    assert resolve_effort(8, task_type, "claude").canonical == "deep"


def test_debugging_tracks_band():
    assert resolve_effort(2, "debugging", "claude").canonical == "fast"
    assert resolve_effort(5, "debugging", "claude").canonical == "balanced"
    assert resolve_effort(8, "debugging", "claude").canonical == "deep"


@pytest.mark.parametrize(
    "invalid_complexity",
    [0, 10, -1, 100, None, "three"],
)
def test_invalid_complexity_defaults_to_balanced(invalid_complexity):
    plan = resolve_effort(invalid_complexity, "debugging", "claude")
    assert plan.canonical == "balanced"

    plan_arch = resolve_effort(invalid_complexity, "architecture", "claude")
    assert plan_arch.canonical == "balanced"


@pytest.mark.parametrize(
    "unknown_task_type",
    ["unknown", "", "magic", None],
)
def test_unknown_task_type_defaults_to_balanced(unknown_task_type):
    plan = resolve_effort(2, unknown_task_type, "claude")
    assert plan.canonical == "balanced"

    plan8 = resolve_effort(8, unknown_task_type, "claude")
    assert plan8.canonical == "balanced"


@pytest.mark.parametrize(
    "complexity,task_type,expected_flags",
    [
        (2, "debugging", ["--effort", "low"]),
        (5, "debugging", ["--effort", "medium"]),
        (8, "debugging", ["--effort", "high"]),
    ],
)
def test_claude_projection(complexity, task_type, expected_flags):
    plan = resolve_effort(complexity, task_type, "claude")
    assert plan.cli_flags == expected_flags
    assert plan.model_override is None


@pytest.mark.parametrize(
    "complexity,task_type,expected_flags",
    [
        (2, "debugging", ["--effort", "low"]),
        (5, "debugging", ["--effort", "medium"]),
        (8, "debugging", ["--effort", "high"]),
    ],
)
def test_agy_projection(complexity, task_type, expected_flags):
    plan = resolve_effort(complexity, task_type, "agy")
    assert plan.cli_flags == expected_flags
    assert plan.model_override is None


@pytest.mark.parametrize(
    "complexity,task_type,expected_flags",
    [
        (2, "debugging", ["-c", "model_reasoning_effort=low"]),
        (5, "debugging", ["-c", "model_reasoning_effort=medium"]),
        (8, "debugging", ["-c", "model_reasoning_effort=high"]),
    ],
)
def test_codex_projection(complexity, task_type, expected_flags):
    plan = resolve_effort(complexity, task_type, "codex")
    assert plan.cli_flags == expected_flags
    assert plan.model_override is None


@pytest.mark.parametrize(
    "complexity,task_type,expected_flags",
    [
        (2, "debugging", ["--variant", "low"]),
        (5, "debugging", ["--variant", "medium"]),
        (8, "debugging", ["--variant", "high"]),
    ],
)
def test_opencode_projection(complexity, task_type, expected_flags):
    plan = resolve_effort(complexity, task_type, "opencode")
    assert plan.cli_flags == expected_flags
    assert plan.model_override is None


@pytest.mark.parametrize(
    "complexity,task_type,expected_canonical,expected_override",
    [
        (2, "debugging", "fast", "fast"),
        (5, "debugging", "balanced", "balanced"),
        (8, "debugging", "deep", "deep"),
    ],
)
def test_gemini_projection(complexity, task_type, expected_canonical, expected_override):
    plan = resolve_effort(complexity, task_type, "gemini")
    assert plan.canonical == expected_canonical
    assert plan.cli_flags == []
    assert plan.model_override == expected_override


def test_unknown_target_cli_projection():
    plan = resolve_effort(8, "debugging", "unknown_cli")
    assert plan.canonical == "deep"
    assert plan.cli_flags == []
    assert plan.model_override is None


def test_overrides_target_specific_win():
    overrides = {"codex": "deep"}
    plan = resolve_effort(2, "simple_edit", "codex", overrides=overrides)
    assert plan.canonical == "deep"
    assert plan.cli_flags == ["-c", "model_reasoning_effort=high"]

    plan_claude = resolve_effort(2, "simple_edit", "claude", overrides=overrides)
    assert plan_claude.canonical == "fast"
    assert plan_claude.cli_flags == ["--effort", "low"]


def test_overrides_default_win():
    overrides = {"default": "deep"}
    plan = resolve_effort(2, "simple_edit", "claude", overrides=overrides)
    assert plan.canonical == "deep"
    assert plan.cli_flags == ["--effort", "high"]


def test_overrides_target_takes_precedence_over_default():
    overrides = {"claude": "fast", "default": "deep"}
    plan_claude = resolve_effort(8, "debugging", "claude", overrides=overrides)
    assert plan_claude.canonical == "fast"
    assert plan_claude.cli_flags == ["--effort", "low"]

    plan_codex = resolve_effort(2, "debugging", "codex", overrides=overrides)
    assert plan_codex.canonical == "deep"
    assert plan_codex.cli_flags == ["-c", "model_reasoning_effort=high"]


def test_default_effort_overrides_is_empty():
    assert DEFAULT_EFFORT_OVERRIDES == {}


def test_load_effort_overrides():
    assert load_effort_overrides(None) == {}
    assert load_effort_overrides({}) == {}
    assert load_effort_overrides({"other": 1}) == {}
    assert load_effort_overrides({"effort": "not a dict"}) == {}

    config = {"effort": {"codex": "deep", "default": "balanced"}}
    loaded = load_effort_overrides(config)
    assert loaded == {"codex": "deep", "default": "balanced"}
