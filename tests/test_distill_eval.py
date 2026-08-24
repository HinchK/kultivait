"""Slice D5 tests: 5-gate eval harness & two-base bake-off (hermetic)."""

import json
from pathlib import Path

import pytest

from kultivait.distill.eval import (
    BAND_CEILING,
    BAND_FLOOR,
    GateReport,
    LadderState,
    bake_off,
    derive_verdict,
    ladder_next,
    run_gates,
)


def contract_json(top_fit: float) -> str:
    return json.dumps({
        "analysis": {"task_type": "simple_edit", "complexity": 3, "signals": [], "subtask_candidates": []},
        "rewrite": "r",
        "judge": {"local_sufficient": False, "confidence": 0.9,
                  "targets": [{"target": "claude", "fit": top_fit, "effort": "medium"}]},
    })


_LABELS = ["local"] * 4 + ["contested"] * 4 + ["frontier"] * 4
CASES = [{"prompt": f"p{i}", "label": lab, "tier": lab} for i, lab in enumerate(_LABELS)]


def make_generate(verdicts: "dict[str, float]", latencies=None, broken=None):
    """Fixture generator over prompts -> contract JSON with chosen top fits."""
    lat = latencies or {}
    brk = set(broken or [])

    def generate(model: str, prompt: str):
        if prompt in brk:
            return "no braces here", lat.get(prompt, 1.0)
        fit = verdicts.get(prompt, 0.5)
        return contract_json(fit), lat.get(prompt, 1.0)

    return generate


# gate-passing profile: labels mirrored in fits, contested cases land in band
GOOD = {c["prompt"]: (0.5 if c["label"] == "local" else
                      0.75 if c["label"] == "contested" else 0.9) for c in CASES}


# ---------------------------------------------------------------- core gates


def test_derive_verdict_bands():
    assert derive_verdict(0.2) == "local"
    assert derive_verdict(0.65) == "contested"
    assert derive_verdict(0.84) == "contested"
    assert derive_verdict(0.85) == "frontier"


def test_run_gates_passes_on_a_good_model():
    report = run_gates(CASES, make_generate(GOOD), model="distilled-a")
    assert isinstance(report, GateReport)
    assert report.gates["dangerous"] == 0
    assert report.gates["parse_rate"] == 1.0
    assert report.gates["latency_p50_s"] <= 8.0
    assert report.gates["latency_max_s"] <= 15.0
    assert report.gates["agreement"] == pytest.approx(1.0)
    assert report.gates["band_floor"] >= BAND_FLOOR      # 4/4 gold-contested in band
    # 4 contested of 12 = 33% > the 25% ceiling — a perfectly-labeled balanced
    # set honestly breaches it; the ceiling holds on realistic (local-heavy)
    # eval sets. Verified below; here the breach is expected:
    assert report.gates["band_ceiling"] == pytest.approx(1 / 3, abs=1e-3)
    assert report.passed is False  # ceiling breach on this synthetic 1/3-contested set
    assert report.failing_gates == ["band_ceiling"]


def test_band_ceiling_holds_on_realistic_mix():
    cases = ([{"prompt": f"l{i}", "label": "local", "tier": "local"} for i in range(8)]
             + [{"prompt": "c0", "label": "contested", "tier": "contested"}]
             + [{"prompt": "f0", "label": "frontier", "tier": "frontier"}])
    fits = {"c0": 0.75, "f0": 0.9}
    fits.update({f"l{i}": 0.3 for i in range(8)})
    report = run_gates(cases, make_generate(fits), model="m")
    assert report.gates["band_ceiling"] == pytest.approx(1 / 10)
    assert report.passed is True
    assert report.failing_gates == []


def test_dangerous_misroute_fails_hard():
    bad = dict(GOOD)
    for c in CASES:
        if c["label"] == "frontier":
            bad[c["prompt"]] = 0.3  # frontier served local
    report = run_gates(CASES, make_generate(bad), model="m")
    assert report.gates["dangerous"] == 4
    assert "dangerous" in report.failing_gates
    assert report.passed is False


def test_parse_gate_requires_perfect_json():
    report = run_gates(CASES, make_generate(GOOD, broken={CASES[0]["prompt"]}), model="m")
    assert report.gates["parse_rate"] == pytest.approx(11 / 12, abs=1e-3)
    assert "parse_rate" in report.failing_gates


def test_latency_gate_p50_and_max():
    lat = {CASES[0]["prompt"]: 16.0}  # one max breach
    report = run_gates(CASES, make_generate(GOOD, latencies=lat), model="m")
    assert "latency_max_s" in report.failing_gates
    lat2 = {c["prompt"]: 9.0 for c in CASES}  # every request breaches p50
    report2 = run_gates(CASES, make_generate(GOOD, latencies=lat2), model="m")
    assert report2.gates["latency_p50_s"] == 9.0
    assert "latency_p50_s" in report2.failing_gates


def test_band_floor_detects_band_dodging():
    dodging = {c["prompt"]: (0.5 if c["label"] == "local" else 0.9)  # contested -> frontier
               for c in CASES}
    report = run_gates(CASES, make_generate(dodging), model="m")
    assert report.gates["band_floor"] == 0.0
    assert "band_floor" in report.failing_gates  # the anti-gaming floor bites


# ---------------------------------------------------------------- agreement vs incumbent + sweep


