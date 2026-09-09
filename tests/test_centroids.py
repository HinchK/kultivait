"""Learned centroids (ADR 0021): blend, extraction, table, seat, shadow."""

import json
from pathlib import Path

import numpy as np
import pytest

from kultivait import centroids as cent
from kultivait.router import Decision, Router
from kultivait.seeds import ROLE_SEEDS


def fake_embed_batch(texts):
    """Deterministic embedder: unit vectors seeded by text length mod classes."""
    out = []
    for t in texts:
        base = np.zeros(8)
        base[len(t) % 8] = 1.0
        out.append(base)
    return np.stack(out)


def make_ledger(path: Path, rows):
    for row in rows:
        base = dict(tier="t", local=True, tokens_in=10, tokens_out=5, cost_usd=0.0)
        base.update(row)
        path.write_text(path.read_text() + json.dumps(base) + "\n" if path.exists()
                        else json.dumps(base) + "\n")


def make_escalation(directory: Path, text, requested_tier="claude"):
    directory.mkdir(parents=True, exist_ok=True)
    eid = f"esc-{len(list(directory.glob('esc-*.json'))):03d}"
    (directory / f"{eid}.json").write_text(json.dumps({
        "id": eid, "requested_tier": requested_tier,
        "messages": [{"role": "user", "content": text}],
    }))
    return eid


TIER_ROLES = {"llama": "simple", "qwen": "reasoning", "agy": "docs", "claude": "architect"}


# ---------- extraction ----------


