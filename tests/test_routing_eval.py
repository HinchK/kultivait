"""#224: versioned routing-quality evaluation with pre-registered bars.

Covers dataset validation, model-free runner scoring (dangerous under-routes,
secret no-egress, tool-capability resolution, wasteful over-routes, the
length-rule policy check), pinned-bar fail behavior, the scorecard the
centroid-cutover guard reads, and the guard itself.
"""

import json
from pathlib import Path

import pytest

from kultivait import routing_eval

# a deterministic routing fixture: category -> tier, all in capability order
ORDER = ["qwen3.5:4b", "qwen3:14b", "frontier:docs", "frontier:architect"]
LOCAL = {"qwen3.5:4b": True, "qwen3:14b": True, "frontier:docs": False, "frontier:architect": False}
SUPPORTS_TOOLS = {"qwen3.5:4b": True, "qwen3:14b": True, "frontier:docs": True, "frontier:architect": True}

GOOD_ROUTES = {
    "coding_fix": "qwen3:14b",
    "planning": "frontier:architect",
    "tool_call": "qwen3:14b",
    "long_context": "frontier:architect",
    "provider_failure": "qwen3:14b",
    "local_only": "qwen3.5:4b",
    "secret_bearing": "qwen3:14b",
}


def _classifier(mapping):
    def classify(prompt):
        # long-context prompts carry no category tag: the fixture dataset
        # routes by category prefix baked into each prompt's id lookup
        return mapping(prompt)
    return classify


def _make_case(**kw):
    base = {
        "id": "t-001", "category": "coding_fix",
        "prompt": "diagnose this deadlock", "tools": None,
        "expect": {"floor": "local_top", "verdict": "any", "dangerous_under_route": True},
        "policy": {}, "meta": {},
    }
    base.update(kw)
    return base


def _run(dataset, tier_for):
    def classify(prompt):
        return tier_for, False, 0.5
    return routing_eval.run_eval(
        dataset, classify=classify, capability_order=ORDER,
        local_flags=LOCAL, supports_tools=SUPPORTS_TOOLS,
    )


# ----------------------------------------------------------------------
# dataset validation
# ----------------------------------------------------------------------


def test_bundled_dataset_loads_and_is_complete():
    path = Path(__file__).resolve().parent.parent / "evals" / "routing_v1.jsonl"
    rows = routing_eval.load_dataset(path)
    cats = {r["category"] for r in rows}
    assert cats == set(routing_eval.CATEGORIES)
    assert len(rows) >= 28
    secret_cases = [r for r in rows if (r.get("policy") or {}).get("no_cloud_egress")]
    assert len(secret_cases) == 4


def test_dataset_validation_rejects_bad_rows(tmp_path):
    p = tmp_path / "d.jsonl"
    p.write_text(json.dumps(_make_case()) + "\n" + json.dumps(_make_case()) + "\n")
    with pytest.raises(ValueError, match="duplicate"):
        routing_eval.load_dataset(p)
    p.write_text(json.dumps(_make_case(category="weird")) + "\n")
    with pytest.raises(ValueError, match="category"):
        routing_eval.load_dataset(p)
    p.write_text(json.dumps(_make_case(expect={"floor": "9b", "verdict": "any"})) + "\n")
    with pytest.raises(ValueError, match="floor"):
        routing_eval.load_dataset(p)
    p.write_text(json.dumps(_make_case(policy={"length_rule_forces_frontier": True, "payload_chars": 0})) + "\n")
    with pytest.raises(ValueError, match="payload"):
        routing_eval.load_dataset(p)
    p.write_text(json.dumps(_make_case(category="planning",
                                        expect={"floor": "frontier", "verdict": "any"})) + "\n")
    with pytest.raises(ValueError, match="incomplete"):
        routing_eval.load_dataset(p)


# ----------------------------------------------------------------------
# runner scoring against the pinned bars
# ----------------------------------------------------------------------


