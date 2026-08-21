"""cmd_init routing: TTY first-runs (or --setup) go through the setup
screen; --no-setup and non-TTY keep today's linear survey path. All probes
monkeypatched — no terminal, no runtimes, no real home dir."""

import argparse

import httpx

import kultivait.cli as cli
from kultivait import onboarding


def _linear_env(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "_running_runtime", lambda: None)
    monkeypatch.setattr(cli, "_available_clis", lambda: [])
    monkeypatch.delenv("KULTIVAIT_RUNTIME", raising=False)
    monkeypatch.setattr(cli, "CONFIG_PATH", tmp_path / "config.toml")


def test_cmd_init_survives_bare_machine(monkeypatch, tmp_path):
    """No runtime anywhere: --no-setup init writes a virtual-tier config
    instead of crashing with a connection error."""
    _linear_env(monkeypatch, tmp_path)

    def refuse(runtime):
        raise httpx.ConnectError("nothing listening")

    monkeypatch.setattr(cli, "_survey_local", refuse)
    cli.cmd_init(argparse.Namespace(no_setup=True, setup=False))
    assert 'kind = "virtual"' in (tmp_path / "config.toml").read_text()


def test_cmd_init_no_setup_never_opens_screen(monkeypatch, tmp_path):
    _linear_env(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_stdin_is_tty", lambda: True)  # TTY, but opted out
    monkeypatch.setattr(cli, "_run_setup_screen", lambda first_run: 1 / 0)
    monkeypatch.setattr(cli, "_survey_local", lambda r: ([], {}))
    cli.cmd_init(argparse.Namespace(no_setup=True, setup=False))  # ZeroDivision if routed


def test_cmd_init_non_tty_stays_linear_even_on_first_run(monkeypatch, tmp_path):
    _linear_env(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_stdin_is_tty", lambda: False)
    monkeypatch.setattr(cli, "_run_setup_screen", lambda first_run: 1 / 0)
    monkeypatch.setattr(cli, "_survey_local", lambda r: ([], {}))
    monkeypatch.setattr(cli.onboarding, "ONBOARDING_PATH", tmp_path / "onboarding.json")
    cli.cmd_init(argparse.Namespace(no_setup=False, setup=False))
    assert (tmp_path / "config.toml").exists()
    assert not (tmp_path / "onboarding.json").exists()  # linear path never marks


def _routing_env(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "_stdin_is_tty", lambda: True)
    monkeypatch.setattr(cli.onboarding, "ONBOARDING_PATH", tmp_path / "onboarding.json")
    monkeypatch.setattr(cli, "CONFIG_PATH", tmp_path / "config.toml")
    monkeypatch.setattr(cli, "_survey_local", lambda r: ([], {}))
    monkeypatch.setattr(cli, "_available_clis", lambda: [])
    monkeypatch.setattr(cli, "_detect_runtime", lambda: "ollama")
    monkeypatch.delenv("KULTIVAIT_RUNTIME", raising=False)


def _fake_screen(monkeypatch, exit, runtime=None, seen=None):
    """Patch the module boundary: routing tests exercise what cmd_init does
    with an outcome, not the screen itself (its suite covers that)."""
    def fake(first_run):
        if seen is not None:
            seen["first_run"] = first_run
        return cli.setup_screen.SetupOutcome(exit=exit, runtime=runtime)

    monkeypatch.setattr(cli, "_run_setup_screen", fake)


import re

def strip_ansi(text: str) -> str:
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)


def test_first_run_routes_to_screen_and_skip_writes_marker(monkeypatch, tmp_path, capsys):
    _routing_env(monkeypatch, tmp_path)
    _fake_screen(monkeypatch, "skipped")
    cli.cmd_init(argparse.Namespace(no_setup=False, setup=False))
    marker = (tmp_path / "onboarding.json").read_text()
    assert '"completed": true' in marker
    assert '"skipped": true' in marker
    assert (tmp_path / "config.toml").exists()  # skip still writes a virtual-tier config
    out = strip_ansi(capsys.readouterr().out)
    assert "re-run kultivait init anytime" in out


def test_completed_outcome_writes_unskipped_marker(monkeypatch, tmp_path):
    _routing_env(monkeypatch, tmp_path)
    _fake_screen(monkeypatch, "completed", runtime="llamacpp")
    cli.cmd_init(argparse.Namespace(no_setup=False, setup=False))
    assert '"skipped": false' in (tmp_path / "onboarding.json").read_text()
    assert (tmp_path / "config.toml").exists()


def test_closed_re_run_writes_nothing(monkeypatch, tmp_path):
    _routing_env(monkeypatch, tmp_path)
    _fake_screen(monkeypatch, "closed")
    cli.cmd_init(argparse.Namespace(no_setup=False, setup=False))
    assert not (tmp_path / "onboarding.json").exists()
    assert not (tmp_path / "config.toml").exists()


def test_setup_flag_reopens_screen_when_marker_complete(monkeypatch, tmp_path):
    onboarding.complete(path=tmp_path / "onboarding.json")
    _routing_env(monkeypatch, tmp_path)
    seen = {}
    _fake_screen(monkeypatch, "completed", runtime="llamacpp", seen=seen)
    cli.cmd_init(argparse.Namespace(no_setup=False, setup=True))
    assert seen["first_run"] is False
    assert (tmp_path / "config.toml").exists()
    # marker-complete re-runs never rewrite the marker
    assert '"skipped": false' in (tmp_path / "onboarding.json").read_text()
