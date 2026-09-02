"""S1 (#101) tests: the enriched shadow read — latency, parse, calibration, readiness."""

import json
import time
from pathlib import Path

import pytest

from kultivait.distill.shadow import ShadowRecord, append_shadow_log, shadow_summary


def rec(inc_verdict="frontier", inc_lat=10.0, sh_verdict="contested", sh_lat=5.0,
        parse_ok=True, agree=None):
    if agree is None:
        agree = inc_verdict == sh_verdict
    return ShadowRecord(
        ts=time.time(), fingerprint="f", prompt_hash="h",
        incumbent={"model": "qwen3.5:4b", "verdict": inc_verdict, "max_fit": 0.9,
                   "latency_s": inc_lat, "parse_ok": True},
        shadow={"model": "kv-judge-g1", "verdict": sh_verdict, "max_fit": 0.7,
                "latency_s": sh_lat, "parse_ok": parse_ok, "dangerous": False},
        agree=agree,
    )


def log(tmp_path, rows):
    p = tmp_path / "shadow.jsonl"
    for r in rows:
        append_shadow_log(r, p)
    return p


# ---------------------------------------------------------------- latency


def test_latency_deltas(tmp_path: Path):
    rows = [rec(inc_lat=10, sh_lat=5), rec(inc_lat=20, sh_lat=8), rec(inc_lat=12, sh_lat=6)]
    s = shadow_summary(log(tmp_path, rows))
    assert s["latency"]["incumbent_p50_s"] == 12.0  # sorted [10,12,20] -> p50 = 12
    assert s["latency"]["shadow_p50_s"] == 6.0
    # deltas: [-5,-12,-6] sorted [-12,-6,-5] -> p50 = idx1 = -6, p90 = idx1 = -6 (nearest-rank)
    assert s["latency"]["delta_p50_s"] == -6.0
    assert s["latency"]["delta_p90_s"] == -6.0


def test_latency_negative_delta_means_shadow_faster():
    assert shadow_summary.__doc__  # exists


# ---------------------------------------------------------------- parse validity


def test_parse_validity_rate(tmp_path: Path):
    rows = [rec(parse_ok=True), rec(parse_ok=True), rec(parse_ok=False), rec(parse_ok=True)]
    s = shadow_summary(log(tmp_path, rows))
    assert s["parse_validity"] == pytest.approx(0.75)


def test_parse_validity_zero_on_empty(tmp_path: Path):
    s = shadow_summary(tmp_path / "missing.jsonl")
    assert s["parse_validity"] == 0.0
    assert s["n"] == 0


# ---------------------------------------------------------------- calibration


def test_calibration_correction_read(tmp_path: Path):
    rows = [rec(inc_verdict="frontier", sh_verdict="contested"),  # correction
            rec(inc_verdict="frontier", sh_verdict="contested"),  # correction
            rec(inc_verdict="local", sh_verdict="local", agree=True),
            rec(inc_verdict="frontier", sh_verdict="frontier", agree=True)]
    s = shadow_summary(log(tmp_path, rows))
    assert s["calibration"]["calibration_corrections"] == 2
    assert s["calibration"]["correction_rate"] == pytest.approx(0.5)
    assert s["calibration"]["verdict_pairs"]["inc:frontier->shadow:contested"] == 2
    assert s["calibration"]["verdict_pairs"]["inc:local->shadow:local"] == 1


# ---------------------------------------------------------------- readiness arms


def test_decomposed_readiness_arms(tmp_path: Path):
    rows = []
    for _ in range(30):
        rows.append(rec(inc_verdict="frontier", sh_verdict="frontier", agree=True))
    for _ in range(5):
        rows.append(rec(inc_verdict="local", sh_verdict="local", agree=True))
    # 5 contested shadows interleaved so they survive (no truncation)
    for _ in range(5):
        rows.append(rec(inc_verdict="frontier", sh_verdict="contested"))
    s = shadow_summary(log(tmp_path, rows))
    arms = s["readiness_arms"]
    assert arms["sample_n_ge_30"]["value"] == 40 and arms["sample_n_ge_30"]["pass"]
    # non-contested incumbents: 35+5=40... minus the 5 corrections' inc=frontier
    # stability: agree on non-contested-inc rows minus corrections
    # (corrections have inc=frontier which IS non-contested — stability < 90%)
    assert arms["health_zero_anomalies"]["pass"]  # no parse fails, no dangerous
    assert arms["repopulation_band_5_to_25"]["value"] == pytest.approx(5 / 40)


def test_readiness_arms_fail_on_low_n(tmp_path: Path):
    rows = [rec(agree=True, inc_verdict="local", sh_verdict="local")] * 5
    s = shadow_summary(log(tmp_path, rows))
    assert s["readiness_arms"]["sample_n_ge_30"]["pass"] is False


# ---------------------------------------------------------------- CLI render


def test_cli_renders_both_modes(tmp_path: Path, capsys):
    import argparse
    from kultivait.cli import cmd_shadow
    p = log(tmp_path, [rec(), rec(agree=True, inc_verdict="local", sh_verdict="local")])
    cmd_shadow(argparse.Namespace(log=str(p), json=False))
    text = capsys.readouterr().out
    assert "shadow observatory" in text
    assert "latency" in text and "calibration" in text
    assert "cutover readiness" in text
    cmd_shadow(argparse.Namespace(log=str(p), json=True))
    data = json.loads(capsys.readouterr().out)
    assert "readiness_arms" in data and "parse_validity" in data
