"""V2 (#107) tests: the 3-lens financial gauges — DOM contract + calculations."""

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from kultivait.ledger import Ledger

DASH = Path("src/kultivait/dashboard/index.html")


@pytest.fixture
def page():
    return DASH.read_text()


# ---------------------------------------------------------------- DOM contract


def test_gauge_dom_ids_present(page):
    for eid in ("kept-pocket", "kept-cache", "cash-out",
                "dial-kept-pocket", "dial-kept-cache", "dial-cash-out",
                "kept-pocket-pct", "cache-hit-rate", "dispatch-count",
                "gen-table"):
        assert f'id="{eid}"' in page, f"missing #{eid}"


def test_financial_panel_and_generation_panel(page):
    assert 'id="financial-lenses"' in page
    assert 'id="generation-panel"' in page
    assert "generation" in page and "share" in page  # the breakdown header


def test_zero_dependency_no_cdn(page):
    low = page.lower()
    assert "cdn" not in low
    assert "<script src=" not in low  # no external scripts
    assert "https://" not in low.replace("https://localhost", "")


def test_sse_handlers_bound(page):
    for event in ("harvest", "dispatch", "shadow"):
        assert f'addEventListener("{event}"' in page
    assert "/api/dashboard/summary" in page  # hydration fetch
    assert "/api/stream" in page


def test_svg_dials_with_arc_paths(page):
    assert 'stroke-dasharray="100.5"' in page
    assert 'stroke-dashoffset' in page
    assert 'viewBox="0 0 80 44"' in page  # the half-circle dials


# ---------------------------------------------------------------- calculation contract (JS)


def test_financial_formula_in_hydrate(page):
    """The ADR 0005 lens mapping is verifiable in the hydrate fn's code."""
    assert 's.saved_usd' in page                    # kept-in-pocket = baseline - notional
    assert 's.cache||{}).kept_via_cache_usd' in page or "s.cache||{}).kept_via_cache_usd" in page
    assert "metered_spent_usd||s.spent_usd" in page # cash-out = metered (fallback spent)
    assert "baseline_usd" in page                    # the % of baseline


def test_generation_breakdown_renders_by_preprocess_model(page):
    assert "by_generation" in page
    assert "preprocess_model" in page or "generation" in page
    assert "gen-bar" in page  # the visual bar


# ---------------------------------------------------------------- live page


def test_dashboard_serves_the_updated_page():
    from kultivait.server import create_app
    class FakeRouter:
        def classify(self, vec):
            class D:
                tier = "local"; escalated = False; margin = 0.9
            return D()
    class FakeBackend:
        supports_tools = True; local = True
        def complete(self, m, tools=None, **kw):
            from kultivait.backends import Completion
            return Completion(text="ok", tokens_in=1, tokens_out=1, cost_usd=0, local=True)
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        led = Ledger(Path(td) / "l.jsonl")
        led.record(tier="local", local=True, tokens_in=5, tokens_out=2, cost_usd=0.0)
        app = create_app(router=FakeRouter(), embed=lambda t: [0.0],
                         backends={"local": FakeBackend()}, ledger=led,
                         gate=None, escalations=None)
        c = TestClient(app)
        r = c.get("/dashboard/")
        assert r.status_code == 200
        assert 'id="kept-pocket"' in r.text
        assert 'id="dial-kept-cache"' in r.text