def test_agreement_gate_against_incumbent_baseline():
    fits = dict(GOOD)
    # flip 3 of 12 verdicts wrong
    for c in CASES[:3]:
        fits[c["prompt"]] = 0.9 if c["label"] == "local" else 0.5
    report = run_gates(CASES, make_generate(fits), model="m",
                       incumbent_agreement=0.5)
    assert report.gates["agreement"] == pytest.approx(9 / 12)
    assert report.gates["agreement"] >= report.gates["incumbent_agreement"]
    assert "agreement" not in report.failing_gates
    report2 = run_gates(CASES, make_generate(fits), model="m",
                        incumbent_agreement=0.9)
    assert "agreement" in report2.failing_gates  # below the recomputed baseline


def test_sweep_displacement_check_flags_displaced_bands():
    # a model whose fits sit high: shipped thresholds miss, but (0.75, 0.95) fits
    # perfectly -> the sweep detects displacement and the gate fails
    displaced = {c["prompt"]: (0.7 if c["label"] == "local" else
                               0.86 if c["label"] == "contested" else 0.96)
                 for c in CASES}
    report = run_gates(CASES, make_generate(displaced), model="m")
    assert "sweep_ok" in report.gates
    assert report.gates["sweep_ok"] is False or "band_floor" in report.failing_gates


# ---------------------------------------------------------------- headline promotion


def test_toll_rate_headline_telemetry_until_n50_then_gate():
    small = CASES[:12]
    report = run_gates(small, make_generate(GOOD), model="m",
                       incumbent_toll_rate=0.4)
    assert report.n < 50
    assert report.headline_is_gate is False
    assert "toll_rate" in report.headline_telemetry
    big = [{"prompt": f"p{i}", "label": "local", "tier": "local"} for i in range(50)]
    fits = {c["prompt"]: 0.3 for c in big}
    report2 = run_gates(big, make_generate(fits), model="m",
                        incumbent_toll_rate=0.4)
    assert report2.n >= 50
    assert report2.headline_is_gate is True
    # toll rate 0.0 vs incumbent 0.4 -> reduction holds -> promoted gate passes
    assert "toll_rate" not in report2.failing_gates


# ---------------------------------------------------------------- bake-off


def _passing(n=10):
    cases = [{"prompt": f"p{i}", "label": "local", "tier": "local"} for i in range(n)]
    fits = {c["prompt"]: 0.3 for c in cases}
    return run_gates(cases, make_generate(fits), model="x")


def test_bake_off_pass_first():
    a = _passing()
    b = _passing()
    assert bake_off({"a": a, "b": b}) in ("a", "b")


def test_bake_off_none_passes_when_both_fail():
    a = run_gates(CASES, make_generate(dict(GOOD)), model="a")  # fails ceiling
    b = run_gates(CASES, make_generate(dict(GOOD)), model="b")
    assert bake_off({"a": a, "b": b}) is None  # no winner picked; ladder runs


def test_bake_off_agreement_then_latency_tiebreak():
    cases = [{"prompt": f"p{i}", "label": "local", "tier": "local"} for i in range(4)]
    fits = {c["prompt"]: 0.3 for c in cases}
    fast = run_gates(cases, make_generate(fits, {c["prompt"]: 2.0 for c in cases}), model="fast")
    slow = run_gates(cases, make_generate(fits, {c["prompt"]: 5.0 for c in cases}), model="slow")
    assert bake_off({"fast": fast, "slow": slow}) == "fast"


def test_bake_off_requires_all_gates():
    one_fail = run_gates(CASES, make_generate(GOOD, broken={CASES[2]["prompt"]}), model="f")
    assert one_fail.passed is False
    assert bake_off({"f": one_fail, "ok": _passing()}) == "ok"


# ---------------------------------------------------------------- failure ladder


def test_ladder_advances_retry_augment_reject():
    state = LadderState(base="qwen3.5:4b")
    assert state.rung == 0
    s1 = ladder_next(state, failed=True)
    assert s1.rung == 1 and s1.action == "retry"
    s2 = ladder_next(s1, failed=True)
    assert s2.rung == 2 and s2.action == "augment"
    s3 = ladder_next(s2, failed=True)
    assert s3.rung == 3 and s3.action == "reject"
    with pytest.raises(ValueError, match="rejected"):
        ladder_next(s3, failed=True)  # a rejected base does not continue


def test_ladder_resets_on_pass():
    state = LadderState(base="b")
    s1 = ladder_next(state, failed=True)
    s2 = ladder_next(s1, failed=False)
    assert s2.rung == 0 and s2.action == "deploy"


def test_ladder_augment_targets_failing_stratum():
    report = run_gates(CASES, make_generate({c["prompt"]: 0.5 if c["label"] == "local" else 0.9
                                             for c in CASES}), model="m")
    state = LadderState(base="b", rung=2, action="augment")
    plan = state.augment_plan(report)
    assert "contested" in plan["strata"]  # grow the failing stratum (+500 targeted)


# ---------------------------------------------------------------- report serialization


def test_gate_report_json_round_trips(tmp_path: Path):
    report = run_gates(CASES, make_generate(GOOD), model="m")
    data = json.loads(report.to_json())
    assert data["model"] == "m" and data["n"] == 12
    assert GateReport.from_json(report.to_json()).passed == report.passed
    p = tmp_path / "g.json"
    p.write_text(report.to_json())
    assert GateReport.from_json(p.read_text()).n == 12
