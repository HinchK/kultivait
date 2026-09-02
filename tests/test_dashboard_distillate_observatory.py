"""V4 (#109) tests: the distillate observatory — DOM, latency bars, readiness."""

from pathlib import Path

import pytest

DASH = Path("src/kultivait/dashboard/index.html")


@pytest.fixture
def page():
    return DASH.read_text()


# ---------------------------------------------------------------- DOM contract


def test_observatory_panel_dom_ids(page):
    for eid in ("distillate-panel", "distill-table",
                "gauge-latency-p50", "gauge-latency-p90",
                "lat-p50-inc", "lat-p50-sh", "lat-p90-inc", "lat-p90-sh",
                "lat-p50-inc-v", "lat-p50-sh-v", "lat-p90-inc-v", "lat-p90-sh-v",
                "gauge-calibration", "calibration-list",
                "readiness-panel", "readiness-verdict",
                "arm-stability-v", "arm-repopulation-v", "arm-health-v", "arm-n-v"):
        assert f'id="{eid}"' in page, f"missing #{eid}"


def test_read_only_no_interactive_triggers(page):
    """READ-ONLY: no buttons/links that could trigger a cutover."""
    low = page.lower()
    assert "<button" not in low  # no interactive elements in the observatory
    assert "kultivait cutover" in low  # the instruction points to the CLI


def test_paired_latency_bars(page):
    # 4 bars (p50/p90 × inc/sh) with transition animations
    for bid in ("lat-p50-inc", "lat-p50-sh", "lat-p90-inc", "lat-p90-sh"):
        assert f'id="{bid}"' in page
        assert "transition" in page


def test_calibration_flow_renders_verdict_pairs(page):
    assert "verdict_pairs" in page
    assert "renderCalibration" in page
    # the correction pair is highlighted green
    assert "frontier->shadow:contested" in page


# ---------------------------------------------------------------- readiness


def test_four_readiness_arms(page):
    for suffix in ("stability_non_contested_ge_90", "repopulation_band_5_to_25",
                   "health_zero_anomalies", "sample_n_ge_30"):
        assert suffix in page
    assert "readiness_arms" in page
    assert "renderReadiness" in page


def test_readiness_verdict_all_pass_message(page):
    assert "ALL ARMS PASS" in page
    assert "human flip" in page


def test_arm_color_coding(page):
    # pass = green, fail = red
    assert '"#3fb950"' in page and '"#f85149"' in page


# ---------------------------------------------------------------- wiring


def test_hydration_fires_observatory(page):
    assert "renderObservatory(s.shadow)" in page


def test_shadow_events_refresh_observatory(page):
    assert 'addEventListener("shadow"' in page
    # shadow SSE fetches the summary to re-render
    assert "renderObservatory" in page


def test_distill_table_renders_shadows_and_incumbent(page):
    assert "renderDistillates" in page
    assert "incumbent" in page and "SHADOW" in page and "retired" in page


# ---------------------------------------------------------------- zero-dep


def test_still_zero_dependency(page):
    low = page.lower()
    assert "cdn" not in low and "<script src=" not in low
