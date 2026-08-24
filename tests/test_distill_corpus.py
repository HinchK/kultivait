"""Slice D1 tests: [distill] config seat + corpus builder foundations."""

import json
import random
from pathlib import Path

import pytest

from kultivait.config import Config, DistillConfig, TierSpec, load_config, save_config
from kultivait.distill.corpus import (
    Anchor,
    TRUST_BRONZE,
    TRUST_GOLD,
    TRUST_SILVER,
    TRUST_UNLABELED,
    assemble_pair,
    build_corpus,
    dry_run_report,
    extract_anchors,
    regress_fits,
    split_heldout,
    write_corpus,
)
from kultivait.preprocessor import PREPROCESSOR_PROMPT, extract_json


# ---------------------------------------------------------------- config seat


def test_distill_config_defaults():
    d = DistillConfig()
    assert d.model == "qwen3.5:4b"
    assert d.shadow_model == ""
    assert d.shadow_mode == "off"
    assert d.shadow_sample_rate == 1.0


def test_config_distill_default_present():
    cfg = Config()
    assert cfg.distill.model == "qwen3.5:4b"
    assert cfg.distill.shadow_mode == "off"


def test_distill_section_round_trips(tmp_path: Path):
    distill = DistillConfig(model="kv-judge-llama32-3b-g1", shadow_model="kv-judge-qwen35-4b-g2",
                            shadow_mode="on", shadow_sample_rate=0.5)
    cfg = Config(tiers=[TierSpec(name="m", role="simple", kind="ollama", model="m")], distill=distill)
    p = tmp_path / "config.toml"
    save_config(cfg, p)
    loaded = load_config(p)
    assert loaded.distill.model == "kv-judge-llama32-3b-g1"
    assert loaded.distill.shadow_model == "kv-judge-qwen35-4b-g2"
    assert loaded.distill.shadow_mode == "on"
    assert loaded.distill.shadow_sample_rate == 0.5
    assert loaded.tiers[0].name == "m"


def test_distill_section_defaults_when_absent(tmp_path: Path):
    p = tmp_path / "config.toml"
    save_config(Config(), p)
    body = p.read_text()
    loaded = load_config(p)
    assert loaded.distill.model == "qwen3.5:4b"
    assert loaded.distill.shadow_mode == "off"
    # explicit [distill] section serializes
    assert "[distill]" in body


# ---------------------------------------------------------------- anchors


def _ledger_entry(**over):
    e = {"ts": 1.0, "tier": "local", "local": True, "tokens_in": 10, "tokens_out": 5,
         "cost_usd": 0.0, "snippet": "explain the config parser briefly"}
    e.update(over)
    return e


def test_extract_anchors_gold_from_human_toll_picks():
    entries = [
        _ledger_entry(toll="answered", route_choice="human:local"),
        _ledger_entry(toll="answered", route_choice="human:frontier:claude"),
    ]
    anchors = extract_anchors(entries, [], [])
    assert len(anchors) == 2
    by_choice = {a.origin: a for a in anchors}
    assert by_choice["toll_pick"].trust == TRUST_GOLD
    tiers = {a.route_target: a.tier for a in anchors}
    assert tiers == {"human:local": "local", "human:frontier:claude": "frontier"}


def test_extract_anchors_silver_from_expired_and_auto():
    entries = [
        _ledger_entry(toll="expired", route_choice="auto:local"),
        _ledger_entry(toll="skipped", route_choice="auto:frontier:openrouter"),
    ]
    anchors = extract_anchors(entries, [], [])
    assert {a.trust for a in anchors} == {TRUST_SILVER}
    assert {a.origin for a in anchors} == {"counterfactual", "auto_policy"}


def test_extract_anchors_ignores_incumbent_verdicts_without_outcome():
    # incumbent-derived verdicts must never become labels (ADR 0013)
    entries = [_ledger_entry(preprocess_mark="ok", verdict="frontier", max_fit=0.9)]
    assert extract_anchors(entries, [], []) == []


