"""Versioned routing-quality evaluation (Map #221 Phase 1 / the #222 pin).

Pre-registered per ADR 0015: the bars below are PINNED in code before any
run — no soft grading, no retroactive adjustment. A run either passes every
bar or fails honestly, with per-case dispositions.

The runner is model-free and deterministic: it scores ROUTING DECISIONS
(embedding classification against the pinned dataset) and POLICY outcomes
(the length rule and tool-capability resolution), never generated text.
The route-regret ceiling (<=10%) is the live design-partner bar computed
from consented outcome labels — it is NOT evaluable here and is not
silently substituted.
"""

import json
import time
from pathlib import Path

DATASET_VERSION = "routing-v1-20260913"

CATEGORIES = (
    "coding_fix",
    "planning",
    "tool_call",
    "long_context",
    "provider_failure",
    "local_only",
    "secret_bearing",
)

# The pre-registered bars (ADR 0015 discipline; ratified via #222).
# Absolute maxima unless written as fractions (then a required minimum).
BARS = {
    "B1_dangerous_under_routes_max": 0,      # absolute count
    "B2_secret_no_cloud_egress_min": 1.0,    # required fraction
    "B3_tool_capability_match_min": 1.0,     # required fraction
    "B4_wasteful_over_route_max": 0.10,      # max fraction of local_only cases
    "B5_length_rule_holds_min": 1.0,         # required fraction
}

SCORECARD_PATH = Path.home() / ".kultivait" / "routing_eval_last.json"

LENGTH_RULE_DEFAULT_CAP = 8192  # tokens; mirrors the config default (ADR 0024)


def load_dataset(path: "str | Path") -> list[dict]:
    """Load and validate the routing dataset. Schema violations raise
    ValueError — an invalid dataset never reaches scoring."""
    path = Path(path)
    rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    seen_ids = set()
    seen_cats = set()
    for row in rows:
        rid = row.get("id")
        if not rid or rid in seen_ids:
            raise ValueError(f"missing or duplicate case id: {rid!r}")
        seen_ids.add(rid)
        cat = row.get("category")
        if cat not in CATEGORIES:
            raise ValueError(f"{rid}: unknown category {cat!r}")
        seen_cats.add(cat)
        if not row.get("prompt"):
            raise ValueError(f"{rid}: empty prompt")
        expect = row.get("expect") or {}
        if expect.get("floor") not in ("local_floor", "local_top", "frontier"):
            raise ValueError(f"{rid}: expect.floor must be local_floor|local_top|frontier")
        if expect.get("verdict") not in ("local", "frontier", "any"):
            raise ValueError(f"{rid}: expect.verdict must be local|frontier|any")
        policy = row.get("policy") or {}
        if policy.get("length_rule_forces_frontier") and not policy.get("payload_chars", 0) > 0:
            raise ValueError(f"{rid}: length-rule case needs payload_chars > 0")
    missing = set(CATEGORIES) - seen_cats
    if missing:
        raise ValueError(f"dataset incomplete — missing categories: {sorted(missing)}")
    return rows


def _rank_maps(capability_order: list[str], local_flags: dict[str, bool]) -> dict:
    """Positional semantics for dataset expectations: floor ranks keyed by
    role, not model id, so the public dataset survives garden changes."""
    local = [t for t in capability_order if local_flags.get(t, False)]
    frontier = [t for t in capability_order if not local_flags.get(t, True)]
    return {
        "rank": {t: i for i, t in enumerate(capability_order)},
        "local_floor_rank": (capability_order.index(local[0]) if local else 0),
        "local_top_rank": (capability_order.index(local[-1]) if local else 0),
        "frontier_rank": (
            capability_order.index(frontier[0]) if frontier else len(capability_order)
        ),
    }


def _floor_rank(expect: dict, maps: dict) -> int:
    if expect.get("floor") == "frontier":
        return maps["frontier_rank"]
    if expect.get("floor") == "local_floor":
        return maps["local_floor_rank"]
    return maps["local_top_rank"]


def _payload_tokens(case: dict) -> int:
    """The length-rule estimate over the declared payload (chars//4 over
    prompt + declared extra payload; mirrors server._estimate_payload_tokens)."""
    n = len(case.get("prompt") or "")
    n += sum(len(json.dumps(t)) for t in case.get("tools") or [])
    n += (case.get("policy") or {}).get("payload_chars", 0)
    return n // 4


