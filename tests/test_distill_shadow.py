"""Slice D6 tests: shadow pass, shadow.jsonl, cutover readiness, server wiring."""

import json
import time
from pathlib import Path

import pytest

from kultivait.distill.shadow import (
    CUTOVER_AGREEMENT,
    CUTOVER_MIN_N,
    ShadowRecord,
    append_shadow_log,
    compute_cutover_readiness,
    read_shadow_log,
    run_shadow_pass,
    schedule_shadow_pass,
    shadow_after_response,
)


def rec(agree=True, parse_ok=True, dangerous=False, incumbent="qwen3.5:4b",
        shadow="kv-judge-llama32-3b-g0"):
    return ShadowRecord(
        ts=time.time(), fingerprint="f1", prompt_hash="h1",
        incumbent={"model": incumbent, "verdict": "frontier", "max_fit": 0.9,
                   "latency_s": 1.0, "parse_ok": True},
        shadow={"model": shadow, "verdict": ("frontier" if agree else "local"),
                "max_fit": 0.9 if agree else 0.3, "latency_s": 1.0,
                "parse_ok": parse_ok, "dangerous": dangerous},
        agree=agree,
    )


# ---------------------------------------------------------------- log store


def test_append_and_read_round_trips(tmp_path: Path):
    p = tmp_path / "shadow.jsonl"
    append_shadow_log(rec(), p)
    append_shadow_log(rec(agree=False), p)
    rows = read_shadow_log(p)
    assert len(rows) == 2
    assert rows[0]["incumbent"]["model"] == "qwen3.5:4b"
    assert rows[1]["agree"] is False
    assert read_shadow_log(tmp_path / "missing.jsonl") == []


# ---------------------------------------------------------------- readiness


def test_readiness_requires_agreement_n_and_zero_anomalies():
    ok30 = [rec() for _ in range(30)]
    r = compute_cutover_readiness(ok30)
    assert r["n"] == 30 and r["agreement"] == 1.0
    assert r["cutover_ready"] is True
    assert r["criteria"] == {"agreement": CUTOVER_AGREEMENT, "min_n": CUTOVER_MIN_N,
                             "anomalies_allowed": 0}


def test_readiness_n_below_30_not_ready():
    r = compute_cutover_readiness([rec() for _ in range(29)])
    assert r["cutover_ready"] is False
    assert r["reasons"] == ["n < 30"]


def test_readiness_agreement_below_90_not_ready():
    # 26/30 agree = 0.867 < 0.90
    rows = [rec() for _ in range(26)] + [rec(agree=False) for _ in range(4)]
    r = compute_cutover_readiness(rows)
    assert r["agreement"] < CUTOVER_AGREEMENT
    assert r["cutover_ready"] is False


def test_readiness_anomaly_blocks_cutover():
    rows = [rec() for _ in range(30)]
    rows[3] = rec(dangerous=True)   # shadow served local on a frontier verdict
    rows[7] = rec(parse_ok=False)   # shadow failed to parse
    r = compute_cutover_readiness(rows)
    assert r["anomalies"] == 2
    assert r["cutover_ready"] is False


# ---------------------------------------------------------------- the pass itself


def contract(top: float) -> str:
    return json.dumps({"analysis": {"task_type": "x", "complexity": 1, "signals": [],
                                    "subtask_candidates": []},
                       "rewrite": "r",
                       "judge": {"local_sufficient": False, "confidence": 0.9,
                                 "targets": [{"target": "claude", "fit": top,
                                              "effort": "medium"}]}})


def test_run_shadow_pass_agree_and_disagree():
    g = lambda model, prompt: (contract(0.9), 0.5)  # noqa: E731
    r = run_shadow_pass("prompt", "fp", incumbent_model="qwen3.5:4b",
                        incumbent_verdict="frontier", incumbent_max_fit=0.9,
                        incumbent_latency_s=1.0, shadow_model="kv-judge-x-g0",
                        generate=g)
    assert r.agree is True
    assert r.shadow["verdict"] == "frontier" and r.shadow["parse_ok"] is True

    g_local = lambda model, prompt: (contract(0.3), 0.5)  # noqa: E731
    r2 = run_shadow_pass("prompt", "fp", incumbent_model="qwen3.5:4b",
                         incumbent_verdict="frontier", incumbent_max_fit=0.9,
                         incumbent_latency_s=1.0, shadow_model="kv-judge-x-g0",
                         generate=g_local)
    assert r2.agree is False
    assert r2.shadow["dangerous"] is True  # frontier verdict shadowed as local


