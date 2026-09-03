"""Q2 (#126) tests: majority resolver, synthetic anchors, strata quotas."""

import random
from unittest.mock import patch

import pytest

from kultivait.distill.corpus import Anchor, TRUST_UNLABELED
from kultivait.distill.generator import (
    build_synthetic_frontier_anchors,
    generate_corpus,
    resolve_majority_label,
    validate_synthetic_anchor,
)


# ---------------------------------------------------------------- majority


def test_unanimous_three():
    tier, unanimous = resolve_majority_label(["frontier", "frontier", "frontier"])
    assert tier == "frontier" and unanimous is True


def test_unanimous_two_of_two():
    tier, unanimous = resolve_majority_label(["contested", "contested"])
    assert tier == "contested" and unanimous is True


def test_majority_two_of_three():
    tier, unanimous = resolve_majority_label(["frontier", "frontier", "contested"])
    assert tier == "frontier" and unanimous is False


def test_none_labels_excluded():
    tier, unanimous = resolve_majority_label([None, "frontier", "frontier"])
    assert tier == "frontier" and unanimous is False  # not unanimous (one None)


def test_full_disagreement_returns_none():
    tier, unanimous = resolve_majority_label(["local", "contested", "frontier"])
    assert tier is None and unanimous is False


def test_all_none_returns_none():
    tier, _ = resolve_majority_label([None, None, None])
    assert tier is None


def test_grok_alone_cannot_starve():
    """The Gen-3 finding: grok says contested; if 2 others say frontier, frontier wins."""
    tier, _ = resolve_majority_label(["contested", "frontier", "frontier"])
    assert tier == "frontier"  # grok's contested vote is outvoted


# ---------------------------------------------------------------- synthetic anchors


def test_anchors_have_frontier_tier():
    for a in build_synthetic_frontier_anchors(8):
        assert a["tier"] == "frontier"


def test_anchors_prompts_substantial():
    for a in build_synthetic_frontier_anchors(8):
        assert len(a["prompt"]) > 30  # substantial, not trivial


def test_anchors_task_types_valid():
    for a in build_synthetic_frontier_anchors(8):
        assert a["task_type"] in ("architecture", "debugging", "compound")


def test_anchor_count():
    assert len(build_synthetic_frontier_anchors(12)) == 12


def test_validate_good_anchor():
    a = {"prompt": "Design the architecture for a distributed system with consistency.", "tier": "frontier", "task_type": "architecture"}
    assert validate_synthetic_anchor(a) is True


def test_validate_bad_tier():
    a = {"prompt": "x" * 50, "tier": "local", "task_type": "architecture"}
    assert validate_synthetic_anchor(a) is False


def test_validate_short_prompt():
    a = {"prompt": "too short", "tier": "frontier", "task_type": "architecture"}
    assert validate_synthetic_anchor(a) is False


def test_validate_bad_task_type():
    a = {"prompt": "x" * 50, "tier": "frontier", "task_type": "unknown"}
    assert validate_synthetic_anchor(a) is False


# ---------------------------------------------------------------- strata with frontier seeds


def make_fns():
    state = {"i": 0}
    def vary_fn(seed, band, tt):
        state["i"] += 1
        return f"{band} {tt} prompt about work {state['i']}"
    def label_fn(prompt):
        # label based on the band embedded in the variation text
        if "frontier" in prompt[:30]:
            return "frontier"
        if "local" in prompt[:30]:
            return "local"
        return "contested"
    def rewrite_fn(prompt, tier):
        return f"rewrite: {prompt}"
    return vary_fn, label_fn, rewrite_fn


def seeds_with_frontier():
    seeds = []
    for i, tier in enumerate(["contested", "frontier", "local"]):
        seeds.append(Anchor(f"{tier} seed {i}", "", TRUST_UNLABELED, f"{tier}-task", f"s{i}"))
    return seeds


def test_strata_produces_frontier_pairs():
    """The starvation-kill: with frontier seeds and honest labels, frontier pairs land."""
    vary, label, rewrite = make_fns()
    report = generate_corpus(
        seeds_with_frontier(), vary_fn=vary, label_fn=label, rewrite_fn=rewrite,
        target_pairs=6, strata={"contested": 0.4, "local": 0.3, "frontier": 0.3},
        rng=random.Random(42), attempt_budget=30,
    )
    assert report.stats["per_stratum"].get("frontier", 0) > 0
    assert report.stats["per_stratum"].get("contested", 0) > 0
    assert report.stats["per_stratum"].get("local", 0) > 0