def _tool_resolved_rank(case: dict, capability_order: list[str],
                        supports_tools: dict[str, bool], maps: dict) -> "tuple[str, int]":
    """Mirror _resolve_tier's fallback for tool-bearing requests: the serving
    tier is the most capable tools-capable tier, never a tools-incapable one."""
    classified = case["_tier"]
    if not case.get("tools"):
        return classified, maps["rank"].get(classified, 0)
    capable = [t for t in capability_order if supports_tools.get(t, True)]
    if classified in capable:
        return classified, maps["rank"].get(classified, 0)
    return capable[-1], maps["rank"].get(capable[-1], 0)


def run_eval(dataset: list[dict], *, classify, capability_order: list[str],
             local_flags: dict[str, bool], supports_tools: "dict[str, bool] | None" = None,
             length_rule_cap: int = LENGTH_RULE_DEFAULT_CAP) -> dict:
    """Score routing decisions + policy outcomes against the PINNED bars.
    `classify(prompt) -> (tier, escalated, margin)` mirrors Router.classify."""
    supports_tools = supports_tools or {}
    maps = _rank_maps(capability_order, local_flags)
    results = []
    counts = {
        "dangerous_under_routes": 0,
        "secret_cloud_egress": 0, "secret_cases": 0,
        "tool_mismatch": 0, "tool_cases": 0,
        "wasteful_over_routes": 0, "local_only_cases": 0,
        "length_rule_violations": 0, "length_cases": 0,
    }
    for case in dataset:
        tier, escalated, margin = classify(case["prompt"])
        case = {**case, "_tier": tier}
        expect = case.get("expect") or {}
        policy = case.get("policy") or {}
        rank = maps["rank"].get(tier, maps["frontier_rank"])
        is_local = local_flags.get(tier, False)
        failures = []

        # verdict expectation
        want_verdict = expect.get("verdict", "any")
        got_verdict = "local" if is_local else "frontier"
        if want_verdict != "any" and got_verdict != want_verdict:
            failures.append(f"verdict {got_verdict} != {want_verdict}")

        # dangerous under-route: below the floor
        floor = _floor_rank(expect, maps)
        if rank < floor:
            if expect.get("dangerous_under_route"):
                counts["dangerous_under_routes"] += 1
                failures.append("dangerous under-route below floor")
            else:
                failures.append("under floor")

        # wasteful over-route: local-only work sent to the cloud
        if expect.get("wasteful_over_route"):
            counts["local_only_cases"] += 1
            if not is_local:
                counts["wasteful_over_routes"] += 1
                failures.append("wasteful over-route (cloud for local-only work)")

        # secret-bearing: cloud egress forbidden
        if policy.get("no_cloud_egress"):
            counts["secret_cases"] += 1
            if not is_local:
                counts["secret_cloud_egress"] += 1
                failures.append("cloud egress on a secret-bearing prompt")

        # tool capability: never lands on a tools-incapable tier
        if policy.get("tools_require_capability") and case.get("tools"):
            counts["tool_cases"] += 1
            resolved, resolved_rank = _tool_resolved_rank(
                case, capability_order, supports_tools, maps
            )
            if resolved_rank < floor:
                counts["tool_mismatch"] += 1
                failures.append(f"tool resolution → {resolved}, below floor")

        # length rule: declared over-cap payloads force frontier by policy
        if policy.get("length_rule_forces_frontier"):
            counts["length_cases"] += 1
            over_cap = _payload_tokens(case) > length_rule_cap
            if over_cap and got_verdict != "frontier":
                counts["length_rule_violations"] += 1
                failures.append("over-cap payload did not force frontier")
            if not over_cap:
                counts["length_rule_violations"] += 1
                failures.append("case payload not actually over cap (dataset bug)")

        results.append({
            "id": case["id"], "category": case["category"], "tier": tier,
            "verdict": got_verdict, "margin": round(float(margin), 4),
            "passed": not failures, "failures": failures,
        })

    bars = {
        "B1_dangerous_under_routes_max": {
            "bar": BARS["B1_dangerous_under_routes_max"],
            "observed": counts["dangerous_under_routes"],
            "passed": counts["dangerous_under_routes"] <= BARS["B1_dangerous_under_routes_max"],
        },
        "B2_secret_no_cloud_egress_min": {
            "bar": BARS["B2_secret_no_cloud_egress_min"],
            "observed": (round(1 - counts["secret_cloud_egress"] / counts["secret_cases"], 4)
                         if counts["secret_cases"] else 1.0),
            "passed": True,
        },
        "B3_tool_capability_match_min": {
            "bar": BARS["B3_tool_capability_match_min"],
            "observed": (round(1 - counts["tool_mismatch"] / counts["tool_cases"], 4)
                         if counts["tool_cases"] else 1.0),
            "passed": True,
        },
        "B4_wasteful_over_route_max": {
            "bar": BARS["B4_wasteful_over_route_max"],
            "observed": (round(counts["wasteful_over_routes"] / counts["local_only_cases"], 4)
                         if counts["local_only_cases"] else 0.0),
            "passed": True,
        },
        "B5_length_rule_holds_min": {
            "bar": BARS["B5_length_rule_holds_min"],
            "observed": (round(1 - counts["length_rule_violations"] / counts["length_cases"], 4)
                         if counts["length_cases"] else 1.0),
            "passed": True,
        },
    }
    if counts["secret_cases"]:
        bars["B2_secret_no_cloud_egress_min"]["passed"] = (
            bars["B2_secret_no_cloud_egress_min"]["observed"]
            >= BARS["B2_secret_no_cloud_egress_min"]
        )
    if counts["tool_cases"]:
        bars["B3_tool_capability_match_min"]["passed"] = (
            bars["B3_tool_capability_match_min"]["observed"]
            >= BARS["B3_tool_capability_match_min"]
        )
    if counts["local_only_cases"]:
        bars["B4_wasteful_over_route_max"]["passed"] = (
            bars["B4_wasteful_over_route_max"]["observed"]
            <= BARS["B4_wasteful_over_route_max"]
        )
    if counts["length_cases"]:
        bars["B5_length_rule_holds_min"]["passed"] = (
            bars["B5_length_rule_holds_min"]["observed"]
            >= BARS["B5_length_rule_holds_min"]
        )

    by_category: dict = {}
    for r in results:
        c = by_category.setdefault(r["category"], {"cases": 0, "passed": 0})
        c["cases"] += 1
        c["passed"] += 1 if r["passed"] else 0

    passed = all(b["passed"] for b in bars.values())
    return {
        "dataset_version": DATASET_VERSION,
        "ts": time.time(),
        "passed": passed,
        "bars": bars,
        "counts": counts,
        "by_category": by_category,
        "failures": [r for r in results if not r["passed"]],
        "results": results,
        "note": ("route-regret (<=10%) is the live design-partner bar from consented "
                 "outcome labels; it is not evaluable in this runner"),
    }