def test_extract_anchors_unlabeled_from_escalations():
    esc = [{"id": "esc-1", "requested_tier": "frontier:architect",
            "messages": [{"role": "user", "content": "Design the migration system fully."}]}]
    anchors = extract_anchors([], esc, [])
    assert anchors[0].trust == TRUST_UNLABELED
    assert anchors[0].tier == ""
    assert anchors[0].origin == "escalation"
    assert "migration" in anchors[0].prompt


def test_extract_anchors_bronze_from_capability_eval():
    ev = [{"prompt": "fix the failing tool loop", "tier": "frontier", "case_id": "case-7"}]
    anchors = extract_anchors([], [], ev)
    assert anchors[0].trust == TRUST_BRONZE
    assert anchors[0].origin == "capability_eval"
    assert anchors[0].source_id == "case-7"


def test_anchors_skip_entries_without_snippet():
    entries = [_ledger_entry(toll="answered", route_choice="human:local")]
    entries[0].pop("snippet")
    assert extract_anchors(entries, [], []) == []


# ---------------------------------------------------------------- held-out split


def test_split_heldout_disjoint_and_verdict_bearing():
    anchors = [
        Anchor("a", "local", TRUST_GOLD, "toll_pick", "l1"),
        Anchor("b", "frontier", TRUST_SILVER, "auto_policy", "l2"),
        Anchor("c", "", TRUST_UNLABELED, "escalation", "e1"),
        Anchor("d", "", TRUST_UNLABELED, "escalation", "e2"),
        Anchor("e", "contested", TRUST_BRONZE, "capability_eval", "case-1"),
    ]
    seeds, heldout = split_heldout(anchors)
    seed_ids = {a.source_id for a in seeds}
    held_ids = {a.source_id for a in heldout}
    assert seed_ids == {"e1", "e2"}
    assert held_ids == {"l1", "l2", "case-1"}
    assert not seed_ids & held_ids
    # every held-out anchor is verdict-bearing (labeled)
    assert all(a.tier for a in heldout)


def test_split_heldout_proves_disjointness_with_duplicate_ids():
    anchors = [
        Anchor("a", "local", TRUST_GOLD, "toll_pick", "dup"),
        Anchor("b", "", TRUST_UNLABELED, "escalation", "dup"),
    ]
    with pytest.raises(ValueError, match="disjoint"):
        split_heldout(anchors)


# ---------------------------------------------------------------- fit regression


@pytest.mark.parametrize("tier,lo,hi", [
    ("local", 0.0, 0.65), ("contested", 0.65, 0.85), ("frontier", 0.85, 1.0),
])
def test_regress_fits_band_placement(tier, lo, hi):
    rng = random.Random(7)
    for _ in range(200):
        fits, top = regress_fits(tier, rng)
        assert lo <= top < hi
        others = [f["fit"] for f in fits[1:]]
        assert all(o <= top for o in others)
        assert {f["target"] for f in fits} == {"claude", "codex", "gemini", "agy"}


def test_regress_fits_pure_function_of_tier_and_rng():
    # never reads incumbent fits: same seed, same values, regardless of environment
    a = regress_fits("frontier", random.Random(42))
    b = regress_fits("frontier", random.Random(42))
    assert a == b


# ---------------------------------------------------------------- pairs & corpus


def test_assemble_pair_serving_shape():
    rng = random.Random(3)
    pair = assemble_pair("Refactor the parser for edge cases.", "contested", rng,
                         origin="synthetic-probe", rewrite="Refactor parser: edge cases.")
    roles = [m["role"] for m in pair.messages]
    assert roles == ["system", "user", "assistant"]
    assert pair.messages[0]["content"] == PREPROCESSOR_PROMPT
    assert pair.messages[1]["content"] == "Refactor the parser for edge cases."
    contract, err = extract_json(pair.messages[2]["content"])
    assert err is None and contract is not None
    assert set(contract) == {"analysis", "rewrite", "judge"}
    assert contract["rewrite"] == "Refactor parser: edge cases."
    fits = [t["fit"] for t in contract["judge"]["targets"]]
    assert 0.65 <= max(fits) < 0.85  # tier-consistent
    assert pair.stratum == "contested"
    assert pair.provenance["origin"] == "synthetic-probe"


