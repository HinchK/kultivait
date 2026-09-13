"""ADR 0024 / #216: time ledger + length rule.

Covers the #215 pin: first_token_ms capture, the frontier-latency reference
table (bands, overrides-never-provenance, honest no-table degrade), the
harvest time-vs-savings section and its display invariants, and the length
rule (over-cap force-frontier, no escalation archive, menu anchor drop,
config override, local-only degradation).
"""

import json

import numpy as np
from fastapi.testclient import TestClient

from kultivait import time_reference
from kultivait.backends import Completion
from kultivait.escalations import EscalationStore
from kultivait.gates import Gate
from kultivait.ledger import Ledger
from kultivait.router import Router
from kultivait.server import create_app
from kultivait.tollbooth import build_route_menu


# ----------------------------------------------------------------------
# time_reference: bands, overrides, availability
# ----------------------------------------------------------------------


def test_band_edges_lower_inclusive_upper_exclusive():
    assert time_reference.band_for(0) == "0-2k"
    assert time_reference.band_for(2047) == "0-2k"
    assert time_reference.band_for(2048) == "2-8k"
    assert time_reference.band_for(8191) == "2-8k"
    assert time_reference.band_for(8192) == "8k+"
    assert time_reference.band_for(500_000) == "8k+"


def test_medians_reflect_committed_and_overridden_values(monkeypatch):
    monkeypatch.setattr(
        time_reference,
        "REFERENCE_MEDIANS",
        {
            "0-2k": {"first_token_ms": 800, "total_ms": 1800},
            "2-8k": {"first_token_ms": 1400, "total_ms": 4200},
        },
    )
    overrides = {
        "band_overrides": [
            {"band": "0-2k", "first_token_ms": 500},
        ]
    }
    table = time_reference.medians(overrides)
    assert table["0-2k"]["first_token_ms"] == 500  # overridden
    assert table["0-2k"]["total_ms"] == 1800  # committed value kept
    assert table["2-8k"]["first_token_ms"] == 1400
    # availability requires EVERY band measured
    assert time_reference.available(overrides) is False
    monkeypatch.setattr(
        time_reference,
        "REFERENCE_MEDIANS",
        {
            **time_reference.REFERENCE_MEDIANS,
            "8k+": {"first_token_ms": 2600, "total_ms": 9000},
        },
    )
    assert time_reference.available(overrides) is True


def test_version_override_is_explicit():
    assert (
        time_reference.active_version({"table_version_override": "time-v9-test"})
        == "time-v9-test"
    )
    assert time_reference.active_version(None) == time_reference.TABLE_VERSION


# ----------------------------------------------------------------------
# ledger: first_token_ms field + time section
# ----------------------------------------------------------------------


def test_first_token_ms_recorded_and_omitted(tmp_path):
    ledger = Ledger(tmp_path / "ledger.jsonl")
    ledger.record(
        tier="qwen3:14b", local=True, tokens_in=100, tokens_out=10,
        cost_usd=0.0, latency_s=2.5, first_token_ms=1200,
    )
    ledger.record(
        tier="qwen3:14b", local=True, tokens_in=100, tokens_out=10,
        cost_usd=0.0, latency_s=1.0,
    )
    rows = [json.loads(l) for l in (tmp_path / "ledger.jsonl").open()]
    assert rows[0]["first_token_ms"] == 1200
    assert "first_token_ms" not in rows[1]


def _seed_time_rows(ledger: Ledger):
    # two local rows in 0-2k (fast), one in 8k+ (slow), one cloud row
    ledger.record(tier="local", local=True, tokens_in=500, tokens_out=20,
                  cost_usd=0.0, latency_s=2.0, first_token_ms=800)
    ledger.record(tier="local", local=True, tokens_in=1000, tokens_out=20,
                  cost_usd=0.0, latency_s=4.0, first_token_ms=1600)
    ledger.record(tier="local", local=True, tokens_in=9000, tokens_out=20,
                  cost_usd=0.0, latency_s=60.0, first_token_ms=45000)
    ledger.record(tier="openrouter", local=False, tokens_in=10, tokens_out=5,
                  cost_usd=0.001, latency_s=3.0, first_token_ms=700)


def test_time_section_bands_reference_and_signed_time_paid(tmp_path, monkeypatch):
    monkeypatch.setattr(time_reference, "_load_overrides", lambda p: {})
    monkeypatch.setattr(
        time_reference,
        "REFERENCE_MEDIANS",
        {
            "0-2k": {"first_token_ms": 800, "total_ms": 3000},
            "2-8k": {"first_token_ms": 1400, "total_ms": 4200},
            "8k+": {"first_token_ms": 2600, "total_ms": 9000},
        },
    )
    ledger = Ledger(tmp_path / "ledger.jsonl")
    _seed_time_rows(ledger)
    section = ledger.harvest()["time"]
    assert section["has_reference"] is True
    assert section["reference_version"] == time_reference.TABLE_VERSION
    bands = section["bands"]
    assert bands["0-2k"]["dispatches"] == 2
    # median of [800, 1600] and [2000, 4000] totals
    assert bands["0-2k"]["local_first_token_ms_median"] == 1200
    assert bands["0-2k"]["local_total_ms_median"] == 3000
    assert bands["0-2k"]["ref_first_token_ms"] == 800
    assert bands["8k+"]["dispatches"] == 1
    # signed: (2000-3000) + (4000-3000) + (60000-9000) = +51000 ms
    assert section["time_paid_min"] == round(51000 / 60000, 2)
    # cloud rows never enter the time section
    assert bands["2-8k"]["dispatches"] == 0


