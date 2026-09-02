"""S3 (#103) tests: generation-aware harvest slicing on preprocess_model."""

import json
from pathlib import Path

import pytest

from kultivait.ledger import Ledger


def rec(ledger, **kw):
    base = dict(tier="local", local=True, tokens_in=100, tokens_out=10,
                cost_usd=0.0, notional_usd=0.05)
    base.update(kw)
    ledger.record(**base)


def test_by_generation_groups_on_preprocess_model(tmp_path: Path):
    led = Ledger(tmp_path / "l.jsonl")
    rec(led, preprocess_model="qwen3.5:4b")
    rec(led, preprocess_model="qwen3.5:4b")
    rec(led, preprocess_model="kv-judge-llama32-3b-g1")
    rec(led)  # legacy: no tag
    h = led.harvest()
    bg = h["by_generation"]
    assert bg["qwen3.5:4b"]["requests"] == 2
    assert bg["kv-judge-llama32-3b-g1"]["requests"] == 1
    assert bg["legacy/incumbent"]["requests"] == 1


def test_per_generation_saved_usd(tmp_path: Path):
    led = Ledger(tmp_path / "l.jsonl")
    rec(led, preprocess_model="inc", cost_usd=0.0, notional_usd=0.10)
    rec(led, preprocess_model="g1", cost_usd=0.02, notional_usd=0.06)
    h = led.harvest()
    assert h["by_generation"]["inc"]["saved_usd"] == pytest.approx(0.10)
    assert h["by_generation"]["g1"]["saved_usd"] == pytest.approx(0.04)


def test_per_generation_cache_metrics(tmp_path: Path):
    led = Ledger(tmp_path / "l.jsonl")
    rec(led, preprocess_model="g1", cache_read_tokens=800, cache_write_tokens=100,
        cache_ttl="5m", cache_price_in=2.0, tokens_in=1000)
    h = led.harvest()
    c = h["by_generation"]["g1"]["cache"]
    assert c["dispatches"] == 1
    assert c["cache_hit_rate"] == pytest.approx(0.8)
    assert c["kept_via_cache_usd"] == pytest.approx((800 * 0.9 * 2.0 - 100 * 0.25 * 2.0) / 1e6)


def test_generation_without_cache_has_zeroed_cache(tmp_path: Path):
    led = Ledger(tmp_path / "l.jsonl")
    rec(led, preprocess_model="g1")
    h = led.harvest()
    assert h["by_generation"]["g1"]["cache"]["dispatches"] == 0
    assert h["by_generation"]["g1"]["cache"]["cache_hit_rate"] == 0.0


def test_legacy_entries_never_crash_the_slice(tmp_path: Path):
    # the entire existing harvest (pre-tag entries) must aggregate cleanly
    legacy = {"ts": 1.0, "tier": "local", "local": True, "tokens_in": 5,
              "tokens_out": 2, "cost_usd": 0.0, "notional_usd": 0.0}
    p = tmp_path / "l.jsonl"
    p.write_text(json.dumps(legacy) + "\n")
    h = Ledger(p).harvest()
    assert h["by_generation"]["legacy/incumbent"]["requests"] == 1


def test_cli_renders_generation_block(tmp_path: Path, capsys):
    import argparse
    from kultivait.cli import format_harvest
    led = Ledger(tmp_path / "l.jsonl")
    rec(led, preprocess_model="qwen3.5:4b")
    rec(led, preprocess_model="kv-judge-g1", cache_read_tokens=500,
        cache_write_tokens=0, cache_ttl="5m", cache_price_in=2.0, tokens_in=800)
    text = format_harvest(led.harvest())
    assert "by generation" in text
    assert "qwen3.5:4b" in text and "kv-judge-g1" in text
    assert "cache hit" in text  # g1's cache line renders
    data = led.harvest()
    assert "by_generation" in data  # JSON carries the slice
