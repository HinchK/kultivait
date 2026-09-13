"""ADR 0025 / #223: route-outcome record, outcome labels, pull-only export.

Covers the privacy primitives (salt, salted repo hash, secret-shape
refusal), ledger label attachment, server row extras + /api/label, the CLI
label/report surfaces, the post-toll pending label, and the zero-network
invariant on the export path.
"""

import json
import socket
import stat
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from fastapi.testclient import TestClient

from kultivait import cli, privacy
from kultivait.backends import Completion
from kultivait.escalations import EscalationStore
from kultivait.gates import Gate
from kultivait.ledger import Ledger
from kultivait.router import Router
from kultivait.server import create_app


# ----------------------------------------------------------------------
# privacy primitives
# ----------------------------------------------------------------------


def test_install_salt_generated_once_and_persistent(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('runtime = "ollama"\n')
    salt1 = privacy.ensure_install_salt(cfg)
    salt2 = privacy.ensure_install_salt(cfg)
    assert salt1 == salt2 and len(salt1) == 32
    body = cfg.read_text()
    assert 'install_salt = ' in body
    assert 'runtime = "ollama"' in body  # other lines untouched


def test_repo_hash_is_salted_and_leaks_no_path(tmp_path):
    a = privacy.repo_hash_for(tmp_path, salt="s1")
    b = privacy.repo_hash_for(tmp_path, salt="s2")
    assert a != b  # salted
    assert a == privacy.repo_hash_for(tmp_path, salt="s1")  # deterministic
    joined = " ".join([a, b])
    assert str(tmp_path) not in joined  # never the raw path
    assert tmp_path.name not in joined  # never the repo name


def test_secret_shape_detection_positives_and_negatives():
    positives = [
        "key sk-ant-api03-XXYYZZAABBCCDDEEFF0011 here",
        "pat ghp_" + "a1B2c3D4e5" * 4,
        "aws AKIAIOSFODNN7EXAMPLE",
        "slack xoxb-1234567890abc",
        "-----BEGIN RSA PRIVATE KEY-----",
        "password = hunter2hunter2hunter2",
        "api_key: 8f3c9d2e7b1a4f6c8d0e",
    ]
    for text in positives:
        assert privacy.contains_secret_shape(text), text
    negatives = [
        "fix the router margin bug in server.py",
        "Bearer of bad news: the deploy failed",
        "the sk-ride was short",  # below length floor
        "",
        None,
    ]
    for text in negatives:
        assert not privacy.contains_secret_shape(text), text


def test_outcome_label_enum_is_pinned():
    assert privacy.OUTCOME_LABELS == ("accepted", "retried", "escalated", "wrong_route")


# ----------------------------------------------------------------------
# ledger: label attachment
# ----------------------------------------------------------------------


def _seed(ledger: Ledger):
    ledger.record(tier="qwen3:14b", local=True, tokens_in=10, tokens_out=5,
                  cost_usd=0.0, latency_s=1.0, first_token_ms=400)
    ledger.record(tier="openrouter", local=False, tokens_in=10, tokens_out=5,
                  cost_usd=0.001, latency_s=2.0, first_token_ms=900)


def test_set_and_clear_outcome_label(tmp_path):
    ledger = Ledger(tmp_path / "l.jsonl")
    _seed(ledger)
    row = ledger.set_outcome_label(2, "wrong_route")
    assert row["outcome_label"] == "wrong_route"
    rows = ledger.read_rows()
    assert rows[1]["outcome_label"] == "wrong_route"
    assert "outcome_label" not in rows[0]
    ledger.clear_outcome_label(2)
    assert "outcome_label" not in ledger.read_rows()[1]


def test_set_outcome_label_validates_enum_and_range(tmp_path):
    ledger = Ledger(tmp_path / "l.jsonl")
    _seed(ledger)
    try:
        ledger.set_outcome_label(1, "fine")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass
    try:
        ledger.set_outcome_label(99, "accepted")
        raise AssertionError("expected IndexError")
    except IndexError:
        pass


def test_label_last_targets_only_unlabeled(tmp_path):
    ledger = Ledger(tmp_path / "l.jsonl")
    _seed(ledger)
    ledger.set_outcome_label(1, "accepted")
    n = ledger.label_last(5, "accepted")
    assert n == 1  # row 2 only
    assert all(r.get("outcome_label") == "accepted" for r in ledger.read_rows())


def test_record_returns_row_index(tmp_path):
    ledger = Ledger(tmp_path / "l.jsonl")
    assert ledger.record(tier="t", local=True, tokens_in=1, tokens_out=1, cost_usd=0.0) == 1
    assert ledger.record(tier="t", local=True, tokens_in=1, tokens_out=1, cost_usd=0.0) == 2


# ----------------------------------------------------------------------
# server: row extras + /api/label
# ----------------------------------------------------------------------


class _FakeLocal:
    supports_tools = True
    local = True

    def complete(self, messages, tools=None, effort_flags=None, model_override=None, **kw):
        return Completion(text="ok", tokens_in=5, tokens_out=3, cost_usd=0.0, local=True)

    def stream(self, messages, tools=None, effort_flags=None, model_override=None, **kw):
        yield "ok"
        yield self.complete(messages, tools, effort_flags, model_override)


def _app(tmp_path):
    return create_app(
        router=Router(
            centroids={"qwen3:14b": np.array([1.0, 0.0]), "frontier": np.array([0.0, 1.0])},
            capability_order=["qwen3:14b", "frontier"],
        ),
        embed=lambda text: np.array([1.0, 0.0]),
        backends={"qwen3:14b": _FakeLocal()},
        ledger=Ledger(tmp_path / "l.jsonl"),
        gate=Gate(generate=lambda p: "d", compost_dir=tmp_path / "compost"),
        escalations=EscalationStore(tmp_path / "esc"),
        toll_enabled=False,
    )


def test_dispatch_row_carries_route_outcome_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "CONFIG_PATH", tmp_path / "config.toml")
    client = TestClient(_app(tmp_path))
    resp = client.post(
        "/v1/chat/completions",
        json={"model": "auto", "messages": [{"role": "user", "content": "hello"}]},
    )
    assert resp.status_code == 200
    row = Ledger(tmp_path / "l.jsonl").read_rows()[0]
    assert row["policy_version"] == privacy.POLICY_VERSION
    assert row["repo_hash"] and len(row["repo_hash"]) == 16
    assert row["cloud_egress"] is False
    assert row["override"] is False
    assert row["candidate_tiers"] == ["qwen3:14b", "frontier"]
    assert "outcome_label" not in row  # fresh dispatches are unlabeled