def _full_dataset():
    out = []
    for cat, tier in GOOD_ROUTES.items():
        for i in range(2):
            out.append(_make_case(
                id=f"{cat[:2]}-{i:03d}", category=cat,
                prompt=f"{cat} case {i}",
                expect=_expect_for(cat), policy=_policy_for(cat),
                tools=[{"type": "function", "function": {"name": "bash", "parameters": {}}}]
                if cat == "tool_call" else None,
            ))
    return out


def _expect_for(cat):
    if cat in ("coding_fix", "tool_call", "provider_failure", "secret_bearing"):
        return {"floor": "local_top", "verdict": "any", "dangerous_under_route": True}
    if cat == "planning":
        return {"floor": "frontier", "verdict": "any", "dangerous_under_route": True}
    if cat == "long_context":
        return {"floor": "frontier", "verdict": "frontier", "dangerous_under_route": True}
    if cat == "local_only":
        return {"floor": "local_floor", "verdict": "local", "wasteful_over_route": True}
    return {"floor": "local_top", "verdict": "any"}


def _policy_for(cat):
    if cat == "tool_call":
        return {"tools_require_capability": True}
    if cat == "long_context":
        return {"length_rule_forces_frontier": True, "payload_chars": 40000}
    if cat == "secret_bearing":
        return {"no_cloud_egress": True}
    return {}


def _tier_by_cat():
    def classify(prompt):
        for cat, tier in GOOD_ROUTES.items():
            if prompt.startswith(cat):
                return tier, False, 0.5
        return "qwen3:14b", False, 0.5
    return classify


def _run_with(classify):
    return routing_eval.run_eval(
        _full_dataset(), classify=classify, capability_order=ORDER,
        local_flags=LOCAL, supports_tools=SUPPORTS_TOOLS,
    )


def test_good_routing_passes_all_bars():
    card = _run_with(_tier_by_cat())
    assert card["passed"] is True
    assert all(b["passed"] for b in card["bars"].values())
    assert card["failures"] == []


def test_dangerous_under_route_fails_bar_one():
    def bad(prompt):
        tier = _tier_by_cat()(prompt)[0]
        # push every cloud-worthy case down to the smallest local model
        if tier.startswith("frontier"):
            return "qwen3.5:4b", False, 0.1
        return tier, False, 0.5
    card = _run_with(bad)
    assert card["bars"]["B1_dangerous_under_routes_max"]["passed"] is False
    assert card["passed"] is False
    assert any("dangerous under-route" in f for f in card["failures"][0]["failures"])


def test_secret_cloud_egress_fails_bar_two():
    def leaky(prompt):
        if prompt.startswith("secret_bearing"):
            return "frontier:architect", False, 0.9  # egress on a secret prompt
        return _tier_by_cat()(prompt)
    card = _run_with(leaky)
    assert card["bars"]["B2_secret_no_cloud_egress_min"]["passed"] is False
    assert card["passed"] is False


def test_tool_capability_mismatch_fails_bar_three():
    # only the smallest tier takes tools: tool cases classify to qwen3:14b,
    # resolution falls to qwen3.5:4b — BELOW the local_top floor
    only_small_takes_tools = dict(SUPPORTS_TOOLS, **{"qwen3:14b": False,
                                                    "frontier:docs": False,
                                                    "frontier:architect": False})
    card = routing_eval.run_eval(
        _full_dataset(), classify=_tier_by_cat(), capability_order=ORDER,
        local_flags=LOCAL, supports_tools=only_small_takes_tools,
    )
    assert card["bars"]["B3_tool_capability_match_min"]["passed"] is False
    assert card["passed"] is False


def test_wasteful_over_route_counts_against_bar_four():
    def wasteful(prompt):
        if prompt.startswith("local_only"):
            return "frontier:docs", False, 0.9
        return _tier_by_cat()(prompt)
    card = _run_with(wasteful)
    assert card["bars"]["B4_wasteful_over_route_max"]["observed"] == 1.0
    assert card["bars"]["B4_wasteful_over_route_max"]["passed"] is False