def test_time_section_without_table_degrades_honestly(tmp_path, monkeypatch):
    monkeypatch.setattr(time_reference, "_load_overrides", lambda p: {})
    monkeypatch.setattr(time_reference, "REFERENCE_MEDIANS", {})
    ledger = Ledger(tmp_path / "ledger.jsonl")
    _seed_time_rows(ledger)
    section = ledger.harvest()["time"]
    assert section["has_reference"] is False
    assert section["time_paid_min"] is None
    assert section["reference_version"] == ""
    # local medians still reported — never fabricated reference values
    assert section["bands"]["0-2k"]["local_first_token_ms_median"] == 1200
    assert section["bands"]["0-2k"]["ref_first_token_ms"] is None


def test_format_harvest_names_reference_version_and_labels(tmp_path, monkeypatch):
    from kultivait.cli import format_harvest

    monkeypatch.setattr(time_reference, "_load_overrides", lambda p: {})
    monkeypatch.setattr(
        time_reference,
        "REFERENCE_MEDIANS",
        {
            "0-2k": {"first_token_ms": 800, "total_ms": 3000},
            "2-8k": {"first_token_ms": 1400, "total_ms": 4200},
            "8k+": {"first_token_ms": 2600, "total_ms": 9000},
        },
    )
    ledger = Ledger(tmp_path / "ledger.jsonl")
    _seed_time_rows(ledger)
    text = format_harvest(ledger.harvest())
    assert "time ledger" in text
    assert "ref " + time_reference.TABLE_VERSION in text
    assert "time paid vs ref" in text
    # invariant: no live counters, the version is named, ref labeled


def test_format_harvest_without_table_says_no_reference(tmp_path, monkeypatch):
    from kultivait.cli import format_harvest

    monkeypatch.setattr(time_reference, "_load_overrides", lambda p: {})
    monkeypatch.setattr(time_reference, "REFERENCE_MEDIANS", {})
    ledger = Ledger(tmp_path / "ledger.jsonl")
    _seed_time_rows(ledger)
    text = format_harvest(ledger.harvest())
    assert "no reference table" in text


# ----------------------------------------------------------------------
# route menu: length rule drops the local anchor
# ----------------------------------------------------------------------


def test_route_menu_drops_local_anchor_when_unavailable():
    options = build_route_menu(
        target_fits=[],
        installed_clis=["claude"],
        candidate_targets=["claude"],
        has_tools=False,
        local_available=False,
    )
    assert all(o.target != "local" for o in options)


# ----------------------------------------------------------------------
# server: length rule enforcement + first-token capture
# ----------------------------------------------------------------------


class _FakeLocal:
    supports_tools = True
    local = True

    def __init__(self):
        self.served = 0

    def complete(self, messages, tools=None, effort_flags=None, model_override=None, **kw):
        self.served += 1
        return Completion(text="local done", tokens_in=10, tokens_out=5,
                          cost_usd=0.0, local=True)

    def stream(self, messages, tools=None, effort_flags=None, model_override=None, **kw):
        comp = self.complete(messages, tools, effort_flags, model_override)
        yield "local "
        yield "done"
        yield comp


class _FakeFrontier:
    supports_tools = True
    local = False

    def __init__(self):
        self.served = 0

    def complete(self, messages, tools=None, effort_flags=None, model_override=None, **kw):
        self.served += 1
        return Completion(text="frontier done", tokens_in=10, tokens_out=5,
                          cost_usd=0.001, local=False)

    def stream(self, messages, tools=None, effort_flags=None, model_override=None, **kw):
        comp = self.complete(messages, tools, effort_flags, model_override)
        yield "frontier "
        yield "done"
        yield comp


def _app(tmp_path, backends, embed_vec=(1.0, 0.0), length_cap=8192):
    local_name = next(n for n, b in backends.items() if b.local)
    return create_app(
        router=Router(
            centroids={local_name: np.array([1.0, 0.0]), "frontier": np.array([0.0, 1.0])},
            capability_order=[local_name, "frontier"],
        ),
        embed=lambda text: np.array(embed_vec),
        backends=backends,
        ledger=Ledger(tmp_path / "ledger.jsonl"),
        gate=Gate(generate=lambda p: "distilled", compost_dir=tmp_path / "compost"),
        escalations=EscalationStore(tmp_path / "escalations"),
        toll_enabled=False,
        length_rule_max_tokens=length_cap,
    )


