"""V3 (#108) tests: the cache economics visualizer — DOM, formulas, SSE."""

import re
from pathlib import Path

import pytest

DASH = Path("src/kultivait/dashboard/index.html")


@pytest.fixture
def page():
    return DASH.read_text()


# ---------------------------------------------------------------- DOM contract


def test_cache_panel_dom_ids(page):
    for eid in ("cache-panel", "gauge-cache-hit", "dial-cache-hit",
                "cache-hit-pct", "cache-read-tokens",
                "gauge-amortization", "amort-bar", "reads-per-write",
                "amort-status", "gauge-ttl-cohorts", "ttl-cohort-list",
                "cache-sparkline", "cache-spark-line", "cache-spark-fill"):
        assert f'id="{eid}"' in page, f"missing #{eid}"


def test_amortization_meter_has_break_even_marker(page):
    # the 1.4x break-even line at 14.28% (1.4/7 = 0.2 of the 7x-full bar... actually 1.4/7≈20%)
    # the marker div exists and is labeled
    assert "1.4" in page
    assert "break-even" in page
    # the bar exists with a transition (animates)
    assert 'id="amort-bar"' in page and "transition" in page


def test_sparkline_svg_structure(page):
    assert 'id="cache-sparkline"' in page
    assert 'id="cache-spark-line"' in page
    assert 'id="cache-spark-fill"' in page
    assert "polyline" in page and "preserveAspectRatio" in page


# ---------------------------------------------------------------- formulas


def test_amortization_formula(page):
    """reads-per-write renders as X.X×; the bar maps rpw/7 to width%; the
    1.4× break-even gates the status text."""
    assert "cache_reads_per_write" in page
    assert 'rpw.toFixed(1)+"×"' in page
    assert "(rpw/7)*100" in page  # bar width: 7x full-scale
    assert "rpw>=1.4" in page     # amortized check
    assert "below break-even" in page


def test_hit_rate_dial_uses_cache_hit_rate(page):
    assert 'dial-cache-hit' in page and "cache_hit_rate" in page
    assert 'setDial("dial-cache-hit"' in page


def test_ttl_cohort_rendering(page):
    assert "cache_ttl_cohorts" in page
    assert "renderTTL" in page
    assert "5m" in page and "1h" in page  # color-coded by TTL


def test_sparkline_pushes_on_cache_dispatch(page):
    assert "onDispatchCache" in page
    assert "pushSparkPoint" in page
    assert "SPARK_MAX" in page  # rolling window
    assert "cache_read_tokens" in page  # gated on cache-bearing


def test_sparkline_math(page):
    # per-point estimate = reads*0.9 - writes*0.25 (the #82 net formula simplified)
    assert "cache_read_tokens*0.9" in page
    assert "0.25" in page  # write premium at 5m


def test_hydrate_fires_render_cache(page):
    assert "renderCache(c)" in page  # wired into hydrate


# ---------------------------------------------------------------- zero-dep still holds


def test_still_zero_dependency(page):
    low = page.lower()
    assert "cdn" not in low and "<script src=" not in low
