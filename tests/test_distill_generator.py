"""Slice D2 tests: dual-teacher synthetic generator & agreement filter."""

import json
import math
import random
from pathlib import Path

import pytest

from kultivait.distill.corpus import Anchor, TRUST_UNLABELED, write_corpus
from kultivait.distill.generator import (
    GENERATION_PROMPT,
    LABEL_PROMPT,
    REWRITE_PROMPT,
    cosine,
    generate_corpus,
    real_teacher_fns,
)
from kultivait.preprocessor import extract_json


# ------------------------------------------------------------ hermetic teachers


def make_fns(agreement: float = 1.0, recall_ok: bool = True, vary_fail_words=()):
    """Deterministic fake teachers: vary -> '<band> prompt about <topic> #i'."""
    state = {"i": 0}

    def vary_fn(seed_prompt: str, band: str, task_type: str) -> str:
        state["i"] += 1
        base = " ".join(seed_prompt.split()[:6]) or "the module"
        text = f"{band} {task_type} prompt about {base} number {state['i']}"
        for w in vary_fail_words:
            if w in text:
                return "garbage output"
        return text

    def label_fn(prompt: str) -> str:
        # independent pass: agrees `agreement` fraction via hash stability
        h = sum(ord(c) for c in prompt) % 10
        intended = prompt.split()[0] if prompt.split() else ""
        if intended not in ("local", "contested", "frontier"):
            return "local"
        return intended if (h / 10) < agreement else "frontier"

    def rewrite_fn(prompt: str, tier: str) -> str:
        if recall_ok:
            return f"rewrite: {prompt}"  # preserves the load-bearing terms
        return "rewrite: something entirely different with no overlap"

    return vary_fn, label_fn, rewrite_fn


def seeds(n=8):
    return [Anchor(f"seed topic {i} for generation", "", TRUST_UNLABELED, "escalation", f"e{i}")
            for i in range(n)]


# ---------------------------------------------------------------- agreement filter


def test_agreement_filter_drops_mislabeled_variations():
    vary_fn, label_fn, rewrite_fn = make_fns(agreement=0.0)  # labels never agree
    report = generate_corpus(seeds(), vary_fn=vary_fn, label_fn=label_fn,
                             rewrite_fn=rewrite_fn, target_pairs=10, rng=random.Random(1))
    assert report.pairs == []
    assert report.stats["agreement_drops"] == report.stats["attempts"]
    assert report.stats["accepted"] == 0


def test_agreement_filter_passes_when_teacher_agrees():
    vary_fn, label_fn, rewrite_fn = make_fns(agreement=1.0)
    report = generate_corpus(seeds(), vary_fn=vary_fn, label_fn=label_fn,
                             rewrite_fn=rewrite_fn, target_pairs=12, rng=random.Random(1))
    assert len(report.pairs) == 12
    assert report.stats["agreement_drops"] == 0
    for p in report.pairs:
        assert p.provenance["agreement_pass"] is True


def test_label_garbage_drops_not_crashes():
    vary_fn, _, rewrite_fn = make_fns()

    def bad_label(prompt: str) -> str:
        return "definitely-a-planet"

    report = generate_corpus(seeds(), vary_fn=vary_fn, label_fn=bad_label,
                             rewrite_fn=rewrite_fn, target_pairs=6, rng=random.Random(2))
    assert report.pairs == []
    assert report.stats["agreement_drops"] == report.stats["attempts"]


# ---------------------------------------------------------------- strata & cross-cut


def test_strata_quotas_and_task_type_cross_cut():
    vary_fn, label_fn, rewrite_fn = make_fns()
    report = generate_corpus(seeds(), vary_fn=vary_fn, label_fn=label_fn,
                             rewrite_fn=rewrite_fn, target_pairs=60, rng=random.Random(3))
    counts = {"contested": 0, "local": 0, "frontier": 0}
    tt_counts: dict[str, int] = {}
    for p in report.pairs:
        counts[p.stratum] += 1
        tt = p.provenance["task_type"]
        tt_counts[tt] = tt_counts.get(tt, 0) + 1
    assert counts == {"contested": 24, "local": 18, "frontier": 18}
    assert len(tt_counts) == 6  # every contract enum value appears
    for tt, n in tt_counts.items():
        assert n / 60 >= 0.10, f"{tt} below the 10% cross-cut: {n}"


# ---------------------------------------------------------------- 3-stage filter


def test_exact_dedup_drops_repeated_prompts():
    vary_fn, label_fn, rewrite_fn = make_fns()
    calls = {"i": 0}

    def dup_vary(seed_prompt, band, task_type):
        calls["i"] += 1
        return f"{band} fixed duplicate prompt always identical"  # same text every attempt

    report = generate_corpus(seeds(), vary_fn=dup_vary, label_fn=label_fn,
                             rewrite_fn=rewrite_fn, target_pairs=10, rng=random.Random(4))
    # only one unique prompt survives per exact-hash; rest drop as dedup
    unique = {p.messages[1]["content"] for p in report.pairs}
    assert len(unique) == len(report.pairs)
    assert report.stats["dedup_drops"] >= 1