def test_length_rule_policy_check_catches_unforced_frontier():
    def local_always(prompt):
        return "qwen3:14b", False, 0.5  # over-cap payloads must force frontier
    card = _run_with(local_always)
    assert card["bars"]["B5_length_rule_holds_min"]["passed"] is False


def test_verdict_mismatch_is_reported():
    def wrong_verdict(prompt):
        if prompt.startswith("local_only"):
            return "frontier:architect", False, 0.9
        return _tier_by_cat()(prompt)
    card = _run_with(wrong_verdict)
    fails = {f["id"] for f in card["failures"]}
    assert any("verdict" in " ".join(f["failures"]) for f in card["failures"])
    assert fails


def test_scorecard_format_reports_bars_and_failures():
    card = _run_with(_tier_by_cat())
    text = routing_eval.format_scorecard(card)
    assert "routing eval —" in text and "PASS" in text
    assert "pre-registered" in text
    assert "route-regret" in text  # the honest not-evaluable note
    bad = _run_with(lambda p: ("qwen3.5:4b", False, 0.1))
    bad_text = routing_eval.format_scorecard(bad)
    assert "FAIL" in bad_text and "disposition" in bad_text


# ----------------------------------------------------------------------
# centroid advisory guard
# ----------------------------------------------------------------------


def test_guard_requires_passing_scorecard(tmp_path, monkeypatch):
    monkeypatch.setattr(routing_eval, "SCORECARD_PATH", tmp_path / "none.json")
    assert routing_eval.passing_scorecard_exists() is None

    failing = _run_with(lambda p: ("qwen3.5:4b", False, 0.1))
    path = tmp_path / "card.json"
    path.write_text(json.dumps(failing))
    monkeypatch.setattr(routing_eval, "SCORECARD_PATH", path)
    assert routing_eval.passing_scorecard_exists() is None  # failing card ≠ evidence

    passing = _run_with(_tier_by_cat())
    path.write_text(json.dumps(passing))
    card = routing_eval.passing_scorecard_exists()
    assert card is not None and card["dataset_version"] == routing_eval.DATASET_VERSION

    stale = dict(passing, dataset_version="routing-v0-old")
    path.write_text(json.dumps(stale))
    assert routing_eval.passing_scorecard_exists() is None  # version must match


def test_cutover_guard_blocks_learned_versions_without_scorecard(tmp_path, monkeypatch, capsys):
    import argparse as ap

    from kultivait import centroids as centroids_mod
    from kultivait import cli

    monkeypatch.setattr(routing_eval, "SCORECARD_PATH", tmp_path / "none.json")
    monkeypatch.setattr(centroids_mod, "load_table",
                        lambda: {"versions": {"seeds-v0": {}, "learned-v1": {}}})
    args = ap.Namespace(version="learned-v1", yes=True)
    with pytest.raises(SystemExit) as exc:
        cli.cmd_centroids_cutover(args)
    assert exc.value.code == 2
    assert "no passing routing eval" in capsys.readouterr().err

    passing = _run_with(_tier_by_cat())
    card_path = tmp_path / "card.json"
    card_path.write_text(json.dumps(passing))
    monkeypatch.setattr(routing_eval, "SCORECARD_PATH", card_path)
    flipped = {}
    monkeypatch.setattr(centroids_mod, "set_active_version",
                        lambda cfg, v: flipped.update(version=v))
    cli.cmd_centroids_cutover(args)
    assert flipped["version"] == "learned-v1"

    # seeds-v0 rollback stays unconditional — no eval needed to go back
    monkeypatch.setattr(routing_eval, "SCORECARD_PATH", tmp_path / "none.json")
    cli.cmd_centroids_cutover(ap.Namespace(version="seeds-v0", yes=True))
    assert flipped["version"] == "seeds-v0"


def test_save_scorecard_round_trip(tmp_path):
    card = _run_with(_tier_by_cat())
    path = routing_eval.save_scorecard(card, tmp_path / "card.json")
    assert routing_eval.passing_scorecard_exists(path) is not None
