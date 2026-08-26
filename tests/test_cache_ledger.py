"""C3 (#84) tests: cache ledger schema, harvest aggregation, CLI rendering."""

import json
from pathlib import Path

import pytest

from kultivait.ledger import Ledger


def rec(ledger, **kw):
    base = dict(tier="openrouter:claude-sonnet-5", local=False, tokens_in=1000,
                tokens_out=50, cost_usd=0.01)
    base.update(kw)
    ledger.record(**base)


# ---------------------------------------------------------------- schema


def test_cache_fields_serialize_on_entry(tmp_path: Path):
    led = Ledger(tmp_path / "l.jsonl")
    rec(led, cache_read_tokens=800, cache_write_tokens=100, cache_ttl="5m",
        cache_price_in=2.0)
    row = json.loads((tmp_path / "l.jsonl").read_text().splitlines()[-1])
    assert row["cache_read_tokens"] == 800
    assert row["cache_write_tokens"] == 100
    assert row["cache_ttl"] == "5m"
    assert row["cache_price_in"] == 2.0


def test_uncached_entries_carry_no_cache_fields(tmp_path: Path):
    led = Ledger(tmp_path / "l.jsonl")
    rec(led)
    row = json.loads((tmp_path / "l.jsonl").read_text().splitlines()[-1])
    assert "cache_read_tokens" not in row and "cache_ttl" not in row


def test_legacy_entries_parse_cleanly(tmp_path: Path):
    # pre-cache ledger lines (the entire existing harvest) must aggregate fine
    legacy = {"ts": 1.0, "tier": "qwen3.5:4b", "local": True, "tokens_in": 10,
              "tokens_out": 5, "cost_usd": 0.0, "notional_usd": 0.0,
              "preprocess_mark": "ok"}
    p = tmp_path / "l.jsonl"
    p.write_text(json.dumps(legacy) + "\n")
    h = Ledger(p).harvest()
    assert h["cache"]["dispatches"] == 0
    assert h["cache"]["kept_via_cache_usd"] == 0.0


# ---------------------------------------------------------------- aggregation


def test_kept_via_cache_nets_read_savings_and_write_premium(tmp_path: Path):
    led = Ledger(tmp_path / "l.jsonl")
    # 5m cohort: reads 800 @ $2 => save 800*0.9*2 = $1.44/million-scale; writes 100 => premium 100*0.25*2
    rec(led, cache_read_tokens=800, cache_write_tokens=100, cache_ttl="5m",
        cache_price_in=2.0)
    h = led.harvest()
    expected = (800 * 0.9 * 2.0 - 100 * 0.25 * 2.0) / 1e6
    assert h["cache"]["dispatches"] == 1
    assert pytest.approx(h["cache"]["kept_via_cache_usd"], rel=1e-4) == expected


def test_hit_rate_reads_over_total_input(tmp_path: Path):
    led = Ledger(tmp_path / "l.jsonl")
    rec(led, tokens_in=1000, cache_read_tokens=800, cache_write_tokens=100,
        cache_ttl="5m", cache_price_in=2.0)
    h = led.harvest()
    assert pytest.approx(h["cache"]["cache_hit_rate"], rel=1e-3) == 800 / 1000


def test_reads_per_write_ratio(tmp_path: Path):
    led = Ledger(tmp_path / "l.jsonl")
    rec(led, cache_read_tokens=800, cache_write_tokens=100, cache_ttl="5m",
        cache_price_in=2.0)
    rec(led, tokens_in=2000, cache_read_tokens=1200, cache_write_tokens=100,
        cache_ttl="5m", cache_price_in=2.0)
    h = led.harvest()
    assert h["cache"]["cache_reads_per_write"] == pytest.approx(2000 / 200)


def test_ttl_cohorts_split(tmp_path: Path):
    led = Ledger(tmp_path / "l.jsonl")
    rec(led, cache_read_tokens=800, cache_write_tokens=0, cache_ttl="5m",
        cache_price_in=2.0)
    rec(led, tokens_in=1000, cache_read_tokens=500, cache_write_tokens=200,
        cache_ttl="1h", cache_price_in=2.0)
    h = led.harvest()
    cohorts = h["cache"]["cache_ttl_cohorts"]
    assert cohorts["5m"]["dispatches"] == 1 and cohorts["1h"]["dispatches"] == 1
    assert pytest.approx(cohorts["1h"]["kept_via_cache_usd"], rel=1e-4) == (
        500 * 0.9 * 2.0 - 200 * 1.0 * 2.0) / 1e6  # 1h premium = 1.0x base


def test_cache_section_isolated_from_lenses(tmp_path: Path):
    led = Ledger(tmp_path / "l.jsonl")
    rec(led, cache_read_tokens=800, cache_write_tokens=100, cache_ttl="5m",
        cache_price_in=2.0)
    h = led.harvest()
    # kept-via-cache is a THIRD line: kept-in-pocket (routing) and metered untouched
    assert "kept_via_cache_usd" in h["cache"]
    assert h["saved_usd"] == pytest.approx(h["baseline_usd"] - h["spent_usd"])


# ---------------------------------------------------------------- CLI rendering


def test_format_harvest_renders_cache_section(tmp_path: Path):
    from kultivait.cli import format_harvest

    led = Ledger(tmp_path / "l.jsonl")
    rec(led, cache_read_tokens=800, cache_write_tokens=100, cache_ttl="5m",
        cache_price_in=2.0)
    text = format_harvest(led.harvest())
    assert "cache" in text.lower()
    assert "kept via cache" in text.lower()
    assert "hit rate" in text.lower()
    assert "5m" in text
    # JSON output carries the structured section
    h = led.harvest()
    assert set(h["cache"]) >= {"dispatches", "kept_via_cache_usd", "cache_hit_rate",
                               "cache_reads_per_write", "cache_ttl_cohorts"}


def test_format_harvest_without_cache_data_has_no_section(tmp_path: Path):
    from kultivait.cli import format_harvest

    led = Ledger(tmp_path / "l.jsonl")
    rec(led)
    text = format_harvest(led.harvest())
    assert "kept via cache" not in text.lower()