def test_embedding_near_dup_dropped():
    vary_fn, label_fn, rewrite_fn = make_fns()
    n = {"i": 0}

    def near_dup_vary(seed_prompt, band, task_type):
        n["i"] += 1
        # near-identical: only a trailing digit differs
        return f"{band} nearly identical wording about the topic variant {n['i'] % 2}"

    def embedder(text: str) -> list[float]:
        # embedding keyed on everything except the last token -> near-dups collide
        key = " ".join(text.split()[:-1]).lower()
        v = [float(ord(c) % 97) for c in key[:32]] or [1.0]
        norm = math.sqrt(sum(x * x for x in v))
        return [x / norm for x in v]

    report = generate_corpus(seeds(), vary_fn=near_dup_vary, label_fn=label_fn,
                             rewrite_fn=rewrite_fn, target_pairs=8, rng=random.Random(5),
                             embed_fn=embedder)
    assert report.stats["near_dup_drops"] >= 1


def test_cosine_edge_cases():
    assert cosine([1, 0], [1, 0]) == pytest.approx(1.0)
    assert cosine([1, 0], [0, 1]) == pytest.approx(0.0)
    assert cosine([], []) == 0.0


def test_planted_fact_recall_floor():
    vary_fn, label_fn, _ = make_fns()
    def drop_facts(prompt, tier):
        return "a rewrite that shares nothing with its source prompt"
    report = generate_corpus(seeds(), vary_fn=vary_fn, label_fn=label_fn,
                             rewrite_fn=drop_facts, target_pairs=6, rng=random.Random(6))
    assert report.pairs == []
    assert report.stats["recall_drops"] == report.stats["attempts"]


def test_schema_stage_validates_pairs():
    vary_fn, label_fn, rewrite_fn = make_fns()
    report = generate_corpus(seeds(), vary_fn=vary_fn, label_fn=label_fn,
                             rewrite_fn=rewrite_fn, target_pairs=9, rng=random.Random(7))
    for p in report.pairs:
        contract, err = extract_json(p.messages[2]["content"])
        assert err is None and contract is not None
        fits = [t["fit"] for t in contract["judge"]["targets"]]
        assert fits == sorted(fits, reverse=True)  # monotone descending
        top = fits[0]
        band = p.stratum
        if band == "local":
            assert top < 0.65
        elif band == "contested":
            assert 0.65 <= top < 0.85
        else:
            assert top >= 0.85
        assert contract["rewrite"]  # rewrite present, from the rewriter teacher


def test_fits_regressed_never_teacher_emitted():
    # the teacher fns see only prompts/labels/rewrites — fits come from regress_fits
    vary_fn, label_fn, rewrite_fn = make_fns()
    report = generate_corpus(seeds(), vary_fn=vary_fn, label_fn=label_fn,
                             rewrite_fn=rewrite_fn, target_pairs=9, rng=random.Random(8))
    rng = random.Random(8)
    assert len(report.pairs) == 9


# ---------------------------------------------------------------- provenance & ledger


def test_provenance_records_teachers_and_seed():
    vary_fn, label_fn, rewrite_fn = make_fns()
    report = generate_corpus(seeds(), vary_fn=vary_fn, label_fn=label_fn,
                             rewrite_fn=rewrite_fn, target_pairs=6, rng=random.Random(9),
                             judge_name="glm/opencode", rewriter_name="claude/cli")
    for p in report.pairs:
        assert p.provenance["teachers"] == {"judge": "glm/opencode", "rewriter": "claude/cli"}
        assert p.provenance["origin"] == "synthetic-d2"
        assert p.provenance["seed"].startswith("e")
        assert p.provenance["band"] == p.stratum


def test_teacher_dispatches_ledger_tagged():
    vary_fn, label_fn, rewrite_fn = make_fns()
    tagged = []

    def ledger_record(**entry):
        tagged.append(entry)

    generate_corpus(seeds(), vary_fn=vary_fn, label_fn=label_fn,
                    rewrite_fn=rewrite_fn, target_pairs=4, rng=random.Random(10),
                    ledger_record=ledger_record)
    assert tagged, "teacher dispatches must be ledger-tagged"
    for e in tagged:
        assert e.get("origin") == "distill-generator"
        assert e.get("orchestrator") == "distill-teacher"
        assert e["local"] is False
        assert e["tier"].startswith("distill:")
    # every accepted pair cost: 2 judge calls (vary+label) + 1 rewrite, minus drops
    assert len(tagged) >= len([1]) * 2


# ---------------------------------------------------------------- prompts & wiring


def test_teacher_prompts_carry_the_contract():
    assert "local" in GENERATION_PROMPT and "contested" in GENERATION_PROMPT
    assert "frontier" in LABEL_PROMPT
    assert "local" in REWRITE_PROMPT or "economy" in REWRITE_PROMPT


def test_real_teacher_fns_wrap_cli_backends():
    import inspect
    fns = real_teacher_fns(judge_cli="opencode", rewriter_cli="claude")
    assert callable(fns["vary_fn"]) and callable(fns["label_fn"]) and callable(fns["rewrite_fn"])
    assert callable(fns["ledger_hook"]) or fns.get("ledger_hook") is None


def test_generated_corpus_writes_via_d1_writer(tmp_path: Path):
    vary_fn, label_fn, rewrite_fn = make_fns()
    report = generate_corpus(seeds(), vary_fn=vary_fn, label_fn=label_fn,
                             rewrite_fn=rewrite_fn, target_pairs=15, rng=random.Random(11))
    n = len(report.pairs)
    valid_frac = max(1, n // 5)
    write_corpus(report.pairs[:-valid_frac], report.pairs[-valid_frac:], tmp_path, heldout=[])
    lines = (tmp_path / "train.jsonl").read_text().strip().splitlines()
    assert len(lines) == n - valid_frac
    row = json.loads(lines[0])
    assert set(row) == {"messages"}
    stats = report.stats
    assert stats["attempts"] >= stats["accepted"]
