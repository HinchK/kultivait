"""H2 (#89) tests: band-tightened budgets + anti-looping efficiency penalties."""

import json
from pathlib import Path

import pytest

from kultivait.capability_eval import efficiency_penalty, load_corpus


# ---------------------------------------------------------------- corpus budgets


def test_budgets_derived_and_tightened():
    tasks = {t.id: t for t in load_corpus()}
    # escalatory: steps + recovery + 1 — tight but recoverable
    esc = tasks["esc_audit_chain_distract"]  # 3 tools + 2 sequenced + 1 = 6
    assert esc.max_turns == 6
    # contested tightened from the old 4s where recovery allows
    assert tasks["exemplar_contested_ambiguous_retry"].max_turns == 3
    assert tasks["contested_ambiguous_perf"].max_turns == 3
    # simple stays generous (>= steps + 2)
    for t in tasks.values():
        if t.rubric["band"] == "simple":
            assert t.max_turns >= len(t.rubric.get("expected_tools", [])) + 2


def test_escalatory_budgets_are_steps_plus_one():
    tasks = load_corpus()
    for t in tasks:
        if t.rubric["band"] != "escalatory":
            continue
        recov = sum(1 for v in t.mock_responses.values() if isinstance(v, list))
        steps = len(t.rubric.get("expected_tools", [])) + recov
        # all escalatory budgets sit at steps+1 (or a documented judgment override)
        note = t.rubric.get("budget_note", "")
        if "override" not in note:
            assert t.max_turns == steps + 1, f"{t.id}: {t.max_turns} != {steps}+1"


def test_budget_notes_record_derivation():
    tasks = load_corpus()
    assert all("budget_note" in t.rubric for t in tasks)


def test_bands_unchanged():
    from collections import Counter
    bands = Counter(t.rubric["band"] for t in load_corpus())
    assert bands == {"simple": 7, "contested": 7, "escalatory": 7}


# ---------------------------------------------------------------- efficiency


def _tc(name, args):
    return {"id": "c1", "type": "function",
            "function": {"name": name, "arguments": args}}


def test_clean_run_no_penalty():
    calls = [_tc("search", '{"q":"a"}'), _tc("read", '{"p":"f"}')]
    mult, notes = efficiency_penalty(calls)
    assert mult == 1.0 and notes == []


def test_distinct_calls_same_tool_no_penalty():
    calls = [_tc("search", '{"q":"a"}'), _tc("search", '{"q":"b"}')]
    mult, _ = efficiency_penalty(calls)
    assert mult == 1.0  # different args = refinement, not repetition


def test_repeated_identical_calls_penalized():
    calls = [_tc("search", '{"q":"a"}'), _tc("read", '{"p":"f"}'),
             _tc("search", '{"q":"a"}'), _tc("search", '{"q":"a"}')]
    mult, notes = efficiency_penalty(calls)
    assert mult < 1.0
    assert any("repeated" in n for n in notes)


def test_blind_back_to_back_repeats_penalized_double():
    refined = [_tc("search", '{"q":"a"}'), _tc("read", '{"p":"f"}'),
               _tc("search", '{"q":"a"}')]                       # 1 repeat, not blind
    blind = [_tc("search", '{"q":"a"}'), _tc("search", '{"q":"a"}')]  # blind repeat
    m_refined, _ = efficiency_penalty(refined)
    m_blind, _ = efficiency_penalty(blind)
    assert m_blind < m_refined


def test_penalty_floored_at_quarter():
    calls = [_tc(f"t{i}", '{"a":1}') for i in range(4)]
    calls += calls + calls  # mass repetition
    mult, _ = efficiency_penalty(calls)
    assert mult >= 0.25


def test_retry_after_failure_is_lightly_penalized_not_destroyed():
    # one legitimate retry of the same failing call (H1 sequences) — single repeat
    calls = [_tc("api", "{}"), _tc("other", '{"x":1}'), _tc("api", "{}")]
    mult, _ = efficiency_penalty(calls)
    assert mult == pytest.approx(0.85)  # -0.15, no blind doubling