def _last_row(tmp_path):
    lines = (tmp_path / "ledger.jsonl").read_text().strip().splitlines()
    return json.loads(lines[-1])


BIG_TEXT = "x" * 40_000  # 10k est. tokens via chars//4 — over the 8192 cap


def test_over_cap_dispatch_forces_frontier_regardless_of_local_verdict(tmp_path):
    local, frontier = _FakeLocal(), _FakeFrontier()
    backends = {"qwen3:14b": local, "frontier": frontier}
    client = TestClient(_app(tmp_path, backends))
    resp = client.post(
        "/v1/chat/completions",
        json={"model": "auto", "messages": [{"role": "user", "content": BIG_TEXT}]},
    )
    assert resp.status_code == 200
    assert resp.json()["model"] == "frontier"  # served tier, not the local verdict
    assert frontier.served == 1 and local.served == 0
    row = _last_row(tmp_path)
    assert row["fallback_reason"] == "length_rule"
    assert row["first_token_ms"] >= 0  # non-stream: first == total, present


def test_over_cap_archives_no_escalation(tmp_path):
    local, frontier = _FakeLocal(), _FakeFrontier()
    client = TestClient(_app(tmp_path, {"qwen3:14b": local, "frontier": frontier}))
    client.post(
        "/v1/chat/completions",
        json={"model": "auto", "messages": [{"role": "user", "content": BIG_TEXT}]},
    )
    esc_dir = tmp_path / "escalations"
    saved = list(esc_dir.glob("*.json")) if esc_dir.exists() else []
    assert saved == []  # the pin: length-forced dispatches archive nothing


def test_under_cap_local_verdict_unchanged(tmp_path):
    local, frontier = _FakeLocal(), _FakeFrontier()
    client = TestClient(_app(tmp_path, {"qwen3:14b": local, "frontier": frontier}))
    resp = client.post(
        "/v1/chat/completions",
        json={"model": "auto", "messages": [{"role": "user", "content": "hello"}]},
    )
    assert resp.status_code == 200
    assert resp.json()["model"] == "qwen3:14b"
    assert local.served == 1 and frontier.served == 0
    row = _last_row(tmp_path)
    assert row["fallback_reason"] is None


def test_tool_schemas_count_toward_the_cap(tmp_path):
    local, frontier = _FakeLocal(), _FakeFrontier()
    client = TestClient(_app(tmp_path, {"qwen3:14b": local, "frontier": frontier}))
    huge_tool = {
        "type": "function",
        "function": {
            "name": "big",
            "description": BIG_TEXT,
            "parameters": {"type": "object"},
        },
    }
    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "auto",
            "messages": [{"role": "user", "content": "run the tool"}],
            "tools": [huge_tool],
        },
    )
    assert resp.status_code == 200
    assert resp.json()["model"] == "frontier"  # tools inflated the payload over cap
    assert _last_row(tmp_path)["fallback_reason"] == "length_rule"


def test_length_cap_is_config_overridable(tmp_path):
    local, frontier = _FakeLocal(), _FakeFrontier()
    client = TestClient(_app(tmp_path, {"qwen3:14b": local, "frontier": frontier}, length_cap=8))
    resp = client.post(
        "/v1/chat/completions",
        json={"model": "auto", "messages": [{"role": "user", "content": "a sentence well past eight tokens"}]},
    )
    assert resp.json()["model"] == "frontier"
    assert _last_row(tmp_path)["fallback_reason"] == "length_rule"


def test_over_cap_local_only_degrades_with_distinct_reason(tmp_path):
    local = _FakeLocal()
    client = TestClient(_app(tmp_path, {"qwen3:14b": local}))
    resp = client.post(
        "/v1/chat/completions",
        json={"model": "auto", "messages": [{"role": "user", "content": BIG_TEXT}]},
    )
    assert resp.status_code == 200
    assert resp.json()["model"] == "qwen3:14b"  # nothing else to serve on
    row = _last_row(tmp_path)
    assert row["fallback_reason"] == "length_rule_no_frontier"
    assert local.served == 1


def test_streaming_path_records_first_token_ms(tmp_path):
    local, frontier = _FakeLocal(), _FakeFrontier()
    client = TestClient(_app(tmp_path, {"qwen3:14b": local, "frontier": frontier}))
    with client.stream(
        "POST", "/v1/chat/completions",
        json={"model": "auto", "messages": [{"role": "user", "content": "hello"}], "stream": True},
    ) as resp:
        assert resp.status_code == 200
        list(resp.iter_lines())
    row = _last_row(tmp_path)
    assert isinstance(row["first_token_ms"], int)
    assert row["first_token_ms"] <= row["latency_s"] * 1000 + 1  # first <= total