def test_extraction_gold_silver_escalation_and_dedup(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    long = "x" * 60
    make_ledger(ledger, [
        {"tier": "claude", "toll": "answered", "route_choice": "llama",
         "snippet": long + "gold", "fingerprint": "f1"},
        {"tier": "llama", "snippet": long + "silver", "fingerprint": "f2"},
        {"tier": "llama", "snippet": long + "silver", "fingerprint": "f3"},  # dedup by text
        {"tier": "unknown-tier", "snippet": long + "zz"},  # unknown role -> skipped
        {"tier": "qwen", "snippet": "short"},  # below SILVER_MIN_CHARS
        {"tier": "qwen", "fallback_reason": "tools_unsupported", "snippet": long + "esc"},
    ])
    esc_dir = tmp_path / "escalations"
    make_escalation(esc_dir, long + "arch-escalation", requested_tier="claude")
    signals = cent.extract_signals(ledger, esc_dir, TIER_ROLES)
    assert len(signals["simple"]["gold"]) == 1        # toll pick chose llama/simple
    assert len(signals["simple"]["silver"]) == 1      # dedup collapsed the repeat
    assert len(signals["architect"]["escalation"]) == 1
    assert not any(signals["reasoning"][k] for k in ("gold", "silver", "escalation"))


def test_extraction_virtual_tier_role(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    make_ledger(ledger, [{"tier": "frontier:docs", "snippet": "y" * 55}])
    signals = cent.extract_signals(ledger, tmp_path / "none", TIER_ROLES)
    assert len(signals["docs"]["silver"]) == 1


# ---------- learn + blend ----------


def test_learn_min_signal_fallback_and_provenance(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    esc_dir = tmp_path / "escalations"
    for i in range(12):
        make_ledger(ledger, [{"tier": "llama", "snippet": f"silver prompt number {i:02d} " + "z" * 45}])
    result = cent.learn(fake_embed_batch, TIER_ROLES, ledger_path=ledger,
                        escalations_dir=esc_dir, min_signals=10,
                        path=tmp_path / "centroids.json")
    table = cent.load_table(tmp_path / "centroids.json")
    assert result["version"] == "learned-v1"
    assert "seeds-v0" in table["versions"]
    simple = table["versions"]["learned-v1"]["roles"]["simple"]
    assert simple["source"] == "learned"
    assert simple["provenance"]["silver"] == 12
    # roles without signals keep the seed prior, note recorded
    assert table["versions"]["learned-v1"]["roles"]["docs"]["source"] == "seeds"


def test_learned_vector_is_blend_not_replacement(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    for i in range(20):
        make_ledger(ledger, [{"tier": "llama", "snippet": f"prompt {i} " + "a" * 50}])
    cent.learn(fake_embed_batch, TIER_ROLES, ledger_path=ledger,
               escalations_dir=tmp_path, path=tmp_path / "c.json")
    table = cent.load_table(tmp_path / "c.json")
    seed = table["versions"]["seeds-v0"]["roles"]["simple"]["vector"]
    learned = table["versions"]["learned-v1"]["roles"]["simple"]["vector"]
    cos = float(np.dot(seed, learned) / (np.linalg.norm(seed) * np.linalg.norm(learned)))
    assert cos > 0.05  # the prior keeps them correlated; history bends, not replaces
    assert abs(np.linalg.norm(learned) - 1.0) < 1e-9


def test_version_increments(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    for i in range(12):
        make_ledger(ledger, [{"tier": "llama", "snippet": f"s{i} " + "b" * 50}])
    p = tmp_path / "c.json"
    cent.learn(fake_embed_batch, TIER_ROLES, ledger_path=ledger, escalations_dir=tmp_path, path=p)
    r2 = cent.learn(fake_embed_batch, TIER_ROLES, ledger_path=ledger, escalations_dir=tmp_path, path=p)
    assert r2["version"] == "learned-v2"


# ---------- seat + cutover ----------


def test_seat_defaults_empty(tmp_path):
    assert cent.seat(tmp_path / "none.toml") == {"active_version": "", "shadow_version": ""}


def test_set_active_version_roundtrip(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('runtime = "ollama"\n\n[centroids]\nactive_version = "seeds-v0"\n')
    cent.set_active_version(cfg, "learned-v1")
    assert cent.seat(cfg)["active_version"] == "learned-v1"
    # preserves the rest of the file
    assert 'runtime = "ollama"' in cfg.read_text()
    # rollback
    cent.set_active_version(cfg, "seeds-v0")
    assert cent.seat(cfg)["active_version"] == "seeds-v0"


def test_set_active_version_appends_missing_section(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('runtime = "ollama"\n')
    cent.set_active_version(cfg, "learned-v1")
    assert cent.seat(cfg)["active_version"] == "learned-v1"


def test_router_for_version(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    p = tmp_path / "c.json"
    cent.learn(fake_embed_batch, TIER_ROLES, ledger_path=ledger,
               escalations_dir=tmp_path, path=p)

    class Tier:
        def __init__(self, name, role):
            self.name, self.role = name, role

    class Cfg:
        tiers = [Tier("llama", "simple"), Tier("claude", "architect")]

        def capability_order(self):
            return ["llama", "claude"]

    router = cent.router_for_version("seeds-v0", Cfg(), fake_embed_batch, p)
    assert isinstance(router, Router)
    assert cent.router_for_version("missing-v9", Cfg(), fake_embed_batch) is None


# ---------- shadow ----------


def test_shadow_classify_logs_disagreement_only(tmp_path):
    log = tmp_path / "shadow.jsonl"
    table = tmp_path / "c.json"
    cent.learn(fake_embed_batch, TIER_ROLES, ledger_path=tmp_path / "l.jsonl",
               escalations_dir=tmp_path, path=table)
    # force the seat to shadow learned-v1
    cfg = tmp_path / "config.toml"
    cfg.write_text('[centroids]\nshadow_version = "learned-v1"\n')
    cent._shadow_cache.clear()
    from unittest.mock import patch

    class Tier:
        def __init__(self, name, role):
            self.name, self.role = name, role

    class Cfg:
        tiers = [Tier("llama", "simple"), Tier("claude", "architect")]

        def capability_order(self):
            return ["llama", "claude"]

    seat_data = {"active_version": "", "shadow_version": "learned-v1"}
    with patch("kultivait.centroids.seat", return_value=seat_data), \
         patch("kultivait.centroids.load_table", return_value=cent.load_table(table)):
        router = cent.shadow_router(config=Cfg(), embed_batch=fake_embed_batch)
        assert router is not None
        vec = fake_embed_batch(["whatever"])[0]
        candidate_says = router.classify(vec).tier
        incumbent_tier = "claude" if candidate_says != "claude" else "llama"
        incumbent = Decision(tier=incumbent_tier, margin=0.5, escalated=False)
        # disagreement is guaranteed by construction -> a row must land
        cent.maybe_shadow_classify(vec, incumbent, "fp", config=Cfg(),
                                   embed_batch=fake_embed_batch, log_path=log)
    assert log.exists()


def test_shadow_stats_filters_kind(tmp_path):
    log = tmp_path / "shadow.jsonl"
    log.write_text(json.dumps({
        "ts": 0, "fingerprint": "f", "prompt_hash": "",
        "incumbent": {"kind": "centroid", "tier": "a"},
        "shadow": {"kind": "centroid", "tier": "b"}, "agree": False,
    }) + "\n" + json.dumps({
        "ts": 0, "fingerprint": "f", "prompt_hash": "",
        "incumbent": {"model": "x"}, "shadow": {"model": "y"}, "agree": False,
    }) + "\n")
    assert cent.shadow_stats(log)["disagreements"] == 1


# ---------- substrate: snippet cap ----------


def test_snippet_cap_is_512():
    import inspect
    from kultivait import server

    src = inspect.getsource(server)
    assert "user_text[:512]" in src
    assert "user_text[:80]" not in src