def test_api_label_endpoint_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "CONFIG_PATH", tmp_path / "config.toml")
    client = TestClient(_app(tmp_path))
    client.post("/v1/chat/completions",
                json={"model": "auto", "messages": [{"role": "user", "content": "hi"}]})
    resp = client.post("/api/label", json={"row_index": 1, "label": "accepted"})
    assert resp.status_code == 200 and resp.json()["outcome_label"] == "accepted"
    assert Ledger(tmp_path / "l.jsonl").read_rows()[0]["outcome_label"] == "accepted"
    assert client.post("/api/label", json={"row_index": 1, "label": "meh"}).status_code == 400
    assert client.post("/api/label", json={"row_index": 99, "label": "accepted"}).status_code == 404
    assert client.post("/api/label", json={"row_index": "x", "label": "accepted"}).status_code == 400


# ----------------------------------------------------------------------
# CLI: label + pull-only report
# ----------------------------------------------------------------------


def _label_args(**kw):
    base = dict(row_index=None, label=None, last=None, clear=False)
    base.update(kw)
    return SimpleNamespace(**base)


def _report_args(**kw):
    base = dict(export=False, out=None, include_snippets=False)
    base.update(kw)
    return SimpleNamespace(**base)


def test_cmd_label_lists_sets_and_batches(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(cli, "PENDING_LABEL_PATH", tmp_path / "pending.json")
    ledger = Ledger(tmp_path / "l.jsonl")
    ledger.record(tier="qwen3:14b", local=True, tokens_in=1, tokens_out=1,
                  cost_usd=0.0, snippet="fix the router margin")
    ledger.record(tier="openrouter", local=False, tokens_in=1, tokens_out=1,
                  cost_usd=0.002, snippet="design the API")
    cli.cmd_label(_label_args(), ledger_path=tmp_path / "l.jsonl")
    out = capsys.readouterr().out
    assert "row" in out and "qwen3:14b" in out and "—" in out
    cli.cmd_label(_label_args(row_index=1, label="accepted"), ledger_path=tmp_path / "l.jsonl")
    cli.cmd_label(_label_args(last=5, label="wrong_route"), ledger_path=tmp_path / "l.jsonl")
    rows = ledger.read_rows()
    assert rows[0]["outcome_label"] == "accepted"
    assert rows[1]["outcome_label"] == "wrong_route"
    cli.cmd_label(_label_args(row_index=2, clear=True), ledger_path=tmp_path / "l.jsonl")
    assert "outcome_label" not in ledger.read_rows()[1]


def test_report_export_scrubs_and_refuses(tmp_path, capsys, monkeypatch):
    redactions = tmp_path / "redactions.jsonl"
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    ledger = Ledger(tmp_path / "l.jsonl")
    ledger.record(
        tier="qwen3:14b", local=True, tokens_in=1, tokens_out=1, cost_usd=0.0,
        latency_s=1.5, first_token_ms=700, snippet="fix the router margin bug",
        fingerprint="secret-fp-1", escalation_id="esc-1",
        policy_version=privacy.POLICY_VERSION, repo_hash="abcd1234abcd1234",
        cloud_egress=False, override=False, candidate_tiers=["a", "b"],
    )
    ledger.record(
        tier="qwen3:14b", local=True, tokens_in=1, tokens_out=1, cost_usd=0.0,
        snippet="token = sk-ant-api03-abcdef0123456789abcdef",
        fingerprint="secret-fp-2",
    )
    out = tmp_path / "report.jsonl"
    cli.cmd_report(_report_args(export=True, out=str(out)), ledger_path=tmp_path / "l.jsonl")
    lines = [json.loads(l) for l in out.read_text().splitlines()]
    assert len(lines) == 2
    assert all("snippet" not in r and "fingerprint" not in r for r in lines)  # default: omitted
    assert lines[0]["repo_hash"] == "abcd1234abcd1234"
    assert lines[0]["first_token_ms"] == 700
    capsys.readouterr()

    out2 = tmp_path / "report2.jsonl"
    cli.cmd_report(
        _report_args(export=True, out=str(out2), include_snippets=True),
        ledger_path=tmp_path / "l.jsonl",
    )
    lines2 = [json.loads(l) for l in out2.read_text().splitlines()]
    assert lines2[0]["snippet"] == "fix the router margin bug"  # clean snippet included
    assert "snippet" not in lines2[1]  # secret-bearing snippet REFUSED
    text = capsys.readouterr().out
    assert "refused (secret-shape)" in text
    assert "never transmits" in text


def test_report_export_is_zero_network(tmp_path, monkeypatch):
    """The pull-only invariant, enforced: with every outbound socket raised,
    the export must still complete — it is a local file write, nothing else."""
    def _no_sockets(*a, **k):
        raise AssertionError("network transmit attempted on the export path")

    monkeypatch.setattr(socket, "socket", _no_sockets)
    monkeypatch.setattr(socket, "create_connection", _no_sockets)
    ledger = Ledger(tmp_path / "l.jsonl")
    ledger.record(tier="t", local=True, tokens_in=1, tokens_out=1, cost_usd=0.0, snippet="clean")
    out = tmp_path / "r.jsonl"
    cli.cmd_report(_report_args(export=True, out=str(out), include_snippets=True),
                   ledger_path=tmp_path / "l.jsonl")
    assert len(out.read_text().splitlines()) == 1


def test_report_summary_mode_counts_labels(tmp_path, capsys):
    ledger = Ledger(tmp_path / "l.jsonl")
    _seed(ledger)
    ledger.set_outcome_label(1, "accepted")
    cli.cmd_report(_report_args(), ledger_path=tmp_path / "l.jsonl")
    out = capsys.readouterr().out
    assert "2 dispatches" in out and "1 labeled" in out and "accepted" in out


# ----------------------------------------------------------------------
# choose: post-toll pending label
# ----------------------------------------------------------------------


def test_post_toll_prompt_stashes_pending_label(tmp_path, monkeypatch):
    answers = iter(["1\n", "w\n"])  # menu pick 1, then label w
    monkeypatch.setattr(cli, "PENDING_LABEL_PATH", tmp_path / "pending.json")
    queue = tmp_path / "pending_tolls.jsonl"
    ticket = {
        "ticket_id": "toll-1", "fingerprint": "fp-abc",
        "options": [{"target": "local", "display_name": "Local"}],
    }
    queue.write_text(json.dumps(ticket) + "\n")
    cli.cmd_choose(
        args=None, queue_path=queue, answers_dir=tmp_path / "answers",
        presence_path=tmp_path / "presence.json", input_fn=lambda _p: next(answers),
    )
    pending = json.loads((tmp_path / "pending.json").read_text())
    assert pending["fingerprint"] == "fp-abc"
    assert pending["label"] == "wrong_route"


def test_pending_label_reconciles_onto_matching_row(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(cli, "PENDING_LABEL_PATH", tmp_path / "pending.json")
    ledger = Ledger(tmp_path / "l.jsonl")
    ledger.record(tier="t", local=True, tokens_in=1, tokens_out=1, cost_usd=0.0,
                  fingerprint="fp-abc", ts=100.0)
    (tmp_path / "pending.json").write_text(
        json.dumps({"fingerprint": "fp-abc", "label": "escalated", "ts": 99.0})
    )
    cli.cmd_label(_label_args(), ledger_path=tmp_path / "l.jsonl")
    assert ledger.read_rows()[0]["outcome_label"] == "escalated"
    assert not (tmp_path / "pending.json").exists()
    assert "applied post-toll label" in capsys.readouterr().out
