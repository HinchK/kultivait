"""Slice D7 tests: CLI surface — cutover confirmation/rollback, shadow, subcommands."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from kultivait.cli import main as cli_main
from kultivait.config import DistillConfig, load_config, save_config, Config, TierSpec


def run_cli(argv: list, stdin: str = "") -> "subprocess.CompletedProcess":
    return subprocess.run(
        ["uv", "run", "kultivait", *argv],
        capture_output=True, text=True, input=stdin, timeout=60,
        cwd=Path(__file__).parent.parent,
    )


def make_config(tmp_path: Path, model="qwen3.5:4b") -> Path:
    cfg = Config(
        tiers=[TierSpec(name="m", role="simple", kind="ollama", model="m")],
        distill=DistillConfig(model=model),
    )
    p = tmp_path / "config.toml"
    save_config(cfg, p)
    return p


# ---------------------------------------------------------------- cutover


def test_cutover_requires_confirmation(tmp_path, monkeypatch, capsys):
    from kultivait import cli
    import argparse

    p = make_config(tmp_path)
    monkeypatch.setattr(cli, "CONFIG_PATH", p)
    args = argparse.Namespace(model="kv-judge-llama32-3b-g0", yes=False,
                              config=str(p))
    # declined: nothing written
    with monkeypatch.context() as m:
        m.setattr("builtins.input", lambda _: "n")
        cli.cmd_cutover(args)
    out = capsys.readouterr().out
    assert "aborted" in out.lower()
    assert load_config(p).distill.model == "qwen3.5:4b"


def test_cutover_flips_model_and_prints_rollback(tmp_path, monkeypatch, capsys):
    from kultivait import cli
    import argparse

    p = make_config(tmp_path)
    monkeypatch.setattr(cli, "CONFIG_PATH", p)
    args = argparse.Namespace(model="kv-judge-llama32-3b-g0", yes=True, config=str(p))
    cli.cmd_cutover(args)
    out = capsys.readouterr().out
    assert load_config(p).distill.model == "kv-judge-llama32-3b-g0"
    assert "kultivait cutover --model qwen3.5:4b" in out  # rollback line printed
    assert "[distill]" in p.read_text()
    # config preserved beyond the distill section
    assert loaded_tiers(p)


def loaded_tiers(p: Path) -> bool:
    cfg = load_config(p)
    return len(cfg.tiers) == 1 and cfg.tiers[0].name == "m"


def test_cutover_readiness_guard_when_not_ready(tmp_path, monkeypatch, capsys):
    from kultivait import cli
    import argparse

    p = make_config(tmp_path)
    monkeypatch.setattr(cli, "CONFIG_PATH", p)
    args = argparse.Namespace(model="kv-judge-x-g1", yes=True, config=str(p))
    # shadow log empty -> not ready; --yes overrides but the warning prints
    monkeypatch.setattr("kultivait.distill.shadow._default_log_path",
                        lambda: tmp_path / "shadow.jsonl")
    cli.cmd_cutover(args)
    out = capsys.readouterr().out
    assert "readiness" in out.lower() or "warning" in out.lower() or "not ready" in out.lower()
    # override still writes (the human confirmed explicitly)
    assert load_config(p).distill.model == "kv-judge-x-g1"


def test_rollback_is_instant_next_request(tmp_path):
    # reverting the knob restores the incumbent model in config
    p = make_config(tmp_path, model="kv-judge-x-g1")
    cfg = load_config(p)
    from dataclasses import replace
    cfg2 = replace(cfg, distill=DistillConfig(model="qwen3.5:4b"))
    save_config(cfg2, p)
    assert load_config(p).distill.model == "qwen3.5:4b"


# ---------------------------------------------------------------- shadow reporting


def test_shadow_command_reports_readiness(tmp_path, monkeypatch, capsys):
    from kultivait import cli
    import argparse
    from kultivait.distill.shadow import ShadowRecord, append_shadow_log

    log = tmp_path / "shadow.jsonl"
    for _ in range(30):
        append_shadow_log(ShadowRecord(
            ts=1.0, fingerprint="f", prompt_hash="h",
            incumbent={"model": "qwen3.5:4b", "verdict": "local", "max_fit": 0.3,
                       "latency_s": 1.0, "parse_ok": True},
            shadow={"model": "kv-judge-x-g1", "verdict": "local", "max_fit": 0.3,
                    "latency_s": 0.8, "parse_ok": True, "dangerous": False},
            agree=True,
        ), log)
    args = argparse.Namespace(log=str(log), json=True)
    cli.cmd_shadow(args)
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["n"] == 30 and data["agreement"] == 1.0
    assert data["cutover_ready"] is True
    assert "kv-judge-x-g1" in data["models"]["shadow"]


# ---------------------------------------------------------------- subcommand wiring


def test_distill_subcommands_registered():
    from kultivait import cli

    parser_required = []
    src = Path(cli.__file__).read_text()
    for token in ("corpus", "generate", "train", "export", "eval"):
        assert f'"{token}"' in src, f"distill {token} missing"
    for fn in ("cmd_distill_corpus", "cmd_distill_generate", "cmd_distill_train",
               "cmd_distill_export", "cmd_distill_eval", "cmd_cutover", "cmd_shadow"):
        assert fn in src, f"{fn} missing"


def test_cutover_cli_flag_wiring():
    import inspect
    from kultivait import cli

    src = inspect.getsource(cli.main)
    assert "cutover" in src and "--yes" in src


def test_help_smoke():
    r = subprocess.run(["uv", "run", "kultivait", "--help"],
                       capture_output=True, text=True, timeout=60,
                       cwd=Path(__file__).parent.parent)
    assert r.returncode == 0
    assert "distill" in r.stdout and "shadow" in r.stdout and "cutover" in r.stdout
