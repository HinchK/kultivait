"""Energy estimation (ADR 0020): coefficients, ledger fields, invariants."""

import json

from kultivait import energy
from kultivait.ledger import Ledger


# ---------- coefficient table + class resolution ----------


def test_embedded_table_version():
    assert energy.TABLE_VERSION == "energy-v1-20260909"
    assert set(energy.CLASSES) == {"1.5b", "3b", "4b", "8b", "14b"}


def test_class_resolution_known_models():
    assert energy.resolve_class("llama3.1:8b") == "8b"
    assert energy.resolve_class("qwen3:14b") == "14b"
    assert energy.resolve_class("kv-judge-llama32-3b-g3") == "3b"
    assert energy.resolve_class("qwen2.5-coder:1.5b") == "1.5b"
    assert energy.resolve_class("qwen3.5:4b") == "4b"


def test_class_resolution_unknown_falls_back_to_default():
    assert energy.resolve_class("mystery-model") == energy.DEFAULT_CLASS
    assert energy.resolve_class("mystery-model", overrides={"default_class": "3b"}) == "3b"


def test_class_resolution_tier_override_wins():
    assert energy.resolve_class("llama3.1:8b", class_overrides={"llama3.1:8b": "14b"}) == "14b"


def test_dispatch_estimate_math():
    est, tag = energy.dispatch_estimate(
        is_local=True, model="llama3.1:8b", tokens_in=1000, tokens_out=1000
    )
    assert tag == energy.TABLE_VERSION
    assert abs(est - (0.00060 + 0.19242)) < 1e-6


def test_coefficient_value_overrides():
    ov = {"coefficient_overrides": [{"class": "8b", "decode": 0.5}]}
    est, _ = energy.dispatch_estimate(
        is_local=True, model="llama3.1:8b", tokens_in=0, tokens_out=1000, overrides=ov
    )
    assert abs(est - 0.5) < 1e-6


# ---------- invariant 4: non-local dispatches carry 0.0 ----------


def test_non_local_estimate_is_zero_but_tagged():
    est, tag = energy.dispatch_estimate(
        is_local=False, model="claude", tokens_in=9999, tokens_out=9999
    )
    assert est == 0.0
    assert tag == energy.TABLE_VERSION  # the tag rides every record


# ---------- invariant 5: version tag override-aware ----------


def test_version_override():
    assert energy.active_version({"table_version_override": "self-measured-v2"}) == "self-measured-v2"
    assert energy.active_version({}) == energy.TABLE_VERSION


# ---------- invariant 2: two-significant-figure display ----------


def test_sig2():
    assert energy.sig2(0.03784) == "0.038"
    assert energy.sig2(0.19242) == "0.19"
    assert energy.sig2(13.37) == "13"
    assert energy.sig2(2.4499) == "2.4"
    assert energy.sig2(0.0) == "0"
    assert energy.sig2(0.0007431) == "0.00074"


# ---------- ledger fields + harvest aggregation ----------


def _ledger_with(tmp_path, rows):
    ledger = Ledger(tmp_path / "ledger.jsonl")
    for row in rows:
        base = dict(tier="t", local=True, tokens_in=100, tokens_out=50, cost_usd=0.0)
        base.update(row)
        ledger.record(**base)
    return ledger


def test_record_carries_energy_fields(tmp_path):
    ledger = _ledger_with(tmp_path, [{
        "est_wh": 0.0123, "energy_model": energy.TABLE_VERSION, "latency_s": 1.2349,
    }])
    entry = json.loads((tmp_path / "ledger.jsonl").read_text().splitlines()[0])
    assert entry["est_wh"] == 0.0123
    assert entry["energy_model"] == energy.TABLE_VERSION
    assert entry["latency_s"] == 1.235


def test_energy_section_sums_local_only(tmp_path):
    ledger = _ledger_with(tmp_path, [
        {"est_wh": 0.1, "energy_model": "energy-v1-20260909"},
        {"est_wh": 0.2, "energy_model": "energy-v1-20260909",
         "preprocess_model": "kv-judge-x"},
        {"local": False, "est_wh": 0.0, "energy_model": "energy-v1-20260909"},
        {"est_wh": 0.4, "energy_model": "energy-v0-legacy"},
    ])
    e = ledger.harvest()["energy"]
    assert e["dispatches"] == 3  # the non-local row never counts
    assert abs(e["est_wh"] - 0.7) < 1e-9
    assert e["version"] == "energy-v1-20260909"  # latest tag present
    assert e["by_generation"]["legacy/incumbent"]["dispatches"] == 2


# ---------- invariant 1: harvest block labeled est. + version ----------


def test_format_harvest_energy_block_labels(tmp_path, capsys):
    from kultivait.cli import format_harvest

    ledger = _ledger_with(tmp_path, [{
        "est_wh": 2.449, "energy_model": energy.TABLE_VERSION,
    }])
    out = format_harvest(ledger.harvest())
    block = [ln for ln in out.splitlines() if "energy" in ln.lower()]
    assert any("est" in ln and energy.TABLE_VERSION in ln for ln in block)
    assert "2.4 Wh" in out  # invariant 2 at the render layer


def test_format_harvest_omits_block_without_energy(tmp_path):
    from kultivait.cli import format_harvest

    ledger = _ledger_with(tmp_path, [{}])
    assert "energy (estimated" not in format_harvest(ledger.harvest())


# ---------- invariant 3: no live-growing energy counters ----------


def test_dashboard_template_has_no_energy_timers():
    src = ( __import__("pathlib").Path("src/kultivait/dashboard/index.html") ).read_text()
    assert "setInterval" not in src and "setTimeout" not in src
    # energy values render statically from summary/dispatch payloads only
    assert "energy-version" in src and "est." in src


def test_dispatch_sse_event_carries_energy_fields():
    import inspect
    from kultivait import server

    src = inspect.getsource(server)
    assert '"est_wh": est_wh' in src
    assert '"energy_model": energy_model' in src
