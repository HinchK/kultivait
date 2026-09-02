"""S2 (#102) tests: the shadow probe — replay, log appending, CLI flags."""

import argparse
import json
import time
from pathlib import Path

import pytest

from kultivait.distill.shadow import read_shadow_log, run_shadow_probe


def contract_json(top_fit: float) -> str:
    return json.dumps({
        "analysis": {"task_type": "debugging", "complexity": 5, "signals": [],
                     "subtask_candidates": []},
        "rewrite": "r",
        "judge": {"local_sufficient": False, "confidence": 0.8,
                  "targets": [{"target": "claude", "fit": top_fit, "effort": "medium"}]},
    })


class StubGenerate:
    """Two-model stub: incumbent says frontier (fit 0.9); shadow says contested (0.7)."""
    def __init__(self):
        self.calls: list = []

    def __call__(self, model: str, prompt: str):
        self.calls.append((model, prompt[:30]))
        fit = 0.9 if "qwen" in model else 0.7
        return contract_json(fit), 1.0


# ---------------------------------------------------------------- probe core


def test_probe_replays_band_and_appends_log(tmp_path: Path):
    log = tmp_path / "shadow.jsonl"
    gen = StubGenerate()
    result = run_shadow_probe(band="contested", n=5,
                              shadow_model="kv-judge-g1",
                              incumbent_model="qwen3.5:4b",
                              generate=gen, log_path=log)
    assert result["tasks_probed"] == 5  # n=5 caps (the contested band has 7)
    rows = read_shadow_log(log)
    assert len(rows) == 5
    for r in rows:
        assert r["incumbent"]["model"] == "qwen3.5:4b"
        assert r["shadow"]["model"] == "kv-judge-g1"
        assert r["shadow"]["parse_ok"] is True
        # incumbent fit 0.9 -> frontier; shadow fit 0.7 -> contested; disagree
        assert r["agree"] is False
        assert r["incumbent"]["verdict"] == "frontier"
        assert r["shadow"]["verdict"] == "contested"


def test_probe_respects_n_cap(tmp_path: Path):
    gen = StubGenerate()
    result = run_shadow_probe(band="simple", n=3,
                              shadow_model="g1", incumbent_model="qwen",
                              generate=gen, log_path=tmp_path / "l.jsonl")
    assert result["tasks_probed"] == min(3, 7)


def test_probe_records_latency_and_fingerprint(tmp_path: Path):
    log = tmp_path / "s.jsonl"
    gen = StubGenerate()
    run_shadow_probe(band="simple", n=2, shadow_model="g1",
                     incumbent_model="qwen", generate=gen, log_path=log)
    rows = read_shadow_log(log)
    for r in rows:
        assert r["fingerprint"].startswith("probe:")
        assert r["shadow"]["latency_s"] > 0


# ---------------------------------------------------------------- CLI


def test_cli_probe_json_mode(tmp_path: Path, capsys, monkeypatch):
    from kultivait.cli import cmd_shadow_probe
    from kultivait.config import Config, DistillConfig

    monkeypatch.setattr("kultivait.cli.get_config", lambda: Config(
        distill=DistillConfig(model="qwen3.5:4b",
                              shadow_model="kv-judge-g1", shadow_mode="on")))
    monkeypatch.setattr("kultivait.distill.shadow._default_log_path",
                        lambda: tmp_path / "shadow.jsonl")
    # stub the generate path
    import kultivait.server as srv
    monkeypatch.setattr(srv, "_default_preprocess_generate_for", lambda: StubGenerate())

    cmd_shadow_probe(argparse.Namespace(band="contested", n=3, json=True))
    data = json.loads(capsys.readouterr().out)
    assert data["band"] == "contested"
    assert data["shadow_model"] == "kv-judge-g1"
    assert data["tasks_probed"] >= 1


def test_cli_probe_no_shadow_model(tmp_path: Path, capsys, monkeypatch):
    from kultivait.cli import cmd_shadow_probe
    from kultivait.config import Config

    monkeypatch.setattr("kultivait.cli.get_config", lambda: Config())
    cmd_shadow_probe(argparse.Namespace(band="contested", n=3, json=False))
    assert "no shadow model" in capsys.readouterr().out
