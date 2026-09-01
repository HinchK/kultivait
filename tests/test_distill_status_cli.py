"""S4 (#104) tests: the distillate registry dashboard."""

import argparse
import json
from pathlib import Path

import pytest

from kultivait.cli import cmd_distill_status
from kultivait.config import Config, DistillConfig


REGISTRY = {
    "kv-judge-llama32-3b-g0": {"generation": 0, "base": "llama-3.2-3b-instruct",
                                 "quantize": "q4_K_M", "registered": True,
                                 "fused_path": "/models/g0/fused"},
    "kv-judge-llama32-3b-g1": {"generation": 1, "base": "llama-3.2-3b-instruct",
                                 "quantize": "q4_K_M", "registered": True,
                                 "fused_path": "/models/g1/fused"},
}


@pytest.fixture
def env(tmp_path, monkeypatch):
    reg_dir = tmp_path / "models"
    reg_dir.mkdir()
    (reg_dir / "distillates.json").write_text(json.dumps(REGISTRY))
    monkeypatch.setattr("kultivait.cli.KULTIVAIT_HOME", tmp_path)
    monkeypatch.setattr("kultivait.cli.get_config", lambda: Config(
        distill=DistillConfig(model="qwen3.5:4b", shadow_model="kv-judge-llama32-3b-g1",
                              shadow_mode="on")))
    monkeypatch.setattr("kultivait.cli.LEDGER_PATH", tmp_path / "ledger.jsonl")
    return tmp_path


def run_status(json_mode=False):
    cmd_distill_status(argparse.Namespace(json=json_mode))


# ---------------------------------------------------------------- JSON mode


def test_json_carries_full_registry_and_seats(env, capsys):
    run_status(json_mode=True)
    data = json.loads(capsys.readouterr().out)
    assert data["active_seat"] == "qwen3.5:4b"
    assert data["shadow_seat"] == "kv-judge-llama32-3b-g1"
    assert len(data["distillates"]) == 2
    g1 = next(d for d in data["distillates"] if "g1" in d["name"])
    assert "SHADOW" in g1["seat"]
    assert g1["generation"] == 1


# ---------------------------------------------------------------- text mode


def test_text_renders_the_dashboard(env, capsys):
    run_status()
    text = capsys.readouterr().out
    assert "distillate registry" in text
    assert "qwen3.5:4b" in text
    assert "kv-judge-llama32-3b-g0" in text and "kv-judge-llama32-3b-g1" in text
    assert "SHADOW" in text and "retired" in text
    assert "q4_K_M" in text


def test_generations_sorted(env, capsys):
    run_status(json_mode=True)
    data = json.loads(capsys.readouterr().out)
    gens = [d["generation"] for d in data["distillates"]]
    assert gens == sorted(gens)


# ---------------------------------------------------------------- edge cases


def test_empty_registry_renders_cleanly(tmp_path, monkeypatch, capsys):
    reg_dir = tmp_path / "models"
    reg_dir.mkdir()
    (reg_dir / "distillates.json").write_text("{}")
    monkeypatch.setattr("kultivait.cli.KULTIVAIT_HOME", tmp_path)
    monkeypatch.setattr("kultivait.cli.get_config", lambda: Config())
    monkeypatch.setattr("kultivait.cli.LEDGER_PATH", tmp_path / "l.jsonl")
    run_status()
    text = capsys.readouterr().out
    assert "distillate registry" in text  # renders, doesn't crash


def test_missing_registry_file_renders_cleanly(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("kultivait.cli.KULTIVAIT_HOME", tmp_path)
    monkeypatch.setattr("kultivait.cli.get_config", lambda: Config())
    monkeypatch.setattr("kultivait.cli.LEDGER_PATH", tmp_path / "l.jsonl")
    run_status(json_mode=True)
    data = json.loads(capsys.readouterr().out)
    assert data["distillates"] == []


def test_active_seat_assignment(env, capsys):
    run_status(json_mode=True)
    data = json.loads(capsys.readouterr().out)
    # neither distillate is the active seat (the incumbent qwen holds it)
    assert all("ACTIVE" not in d["seat"] for d in data["distillates"])
    assert data["active_seat"] == "qwen3.5:4b"