def test_run_shadow_pass_parse_failure_recorded_not_raised():
    def broken(model, prompt):
        raise RuntimeError("shadow backend exploded")
    r = run_shadow_pass("prompt", "fp", incumbent_model="m", incumbent_verdict="local",
                        incumbent_max_fit=0.3, incumbent_latency_s=1.0,
                        shadow_model="kv-judge-x-g0", generate=broken)
    assert r.shadow["parse_ok"] is False and r.agree is False


# ---------------------------------------------------------------- isolation


def test_schedule_is_totally_exception_isolated(tmp_path):
    p = tmp_path / "shadow.jsonl"

    def explode(model, prompt):
        raise RuntimeError("boom")

    # never raises, returns immediately (fire-and-forget); the backend failure
    # becomes an anomaly ROW (telemetry the readiness counter needs), never an
    # exception in serving
    schedule_shadow_pass("prompt", "fp", incumbent_model="m", incumbent_verdict="local",
                         incumbent_max_fit=0.3, incumbent_latency_s=1.0,
                         shadow_model="s", generate=explode, log_path=p)
    time.sleep(0.3)
    rows = read_shadow_log(p)
    assert len(rows) == 1
    assert rows[0]["shadow"]["parse_ok"] is False  # the anomaly is data, not a crash


def test_after_response_helper_fires_only_when_enabled(tmp_path):
    p = tmp_path / "shadow.jsonl"
    calls = []

    def gen(model, prompt):
        calls.append(model)
        return contract(0.3), 0.4

    # off: nothing happens
    shadow_after_response(shadow_mode="off", shadow_model="kv-judge-x-g0",
                          prompt="p", fingerprint="fp", incumbent_model="qwen3.5:4b",
                          incumbent_verdict="local", incumbent_max_fit=0.3,
                          incumbent_latency_s=1.0, generate=gen, log_path=p)
    assert calls == []
    # on: fires (post-response, sampled at rate 1.0)
    shadow_after_response(shadow_mode="on", shadow_model="kv-judge-x-g0",
                          prompt="p", fingerprint="fp", incumbent_model="qwen3.5:4b",
                          incumbent_verdict="local", incumbent_max_fit=0.3,
                          incumbent_latency_s=1.0, generate=gen, log_path=p)
    time.sleep(0.3)
    assert calls == ["kv-judge-x-g0"]
    rows = read_shadow_log(p)
    assert len(rows) == 1 and rows[0]["shadow"]["model"] == "kv-judge-x-g0"
    # no shadow model configured: never fires
    shadow_after_response(shadow_mode="on", shadow_model="",
                          prompt="p", fingerprint="fp", incumbent_model="m",
                          incumbent_verdict="local", incumbent_max_fit=0.3,
                          incumbent_latency_s=1.0, generate=gen, log_path=p)
    time.sleep(0.2)
    assert len(read_shadow_log(p)) == 1


# ---------------------------------------------------------------- server wiring


def test_ledger_entries_gain_preprocess_model_tag():
    from kultivait.ledger import Ledger

    led = Ledger(Path("/tmp/_d6_ledger.jsonl"))
    # the exact extra-fields shape the server records in the contested branch
    extras = {"preprocess_mark": "ok", "verdict": "contested", "toll": "skipped",
              "preprocess_model": "qwen3.5:4b"}
    led.record(tier="local", local=True, tokens_in=10, tokens_out=5, cost_usd=0.0,
               fingerprint="f", **extras)
    rows = [json.loads(l) for l in open("/tmp/_d6_ledger.jsonl") if l.strip()]
    assert rows[-1]["preprocess_model"] == "qwen3.5:4b"
    Path("/tmp/_d6_ledger.jsonl").unlink()


def test_distill_seat_reads_config_and_resolves_per_call():
    from kultivait.config import Config, DistillConfig
    from kultivait.distill.shadow import DistillSeat

    cfg = Config(distill=DistillConfig(model="kv-judge-llama32-3b-g0",
                                       shadow_model="kv-judge-x-g1", shadow_mode="on"))
    seat = DistillSeat.from_config(cfg)
    assert seat.model == "kv-judge-llama32-3b-g0"
    assert seat.shadow_model == "kv-judge-x-g1"
    assert seat.shadow_on() is True
    # per-call swap: updating the seat changes the next call's model
    seat.set_model("kv-judge-qwen35-4b-g2")
    assert seat.model == "kv-judge-qwen35-4b-g2"


def test_server_carries_seat_into_contested_path():
    # the contested branch consults the seat for model + shadow dispatch
    import inspect
    from kultivait import server

    src = inspect.getsource(server)
    assert "DistillSeat" in src or "distill" in src
    assert "preprocess_model" in src          # ledger tagging wired
    assert "shadow_after_response" in src     # post-response hook wired