def test_build_corpus_strata_and_write(tmp_path: Path):
    seeds = [Anchor(f"prompt {i}", "", TRUST_UNLABELED, "escalation", f"e{i}") for i in range(6)]
    rng = random.Random(11)
    train, valid = build_corpus(seeds, target_pairs=100, strata=(0.4, 0.3, 0.3), rng=rng)
    allp = train + valid
    assert len(allp) == 100
    counts = {"contested": 0, "local": 0, "frontier": 0}
    for p in allp:
        counts[p.stratum] += 1
    assert counts == {"contested": 40, "local": 30, "frontier": 30}
    write_corpus(train, valid, tmp_path, heldout=[
        Anchor("held", "local", TRUST_GOLD, "toll_pick", "l1")])
    train_lines = (tmp_path / "train.jsonl").read_text().strip().splitlines()
    valid_lines = (tmp_path / "valid.jsonl").read_text().strip().splitlines()
    meta = [json.loads(l) for l in (tmp_path / "metadata.jsonl").read_text().strip().splitlines()]
    held = [json.loads(l) for l in (tmp_path / "heldout.jsonl").read_text().strip().splitlines()]
    assert len(train_lines) == len(train) and len(valid_lines) == len(valid)
    for line in train_lines + valid_lines:
        row = json.loads(line)
        assert set(row) == {"messages"}  # mlx-lm chat format, metadata lives in the sidecar
    assert len(meta) == len(allp)
    assert {m["stratum"] for m in meta} == {"contested", "local", "frontier"}
    assert held[0]["source_id"] == "l1" and held[0]["tier"] == "local"
    # train/valid prompts disjoint
    tp = {json.loads(l)["messages"][1]["content"] for l in train_lines}
    vp = {json.loads(l)["messages"][1]["content"] for l in valid_lines}
    assert not tp & vp


def test_train_pairs_never_use_real_verdict_bearing_prompts(tmp_path: Path):
    gold_prompt = "the gold toll pick prompt"
    seeds = [Anchor(gold_prompt, "", TRUST_UNLABELED, "escalation", "e1")]
    heldout = [Anchor(gold_prompt, "local", TRUST_GOLD, "toll_pick", "l1")]
    train, valid = build_corpus(seeds, target_pairs=10, rng=random.Random(5))
    trained_prompts = {p.messages[1]["content"] for p in train + valid}
    # synthesized pairs are framed variations, and no real labeled case is trained on verbatim
    assert gold_prompt not in trained_prompts
    write_corpus(train, valid, tmp_path, heldout=heldout)
    assert (tmp_path / "heldout.jsonl").exists()


# ---------------------------------------------------------------- dry run


def test_dry_run_report_on_fixture_harvest(tmp_path: Path):
    led = tmp_path / "ledger.jsonl"
    led.write_text("\n".join(json.dumps(e) for e in [
        _ledger_entry(toll="answered", route_choice="human:frontier:claude"),
        _ledger_entry(toll="expired", route_choice="auto:local"),
    ]) + "\n")
    esc_dir = tmp_path / "escalations"
    esc_dir.mkdir()
    (esc_dir / "esc-1.json").write_text(json.dumps({
        "id": "esc-1", "requested_tier": "frontier:architect",
        "messages": [{"role": "user", "content": "Design the whole thing."}]}))
    report = dry_run_report(tmp_path)
    assert report["anchors"]["total"] == 3
    assert report["by_trust"] == {"gold": 1, "silver": 1, "unlabeled": 1}
    assert len(report["heldout_roster"]) == 2
    assert report["train_seed_count"] == 1
    assert report["strata"] == {"contested": 0.4, "local": 0.3, "frontier": 0.3}
