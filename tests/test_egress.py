"""#225: cloud-egress policy engine, secret-risk guard, enforcement, CLI.

Covers posture evaluation and persistence, ask-once-per-repo pending asks,
the unconditional secret guard (including precedence over allow), the
server dispatch path (0-egress on blocked repos, decisions on ledger rows),
the eval wrapper (B2 via the real guard), and the CLI grammar.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi.testclient import TestClient

from kultivait import cli, egress
from kultivait.backends import Completion
from kultivait.escalations import EscalationStore
from kultivait.gates import Gate
from kultivait.ledger import Ledger
from kultivait.router import Router
from kultivait.server import create_app

ORDER = ["qwen3.5:4b", "qwen3:14b", "frontier:architect"]
LOCAL = {"qwen3.5:4b": True, "qwen3:14b": True, "frontier:architect": False}

SECRET_PROMPT = "rotate the key sk-ant-api03-abcdef0123456789abcdef across scripts"
CLEAN_FRONTIER_PROMPT = "design a multi-region failover architecture for ingest"


# ----------------------------------------------------------------------
# engine: postures, persistence, pending asks
# ----------------------------------------------------------------------


def test_unknown_repo_defaults_to_ask_and_persists_answers(tmp_path):
    pol = tmp_path / "policy.json"
    assert egress.repo_posture("hash1", egress.load_policy(pol)) == "ask"
    egress.set_repo_posture("hash1", "allow", pol)
    assert egress.repo_posture("hash1", egress.load_policy(pol)) == "allow"
    egress.set_global_posture("block", pol)
    assert egress.load_policy(pol)["global"] == "block"


def test_set_posture_validates(tmp_path):
    with pytest.raises(ValueError):
        egress.set_repo_posture("h", "sometimes", tmp_path / "p.json")
    with pytest.raises(ValueError):
        egress.set_global_posture("maybe", tmp_path / "p.json")


def test_enforce_postures(tmp_path):
    pending = tmp_path / "pending.json"
    kw = dict(capability_order=ORDER, local_flags=LOCAL, pending_path=pending)

    # local tier: no egress considered at all
    assert egress.enforce_prompt_policy("anything", "qwen3:14b", **kw) == \
        ("qwen3:14b", "local_only")

    # allow: frontier dispatch passes
    assert egress.enforce_prompt_policy(CLEAN_FRONTIER_PROMPT, "frontier:architect",
                                        policy={"global": "allow", "repos": {}}, **kw) == \
        ("frontier:architect", "allowed")

    # block: degrades to the local floor
    assert egress.enforce_prompt_policy(CLEAN_FRONTIER_PROMPT, "frontier:architect",
                                        policy={"global": "block", "repos": {}}, **kw) == \
        ("qwen3:14b", "blocked_policy")

    # repo-scoped block beats a permissive global
    assert egress.enforce_prompt_policy(
        CLEAN_FRONTIER_PROMPT, "frontier:architect",
        policy={"global": "allow", "repos": {"hash9": "block"}},
        repo_hash="hash9", **kw) == ("qwen3:14b", "blocked_policy")


def test_secret_guard_is_unconditional_and_precedes_allow(tmp_path):
    pending = tmp_path / "pending.json"
    kw = dict(capability_order=ORDER, local_flags=LOCAL, pending_path=pending)
    tier, decision = egress.enforce_prompt_policy(
        SECRET_PROMPT, "frontier:architect",
        policy={"global": "allow", "repos": {}}, **kw)
    assert (tier, decision) == ("qwen3:14b", "blocked_secret")


def test_ask_records_pending_and_degrades(tmp_path):
    pending = tmp_path / "pending.json"
    tier, decision = egress.enforce_prompt_policy(
        CLEAN_FRONTIER_PROMPT, "frontier:architect",
        capability_order=ORDER, local_flags=LOCAL,
        policy={"global": "ask", "repos": {}}, repo_hash="hash7",
        pending_path=pending)
    assert (tier, decision) == ("qwen3:14b", "ask_local")
    assert "hash7" in egress.load_pending(pending)  # ask-once: stable
    egress.enforce_prompt_policy(
        CLEAN_FRONTIER_PROMPT, "frontier:architect",
        capability_order=ORDER, local_flags=LOCAL,
        policy={"global": "ask", "repos": {}}, repo_hash="hash7",
        pending_path=pending)
    assert len(egress.load_pending(pending)) == 1
    egress.set_repo_posture("hash7", "allow", tmp_path / "policy.json")
    egress.clear_pending("hash7", pending)
    assert egress.load_pending(pending) == {}


# ----------------------------------------------------------------------
# server enforcement: decisions on rows, 0-egress guarantee
# ----------------------------------------------------------------------


class _FakeLocal:
    supports_tools = True
    local = True

    def complete(self, messages, tools=None, effort_flags=None, model_override=None, **kw):
        return Completion(text="local ok", tokens_in=5, tokens_out=3, cost_usd=0.0, local=True)

    def stream(self, messages, tools=None, effort_flags=None, model_override=None, **kw):
        yield "ok"
        yield self.complete(messages, tools, effort_flags, model_override)


class _FakeFrontier:
    supports_tools = True
    local = False

    def __init__(self):
        self.dispatched = 0

    def complete(self, messages, tools=None, effort_flags=None, model_override=None, **kw):
        self.dispatched += 1
        return Completion(text="cloud ok", tokens_in=5, tokens_out=3, cost_usd=0.01, local=False)

    def stream(self, messages, tools=None, effort_flags=None, model_override=None, **kw):
        yield "ok"
        yield self.complete(messages, tools, effort_flags, model_override)


def _app(tmp_path, policy=None, monkeypatch=None, repo_hash="repo-hash-1"):
    if monkeypatch is not None and policy is not None:
        p = tmp_path / "policy.json"
        p.write_text(json.dumps(policy))
        monkeypatch.setattr(egress, "POLICY_PATH", p)
    monkeypatch.setattr(cli, "CONFIG_PATH", tmp_path / "config.toml")
    frontier = _FakeFrontier()
    app = create_app(
        router=Router(
            centroids={"qwen3:14b": np.array([0.0, 1.0]), "frontier:architect": np.array([1.0, 0.0])},
            capability_order=ORDER,
        ),
        embed=lambda text: np.array([1.0, 0.0]),  # classifies frontier
        backends={"qwen3.5:4b": _FakeLocal(), "qwen3:14b": _FakeLocal(),
                  "frontier:architect": frontier},
        ledger=Ledger(tmp_path / "l.jsonl"),
        gate=Gate(generate=lambda p: "d", compost_dir=tmp_path / "compost"),
        escalations=EscalationStore(tmp_path / "esc"),
        toll_enabled=False,
    )
    return app, frontier


def test_secret_prompt_never_egresses_from_the_proxy(tmp_path, monkeypatch):
    pending = tmp_path / "pending.json"
    monkeypatch.setattr(egress, "PENDING_PATH", pending)
    app, frontier = _app(tmp_path, policy={"global": "allow", "repos": {}},
                         monkeypatch=monkeypatch)
    client = TestClient(app)
    resp = client.post("/v1/chat/completions",
                       json={"model": "auto", "messages": [{"role": "user", "content": SECRET_PROMPT}]})
    assert resp.status_code == 200
    assert resp.json()["model"] == "qwen3:14b"  # best local tier, never the cloud
    assert frontier.dispatched == 0  # 0 bytes egress
    row = Ledger(tmp_path / "l.jsonl").read_rows()[0]
    assert row["cloud_egress_decision"] == "blocked_secret"
    assert row["fallback_reason"] == "secret_no_egress"
    assert row["cloud_egress"] is False


def test_blocked_repo_guarantees_zero_egress(tmp_path, monkeypatch):
    pending = tmp_path / "pending.json"
    monkeypatch.setattr(egress, "PENDING_PATH", pending)
    app, frontier = _app(tmp_path, policy={"global": "block", "repos": {}},
                         monkeypatch=monkeypatch)
    client = TestClient(app)
    resp = client.post("/v1/chat/completions",
                       json={"model": "auto", "messages": [{"role": "user", "content": CLEAN_FRONTIER_PROMPT}]})
    assert resp.status_code == 200
    assert resp.json()["model"] == "qwen3:14b"
    assert frontier.dispatched == 0
    row = Ledger(tmp_path / "l.jsonl").read_rows()[-1]
    assert row["cloud_egress_decision"] == "blocked_policy"
    assert row["fallback_reason"] == "egress_blocked"


def test_allow_posture_permits_frontier_with_decision_allowed(tmp_path, monkeypatch):
    pending = tmp_path / "pending.json"
    monkeypatch.setattr(egress, "PENDING_PATH", pending)
    app, frontier = _app(tmp_path, policy={"global": "allow", "repos": {}},
                         monkeypatch=monkeypatch)
    client = TestClient(app)
    resp = client.post("/v1/chat/completions",
                       json={"model": "auto", "messages": [{"role": "user", "content": CLEAN_FRONTIER_PROMPT}]})
    assert resp.json()["model"] == "frontier:architect"
    assert frontier.dispatched == 1
    row = Ledger(tmp_path / "l.jsonl").read_rows()[0]
    assert row["cloud_egress_decision"] == "allowed"


def test_ask_posture_degrades_and_records_pending(tmp_path, monkeypatch):
    pending = tmp_path / "pending.json"
    monkeypatch.setattr(egress, "PENDING_PATH", pending)
    app, frontier = _app(tmp_path, policy={"global": "ask", "repos": {}},
                         monkeypatch=monkeypatch)
    client = TestClient(app)
    resp = client.post("/v1/chat/completions",
                       json={"model": "auto", "messages": [{"role": "user", "content": CLEAN_FRONTIER_PROMPT}]})
    assert resp.json()["model"] == "qwen3:14b"
    assert frontier.dispatched == 0
    row = Ledger(tmp_path / "l.jsonl").read_rows()[0]
    assert row["cloud_egress_decision"] == "ask_local"
    assert row["fallback_reason"] == "egress_ask"
    assert egress.load_pending(pending)  # the ask is recorded for the CLI


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------


def _egress_args(**kw):
    base = dict(posture=None, repo=None, global_=False, answer=False)
    base.update(kw)
    return SimpleNamespace(**base)


def test_cmd_egress_inspect_set_and_answer(tmp_path, capsys, monkeypatch):
    pol = tmp_path / "policy.json"
    pend = tmp_path / "pending.json"
    monkeypatch.setattr(egress, "POLICY_PATH", pol)
    monkeypatch.setattr(egress, "PENDING_PATH", pend)
    monkeypatch.setattr(cli, "CONFIG_PATH", tmp_path / "config.toml")
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)

    cli.cmd_egress(_egress_args())
    out = capsys.readouterr().out
    assert "global default: ask" in out and "no pending asks" in out

    cli.cmd_egress(_egress_args(posture="block", global_=True))
    assert egress.load_policy(pol)["global"] == "block"

    egress.record_pending_ask("hash42", pend)
    cli.cmd_egress(_egress_args(posture="allow", answer=True))
    out = capsys.readouterr().out
    assert "hash42 → allow" in out
    assert egress.load_pending(pend) == {}
    assert egress.repo_posture("hash42", egress.load_policy(pol)) == "allow"

    cli.cmd_egress(_egress_args(posture="ask", repo="hash99"))
    assert egress.repo_posture("hash99", egress.load_policy(pol)) == "ask"
