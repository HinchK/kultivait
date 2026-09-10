"""Distill-eval harness substrate (map #187 / #188): corpus + survival scoring."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments" / "distill_eval"))

from facts import FACTS  # noqa: E402
from kultivait.evals import score_brief, score_survival  # noqa: E402

CORPUS = Path(__file__).resolve().parents[1] / "experiments" / "distill_eval" / "corpus"


def test_corpus_grown_to_eight_with_files():
    docs = sorted(FACTS)
    assert len(docs) == 8
    assert {"multiturn-chat", "toolloop", "phasehandoff",
            "postmortem", "specnegotiation"} <= set(docs)
    for doc in docs:
        assert (CORPUS / f"{doc}.txt").is_file(), doc
        assert len(FACTS[doc]) >= 8, doc


def test_corpus_transcripts_are_sized_like_the_originals():
    for doc in sorted(FACTS):
        text = (CORPUS / f"{doc}.txt").read_text()
        tokens = len(text) // 4
        assert 300 <= tokens <= 1200, f"{doc}: {tokens} tokens"


def test_every_fact_has_paraphrase_groups():
    for doc, facts in FACTS.items():
        for fact in facts:
            assert fact["groups"], (doc, fact["name"])
            assert all(isinstance(g, list) and g for g in fact["groups"]), (doc, fact["name"])


def test_score_survival_across_generations():
    facts = [
        {"name": "a", "groups": [["alpha"]]},
        {"name": "b", "groups": [["beta"]]},
    ]
    gen1 = "alpha and beta both present"
    gen2 = "alpha survived"  # beta lost at generation 2
    results = score_survival([gen1, gen2], facts)
    assert results[0].recall == 1.0
    assert results[1].recall == 0.5
    assert results[1].missing == ["b"]


def test_score_brief_still_backward_compatible():
    r = score_brief("contains REDIS and rl: prefix", [
        {"name": "rl", "groups": [["rl:"]]},
    ])
    assert r.recall == 1.0


def test_harness_module_parses_and_imports():
    import run  # noqa: F401  (experiments/distill_eval/run.py)

    assert "--gen-loss" in (Path(run.__file__).read_text())
