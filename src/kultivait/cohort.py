"""Design-partner cohort reporting (ADR 0025 / Map #221 Phase 1 / #226).

Aggregates pull-only partner exports (the scrubbed JSONL files written by
`kultivait report --export`) — or a single local ledger — into the five
ratified lenses: billed metered cash, counterfactual savings, observed
latency, estimated time, and route regret. Route regret uses the ratified
formula EXACTLY: wrong_route labels ÷ total labeled dispatches (unlabeled
dispatches never enter the denominator), ceiling 10%. Nothing here
transmits; deletion helpers exist because the exit protocol (14-day) and
the post-memo cleanup (90-day) are product obligations, not prose.
"""

import json
import time
from pathlib import Path

REGRET_CEILING = 0.10  # the ratified routing-safety bar
REFERENCE_PRICE_IN = 3.0   # USD per MTok — the season reference price
REFERENCE_PRICE_OUT = 15.0

DELETION_LOG = Path.home() / ".kultivait" / "export_deletions.jsonl"


# ----------------------------------------------------------------------
# ingestion
# ----------------------------------------------------------------------


def load_cohort(sources: "str | Path | list") -> "tuple[list[dict], list[str]]":
    """Rows from export JSONL files (a path, a directory of *.jsonl, or a
    list). Returns (rows, files) with each row stamped `_source` so
    per-partner breakdowns and targeted deletion stay possible."""
    if isinstance(sources, (str, Path)):
        p = Path(sources)
        files = sorted(p.glob("*.jsonl")) if p.is_dir() else [p]
    else:
        files = [Path(f) for f in sources]
    rows: list[dict] = []
    for f in files:
        for line in f.read_text().splitlines():
            if line.strip():
                row = json.loads(line)
                row["_source"] = f.name
                rows.append(row)
    return rows, [str(f) for f in files]


# ----------------------------------------------------------------------
# the five lenses
# ----------------------------------------------------------------------


def _med(vals: list) -> "float | None":
    vals = sorted(v for v in vals if v is not None)
    if not vals:
        return None
    n = len(vals)
    mid = n // 2
    return vals[mid] if n % 2 else (vals[mid - 1] + vals[mid]) / 2


def _p95(vals: list) -> "float | None":
    vals = sorted(v for v in vals if v is not None)
    if not vals:
        return None
    idx = min(len(vals) - 1, max(0, round(0.95 * (len(vals) - 1))))
    return vals[idx]


def _band(tokens_in: int) -> str:
    if tokens_in < 2048:
        return "0-2k"
    if tokens_in < 8192:
        return "2-8k"
    return "8k+"


def _lenses(rows: list[dict]) -> dict:
    cloud = [r for r in rows if r.get("cloud_egress")]
    local = [r for r in rows if r.get("local")]
    labeled = [r for r in rows if r.get("outcome_label")]
    wrong = [r for r in labeled if r["outcome_label"] == "wrong_route"]
    tokens_in = sum(int(r.get("tokens_in") or 0) for r in rows)
    tokens_out = sum(int(r.get("tokens_out") or 0) for r in rows)
    metered = sum(float(r.get("cost_usd") or 0.0) for r in cloud)
    notional = sum(float(r.get("notional_usd") or 0.0) for r in rows)
    baseline = (tokens_in * REFERENCE_PRICE_IN + tokens_out * REFERENCE_PRICE_OUT) / 1e6
    lat = [float(r["latency_s"]) for r in local if r.get("latency_s") is not None]
    ft = [float(r["first_token_ms"]) for r in local if r.get("first_token_ms") is not None]
    regret = (len(wrong) / len(labeled)) if labeled else None
    return {
        "dispatches": len(rows),
        "labeled": len(labeled),
        # lens 1: billed metered cash (cloud rows only)
        "billed_metered_cash_usd": round(metered, 4),
        # lens 2: counterfactual savings at the season reference price
        "counterfactual_savings_usd": round(baseline - notional, 4),
        "baseline_usd": round(baseline, 4),
        "notional_usd": round(notional, 4),
        # lens 3: observed latency (local serving)
        "observed_latency": {
            "first_token_ms_p50": _med(ft), "first_token_ms_p95": _p95(ft),
            "total_s_p50": _med(lat), "total_s_p95": _p95(lat),
        },
        # lens 4: estimated time — local wall-clock invested vs cloud spend
        "estimated_time": {
            "local_minutes_served": round(sum(lat) / 60, 2) if lat else 0.0,
            "cloud_dispatches": len(cloud),
        },
        # lens 5: route regret, the ratified formula, no substitutes
        "route_regret": {
            "wrong_route": len(wrong), "labeled": len(labeled),
            "regret": round(regret, 4) if regret is not None else None,
            "ceiling": REGRET_CEILING,
            "within_ceiling": (regret is not None and regret <= REGRET_CEILING)
            if regret is not None else None,
        },
    }


