"""#71 ride-along tests: curated reasoning metadata + api-only judge selection."""

import pytest

from kultivait.api_backends import model_supports_reasoning
from kultivait.capability_eval import select_cross_family_judge
from kultivait.config import MODEL_SUPPORTS_REASONING


class FakeAPI:
    supports_tools = True
    local = False


class FakeCLI:
    supports_tools = False   # CLI backends run their own loops
    local = False


class FakeLocal:
    supports_tools = True
    local = True


# ------------------------------------------------- curated reasoning metadata


def test_curated_table_decides_known_models():
    # the #64 live failures stay False in the curated table
    assert MODEL_SUPPORTS_REASONING["meta-llama/llama-3.3-70b-instruct"] is False
    assert MODEL_SUPPORTS_REASONING["openai/gpt-4o"] is False
    assert model_supports_reasoning("meta-llama/llama-3.3-70b-instruct") is False
    assert model_supports_reasoning("openai/gpt-4o") is False
    # reasoning families stay True
    assert model_supports_reasoning("anthropic/claude-sonnet-5") is True
    assert model_supports_reasoning("x-ai/grok-4.6") is True
    assert model_supports_reasoning("openai/gpt-5.6-terra") is True


def test_curated_table_overrides_pattern_fallback():
    assert model_supports_reasoning("x-ai/grok-4.6") is True
    assert model_supports_reasoning("gpt-4o") is False


def test_basename_match_covers_unprefixed_ids():
    assert model_supports_reasoning("claude-sonnet-5") is True
    assert model_supports_reasoning("llama-3.3-70b-instruct") is False


def test_unknown_ids_fall_back_to_family_patterns():
    assert model_supports_reasoning("openai/gpt-5.7-nova") is True   # gpt-5 pattern
    assert model_supports_reasoning("some-unknown-model") is False   # no pattern


# ------------------------------------------------- api-only judge selection


def test_judge_selection_excludes_cli_backends():
    backends = {
        "qwen3.5:4b": FakeLocal(),
        "openrouter:gpt-4o": FakeAPI(),
        "agy": FakeCLI(),          # the #65 timeout culprit
        "claude": FakeCLI(),
    }
    name, b = select_cross_family_judge("qwen3.5:4b", backends)
    assert name == "openrouter:gpt-4o"
    assert isinstance(b, FakeAPI)


def test_judge_selection_never_returns_a_cli_even_under_pressure():
    # only CLI cross-family candidates exist -> raise, never fall back to CLI
    backends = {"qwen3.5:4b": FakeLocal(), "agy": FakeCLI()}
    with pytest.raises(ValueError, match="api-kind"):
        select_cross_family_judge("qwen3.5:4b", backends)


def test_judge_selection_error_mentions_pinning():
    backends = {"openrouter:gpt-4o": FakeAPI()}
    with pytest.raises(ValueError, match="pin judge_backend"):
        select_cross_family_judge("openrouter:gpt-4o", backends)  # same family


def test_judge_selection_cross_family_still_enforced():
    backends = {
        "openrouter:gpt-4o": FakeAPI(),            # openai family
        "openrouter:claude-sonnet-5": FakeAPI(),   # anthropic family
    }
    name, _ = select_cross_family_judge("openrouter:gpt-4o", backends)
    assert name == "openrouter:claude-sonnet-5"
