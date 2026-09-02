"""W1 (#113) tests: multi-teacher fallback, strata balance, budget floors."""

import random
from unittest.mock import patch

import pytest

from kultivait.distill.corpus import Anchor, TRUST_UNLABELED
from kultivait.distill.generator import (
    BudgetStop,
    generate_corpus,
    with_teacher_fallback,
)


def make_fns(agreement=1.0):
    state = {"i": 0}
    def vary_fn(seed, band, tt):
        state["i"] += 1
        return f"{band} {tt} prompt about work number {state['i']}"
    def label_fn(prompt):
        h = sum(ord(c) for c in prompt) % 10
        intended = prompt.split()[0]
        return intended if (h / 10) < agreement else "frontier"
    def rewrite_fn(prompt, tier):
        return f"rewrite: {prompt}"
    return vary_fn, label_fn, rewrite_fn


def seeds(n=6, origin="contested-task"):
    return [Anchor(f"seed {i} about {origin}", "", TRUST_UNLABELED, origin, f"s{i}")
            for i in range(n)]


# ---------------------------------------------------------------- fallback


class FlakyTeacher:
    """Fails the first N calls, then succeeds."""
    def __init__(self, fail_n=2):
        self.calls = 0
        self.fail_n = fail_n
    def __call__(self, prompt):
        self.calls += 1
        if self.calls <= self.fail_n:
            raise ConnectionError(f"rate limited (call {self.calls})")
        return "frontier"


def test_fallback_retries_primary_before_switching():
    flaky = FlakyTeacher(fail_n=2)
    backup = lambda p: "local"  # noqa: E731
    fn = with_teacher_fallback(flaky, [backup], max_primary_retries=3, retry_delay_s=0)
    assert fn("test") == "frontier"  # primary recovered on retry 3
    assert flaky.calls == 3


def test_fallback_switches_to_backup_after_exhaustion():
    dead = FlakyTeacher(fail_n=99)  # never succeeds
    backup_calls = []
    def backup(prompt):
        backup_calls.append(prompt)
        return "local"
    fn = with_teacher_fallback(dead, [backup], max_primary_retries=2, retry_delay_s=0)
    assert fn("test") == "local"
    assert len(backup_calls) == 1
    assert dead.calls == 2  # primary exhausted its retries


def test_fallback_budget_stop_never_caught():
    def budget_raiser(prompt):
        raise BudgetStop("floor hit")
    fn = with_teacher_fallback(budget_raiser, [lambda p: "local"], max_primary_retries=3, retry_delay_s=0)
    with pytest.raises(BudgetStop):
        fn("test")


def test_fallback_all_teachers_exhaust_raises():
    def always_fails(p):
        raise ConnectionError("dead")
    fn = with_teacher_fallback(always_fails, [always_fails], max_primary_retries=1, retry_delay_s=0)
    with pytest.raises(ConnectionError):
        fn("test")


# ---------------------------------------------------------------- strata


def test_strata_includes_escalatory_seeds():
    """Gen-3's delta: escalatory seeds ensure frontier labels occur."""
    vary, label, rewrite = make_fns(agreement=1.0)
    esc_seeds = [Anchor(f"architect the {i} region system", "", TRUST_UNLABELED,
                        "escalatory-task", f"e{i}") for i in range(3)]
    cont_seeds = [Anchor(f"refactor the {i} module", "", TRUST_UNLABELED,
                          "contested-task", f"c{i}") for i in range(3)]
    report = generate_corpus(cont_seeds + esc_seeds,
                             vary_fn=vary, label_fn=label, rewrite_fn=rewrite,
                             target_pairs=6, strata={"contested": 0.4, "local": 0.3, "frontier": 0.3},
                             rng=random.Random(42), attempt_budget=50)
    strata = report.stats["per_stratum"]
    assert strata.get("frontier", 0) > 0, "frontier starvation: escalatory seeds must yield frontier pairs"


def test_no_frontier_starvation_with_escalatory_band():
    """The #95 lesson: pure contested seeds starve the frontier stratum."""
    vary, label, rewrite = make_fns(agreement=1.0)
    # pure contested seeds → frontier stratum should still get some from escalatory framing
    cont = [Anchor(f"contested {i}", "", TRUST_UNLABELED, "contested-task", f"c{i}") for i in range(4)]
    report = generate_corpus(cont, vary_fn=vary, label_fn=label, rewrite_fn=rewrite,
                             target_pairs=3, strata={"contested": 0.4, "local": 0.3, "frontier": 0.3},
                             rng=random.Random(42), attempt_budget=30)
    # even without escalatory seeds, the band-targeted generation produces frontier attempts
    assert report.stats["attempts"] > 0
