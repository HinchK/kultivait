"""Distillation eval harness: five gates, band discipline, bake-off, ladder
(ADR 0015).

A distilled model proves itself on the permanent held-out set through the
PRODUCTION generate path — the incumbent-baseline discovery from probe #52
is binding: raw-chat framing lies, so the evaluator takes the same
generate(model, prompt) -> (text, latency) callable the serving preprocessor
uses. Gates are pass/fail: zero dangerous misroutes (frontier-labeled cases
served local), 100% JSON parse, p50 <= 8s / max <= 15s, verdict agreement >=
the recomputed incumbent baseline, and two-sided band discipline (floor: at
least half of gold-contested cases land in the contested band — dodging the
band to fake a lower toll rate fails; ceiling: at most 25% of the set
populates the band — flooding fails) plus a threshold-sweep displacement
check. The toll-rate-reduction headline is telemetry until n >= 50 real
held-out cases, then auto-promotes to a gate. The bake-off is pass-first:
all gates, then agreement, latency p50, parse margin; neither passing means
no winner — the failure ladder (retry -> augment -> reject) runs instead.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

from kultivait.preprocessor import extract_json

VERDICT_BANDS = (0.65, 0.85)
BAND_FLOOR = 0.5
BAND_CEILING = 0.25
LATENCY_P50_S = 8.0
LATENCY_MAX_S = 15.0
HEADLINE_GATE_N = 50
SWEEP_GRID = [0.60, 0.65, 0.70], [0.80, 0.85, 0.90]
SWEEP_TOLERANCE = 0.05  # an alternative must beat shipped by more than this


def derive_verdict(max_fit: float, bands=VERDICT_BANDS) -> str:
    low, high = bands
    if max_fit < low:
        return "local"
    if max_fit >= high:
        return "frontier"
    return "contested"


def _top_fit(contract: dict) -> float:
    targets = contract.get("judge", {}).get("targets", [])
    return max((float(t.get("fit", 0.0)) for t in targets if isinstance(t, dict)),
               default=0.0)


@dataclass(frozen=True)
class GateReport:
    model: str
    n: int
    gates: dict
    passed: bool
    failing_gates: list
    headline_telemetry: dict = field(default_factory=dict)
    headline_is_gate: bool = False
    ladder_hint: str = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=1)

    @classmethod
    def from_json(cls, raw: str) -> "GateReport":
        return cls(**json.loads(raw))


def _sweep_ok(rows: list[dict]) -> bool:
    """No alternative cutpoint quietly beats the shipped bands (ADR 0015)."""
    lows, highs = SWEEP_GRID
    labels = [r["label"] for r in rows]

    def agreement_for(low: float, high: float) -> float:
        ok = sum(1 for r in rows if derive_verdict(r["max_fit"], (low, high)) == r["label"])
        return ok / len(rows) if rows else 0.0

    shipped = agreement_for(*VERDICT_BANDS)
    for low in lows:
        for high in highs:
            if (low, high) == VERDICT_BANDS:
                continue
            if agreement_for(low, high) > shipped + SWEEP_TOLERANCE:
                return False
    _ = labels
    return True


def run_gates(
    cases: list,
    generate,
    *,
    model: str,
    incumbent_agreement: "float | None" = None,
    incumbent_latency_p50_s: "float | None" = None,
    incumbent_toll_rate: "float | None" = None,
) -> GateReport:
    """Evaluate held-out ``cases`` through ``generate(model, prompt) -> (text,
    latency_s)`` — the production-path contract. All five gates are exact."""
    rows: list[dict] = []
    for case in cases:
        prompt = case.get("prompt", "")
        label = case.get("label") or case.get("tier")
        out = generate(model, prompt)
        if isinstance(out, tuple):
            raw, latency = out[0], float(out[1])
        else:
            raw, latency = str(out), 0.0
        contract, _err = extract_json(raw)
        parse_ok = contract is not None
        max_fit = _top_fit(contract) if parse_ok else 0.0
        verdict = derive_verdict(max_fit) if parse_ok else None
        rows.append({
            "label": label, "parse_ok": parse_ok, "verdict": verdict,
            "max_fit": max_fit, "latency_s": latency,
            "dangerous": parse_ok and verdict == "local" and label == "frontier",
        })

    n = len(rows)
    parsed = [r for r in rows if r["parse_ok"]]
    dangerous = sum(1 for r in rows if r["dangerous"])
    parse_rate = sum(1 for r in rows if r["parse_ok"]) / n if n else 0.0
    latencies = [r["latency_s"] for r in rows]
    p50 = statistics.median(latencies) if latencies else 0.0
    lmax = max(latencies) if latencies else 0.0
    agreement = (sum(1 for r in parsed if r["verdict"] == r["label"]) / n) if n else 0.0

    contested_cases = [r for r in parsed if r["label"] == "contested"]
    band_floor = ((sum(1 for r in contested_cases if r["verdict"] == "contested")
                   / len(contested_cases)) if contested_cases else 1.0)
    toll_rate = (sum(1 for r in parsed if r["verdict"] == "contested") / n) if n else 0.0
    band_ceiling = toll_rate
    sweep = _sweep_ok(rows)

    gates = {
        "dangerous": dangerous,
        "parse_rate": round(parse_rate, 4),
        "latency_p50_s": round(p50, 2),
        "latency_max_s": round(lmax, 2),
        "agreement": round(agreement, 4),
        "band_floor": round(band_floor, 4),
        "band_ceiling": round(band_ceiling, 4),
        "sweep_ok": sweep,
    }
    if incumbent_agreement is not None:
        gates["incumbent_agreement"] = round(incumbent_agreement, 4)
    if incumbent_latency_p50_s is not None:
        gates["incumbent_latency_p50_s"] = round(incumbent_latency_p50_s, 2)
    if incumbent_toll_rate is not None:
        gates["incumbent_toll_rate"] = round(incumbent_toll_rate, 4)

    failing: list[str] = []
    if dangerous != 0:
        failing.append("dangerous")
    if parse_rate < 1.0:
        failing.append("parse_rate")
    if p50 > LATENCY_P50_S:
        failing.append("latency_p50_s")
    if lmax > LATENCY_MAX_S:
        failing.append("latency_max_s")
    if incumbent_agreement is not None and agreement < incumbent_agreement:
        failing.append("agreement")
    if band_floor < BAND_FLOOR:
        failing.append("band_floor")
    if band_ceiling > BAND_CEILING:
        failing.append("band_ceiling")
    if not sweep:
        failing.append("sweep_ok")

    headline_telemetry = {
        "toll_rate": round(toll_rate, 4),
        "toll_rate_delta_vs_incumbent": (
            round(toll_rate - incumbent_toll_rate, 4)
            if incumbent_toll_rate is not None else None
        ),
    }
    headline_is_gate = n >= HEADLINE_GATE_N
    if headline_is_gate and incumbent_toll_rate is not None:
        if toll_rate > incumbent_toll_rate:
            failing.append("toll_rate")  # promoted: reduction must hold

    ladder_hint = ""
    if failing:
        if "band_floor" in failing or "band_ceiling" in failing:
            ladder_hint = "augment: grow the contested stratum (+500 targeted)"
        elif "agreement" in failing or "sweep_ok" in failing:
            ladder_hint = "retry: tune hyperparameters"
        else:
            ladder_hint = "retry"

    return GateReport(
        model=model, n=n, gates=gates, passed=not failing, failing_gates=failing,
        headline_telemetry=headline_telemetry, headline_is_gate=headline_is_gate,
        ladder_hint=ladder_hint,
    )


# ---------------------------------------------------------------- bake-off


def bake_off(reports: "dict[str, GateReport]") -> "str | None":
    """Pass-first winner rule: all gates, then agreement desc, latency p50
    asc, parse margin desc. No passer -> None (the ladder runs, both
    retrain); a winner is never picked from failing candidates."""
    passing = [(name, r) for name, r in reports.items() if r.passed]
    if not passing:
        return None
    ranked = sorted(
        passing,
        key=lambda kv: (
            -kv[1].gates["agreement"],
            kv[1].gates["latency_p50_s"],
            -kv[1].gates["parse_rate"],
        ),
    )
    return ranked[0][0]


# ---------------------------------------------------------------- failure ladder


ACTIONS = ["none", "retry", "augment", "reject"]


@dataclass(frozen=True)
class LadderState:
    base: str
    rung: int = 0
    action: str = "none"
    history: tuple = ()

    @property
    def rejected(self) -> bool:
        return self.action == "reject"

    def augment_plan(self, report: GateReport) -> dict:
        """The +500-targeted-synthetic plan: grow the strata the failing
        gates point at (band gates -> contested; else balance)."""
        strata = {"contested": 0.5, "local": 0.25, "frontier": 0.25}
        if "band_floor" in report.failing_gates or "band_ceiling" in report.failing_gates:
            strata = {"contested": 0.6, "local": 0.2, "frontier": 0.2}
        return {"action": "augment", "add_pairs": 500, "strata": strata,
                "failing_gates": list(report.failing_gates)}


def ladder_next(state: LadderState, *, failed: bool) -> LadderState:
    """Advance the retry -> augment -> reject ladder (ADR 0015).

    failed=False resets to rung 0 (deploy); each failure costs one rung; a
    rejected base raises instead of continuing — the incumbent stands.
    """
    if state.rejected:
        raise ValueError(f"base {state.base!r} is rejected; the incumbent stands")
    if not failed:
        return replace(state, rung=0, action="deploy",
                       history=state.history + (("pass", state.rung),))
    rung = state.rung + 1
    if rung >= len(ACTIONS) - 1:
        return replace(state, rung=len(ACTIONS) - 1, action="reject",
                       history=state.history + (("reject", rung),))
    return replace(state, rung=rung, action=ACTIONS[rung],
                   history=state.history + ((ACTIONS[rung], rung),))