def save_scorecard(scorecard: dict, path: "Path | None" = None) -> Path:
    path = Path(path) if path else SCORECARD_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(scorecard, indent=1))
    return path


def passing_scorecard_exists(path: "Path | None" = None) -> "dict | None":
    """The centroid-cutover guard's evidence: a scorecard from the pinned
    dataset whose every pre-registered bar passed. None otherwise."""
    path = Path(path) if path else SCORECARD_PATH
    if not path.is_file():
        return None
    try:
        card = json.loads(path.read_text())
    except Exception:
        return None
    if card.get("dataset_version") != DATASET_VERSION or card.get("passed") is not True:
        return None
    return card


def format_scorecard(scorecard: dict) -> str:
    lines = [
        f"routing eval — {scorecard['dataset_version']}",
        "",
        f"  overall   {'PASS' if scorecard['passed'] else 'FAIL'}",
        "",
        "  bars (pre-registered, no soft grading):",
    ]
    for name, b in scorecard["bars"].items():
        lines.append(
            f"    {'PASS' if b['passed'] else 'FAIL'}  {name:<38} "
            f"observed {b['observed']} vs bar {b['bar']}"
        )
    lines += ["", "  by category:"]
    for cat, c in sorted(scorecard["by_category"].items()):
        lines.append(f"    {cat:<18} {c['passed']}/{c['cases']}")
    if scorecard["failures"]:
        lines += ["", "  failed cases (disposition required):"]
        for r in scorecard["failures"]:
            lines.append(f"    {r['id']} [{r['category']}] → {r['tier']}: {'; '.join(r['failures'])}")
    lines += ["", f"  {scorecard['note']}"]
    return "\n".join(lines)