def _breakdowns(rows: list[dict]) -> dict:
    def group(key_fn):
        out: dict = {}
        for r in rows:
            k = key_fn(r)
            if k is None:
                continue
            g = out.setdefault(k, {"dispatches": 0, "labeled": 0, "wrong_route": 0})
            g["dispatches"] += 1
            if r.get("outcome_label"):
                g["labeled"] += 1
                if r["outcome_label"] == "wrong_route":
                    g["wrong_route"] += 1
        for g in out.values():
            g["regret"] = round(g["wrong_route"] / g["labeled"], 4) if g["labeled"] else None
        return out

    return {
        "by_tier": group(lambda r: r.get("tier")),
        "by_outcome_label": group(lambda r: r.get("outcome_label")),
        "by_band": group(lambda r: _band(int(r.get("tokens_in") or 0))),
        "by_repo": group(lambda r: r.get("repo_hash")),
        "by_partner_file": group(lambda r: r.get("_source")),
    }


def cohort_report(rows: list[dict], sources: "list[str] | None" = None) -> dict:
    report = _lenses(rows)
    report["breakdowns"] = _breakdowns(rows)
    report["sources"] = sources or []
    report["note"] = ("route regret = wrong_route ÷ labeled dispatches (ratified #222 "
                      "formula; unlabeled dispatches never enter the denominator)")
    return report


def format_cohort_report(report: dict) -> str:
    r = report
    lines = [
        "cohort quality report — design partners",
        "",
        f"  dispatches           {r['dispatches']}  ({r['labeled']} labeled)",
        f"  billed metered cash  ${r['billed_metered_cash_usd']:.2f}",
        f"  counterfactual       ${r['counterfactual_savings_usd']:.2f} saved "
        f"(baseline ${r['baseline_usd']:.2f} − notional ${r['notional_usd']:.2f})",
    ]
    ol = r["observed_latency"]
    ft50 = ol["first_token_ms_p50"]
    t50 = ol["total_s_p50"]
    lines.append(
        f"  observed latency     local first-token p50 "
        f"{('%.0f ms' % ft50) if ft50 is not None else '—'} · total p50 "
        f"{('%.1f s' % t50) if t50 is not None else '—'}"
    )
    et = r["estimated_time"]
    lines.append(
        f"  estimated time       {et['local_minutes_served']} local minutes · "
        f"{et['cloud_dispatches']} cloud dispatches"
    )
    rr = r["route_regret"]
    if rr["regret"] is None:
        lines.append("  route regret         — (no labeled dispatches yet)")
    else:
        verdict = "within" if rr["within_ceiling"] else "OVER"
        lines.append(
            f"  route regret         {rr['wrong_route']}/{rr['labeled']} = "
            f"{rr['regret']:.1%}  ({verdict} the {rr['ceiling']:.0%} ceiling)"
        )
    lines += ["", "  by tier:"]
    for tier, g in sorted(r["breakdowns"]["by_tier"].items()):
        lines.append(f"    {str(tier):<24} {g['dispatches']:>5} dsp · {g['labeled']:>4} labeled")
    lines += ["  by band:"]
    for band, g in sorted(r["breakdowns"]["by_band"].items()):
        lines.append(f"    {band:<24} {g['dispatches']:>5} dsp · {g['labeled']:>4} labeled")
    if r["breakdowns"]["by_partner_file"]:
        lines += ["  by partner file:"]
        for src, g in sorted(r["breakdowns"]["by_partner_file"].items()):
            regret_txt = f"regret {g['regret']:.1%}" if g["regret"] is not None else "regret —"
            lines.append(f"    {str(src):<36} {g['dispatches']:>5} dsp · {regret_txt}")
    lines += ["", f"  {r['note']}"]
    return "\n".join(lines)


# ----------------------------------------------------------------------
# lifecycle: deletion helpers (the exit protocol, executable)
# ----------------------------------------------------------------------


def _log_deletion(entry: dict, log_path: "Path | None" = None) -> None:
    path = Path(log_path) if log_path else DELETION_LOG
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def purge_partner_exports(repo_hash: str, cohort_dir: "str | Path",
                          log_path: "Path | None" = None) -> list[str]:
    """Partner exit (the 14-day rule): delete every export file in the
    cohort dir whose rows mention this repo hash. The deletion is logged —
    the file is gone, the fact of its deletion is not."""
    cohort_dir = Path(cohort_dir)
    removed = []
    for f in sorted(cohort_dir.glob("*.jsonl")):
        text = f.read_text()
        if f'"{repo_hash}"' in text:
            f.unlink()
            removed.append(f.name)
            _log_deletion({"ts": time.time(), "file": f.name, "reason": "partner_exit",
                           "repo_hash": repo_hash}, log_path)
    return removed


def purge_older_exports(cohort_dir: "str | Path", older_than_days: int = 90,
                        log_path: "Path | None" = None,
                        now: "float | None" = None) -> list[str]:
    """Post-memo cleanup (the 90-day rule): delete export files older than
    the given age in days, by file mtime."""
    cohort_dir = Path(cohort_dir)
    now = now if now is not None else time.time()
    cutoff = now - older_than_days * 86400
    removed = []
    for f in sorted(cohort_dir.glob("*.jsonl")):
        if f.stat().st_mtime < cutoff:
            f.unlink()
            removed.append(f.name)
            _log_deletion({"ts": now, "file": f.name, "reason": "post_memo_cleanup",
                           "older_than_days": older_than_days}, log_path)
    return removed
