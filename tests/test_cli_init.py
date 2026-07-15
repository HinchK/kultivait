"""cmd_init's zero-to-local seam: offers are gated on TTY/flags/census, and
the survey no longer crashes on a bare machine. All probes monkeypatched."""

import argparse

import httpx
import pytest

import kultivait.cli as cli
from kultivait.hardware import HardwareProfile, SetupPlan

ELIGIBLE = SetupPlan(eligible=True, reason="Apple M3 with 24GB unified RAM")
INELIGIBLE = SetupPlan(eligible=False, reason="needs >=24GB unified RAM; this Mac has 16GB")
PROFILE = HardwareProfile("darwin", "Apple M3", True, 24.0)


@pytest.fixture
def offer_env(monkeypatch):
    """Baseline: interactive TTY, bare machine, eligible hardware."""
    monkeypatch.delenv("KULTIVAIT_RUNTIME", raising=False)
    monkeypatch.setattr(cli, "_stdin_is_tty", lambda: True)
    monkeypatch.setattr(cli.shutil, "which", lambda c: None)
    monkeypatch.setattr(cli.hardware, "scan", lambda: PROFILE)
    monkeypatch.setattr(cli.hardware, "plan", lambda p: ELIGIBLE)
    monkeypatch.setattr(cli.bootstrap, "ask", lambda p: True)
    return monkeypatch


def test_offer_setup_skipped_without_tty(offer_env):
    offer_env.setattr(cli, "_stdin_is_tty", lambda: False)
    offer_env.setattr(cli.hardware, "scan", lambda: 1 / 0)  # must not be reached
    assert cli._offer_setup() is None


def test_offer_setup_skipped_when_runtime_forced(offer_env):
    offer_env.setenv("KULTIVAIT_RUNTIME", "llamacpp")
    offer_env.setattr(cli.hardware, "scan", lambda: 1 / 0)  # must not be reached
    assert cli._offer_setup() is None


def test_offer_setup_defers_to_installed_ollama(offer_env, capsys):
    offer_env.setattr(
        cli.shutil, "which", lambda c: "/usr/local/bin/ollama" if c == "ollama" else None
    )
    assert cli._offer_setup() is None
    assert "ollama serve" in capsys.readouterr().out


def test_offer_setup_explains_ineligible(offer_env, capsys):
    offer_env.setattr(cli.hardware, "plan", lambda p: INELIGIBLE)
    assert cli._offer_setup() is None
    assert "16GB" in capsys.readouterr().out


def test_offer_setup_declined(offer_env):
    offer_env.setattr(cli.bootstrap, "ask", lambda p: False)
    offer_env.setattr(cli.bootstrap, "run", lambda *a, **k: 1 / 0)  # must not run
    assert cli._offer_setup() is None


def test_offer_setup_bootstraps_and_reports_llamacpp(offer_env):
    seen = {}

    def fake_run(plan, **kwargs):
        seen["plan"], seen["kwargs"] = plan, kwargs
        return "ok"

    offer_env.setattr(cli.bootstrap, "run", fake_run)
    assert cli._offer_setup() == "llamacpp"
    assert seen["plan"] is ELIGIBLE
    assert seen["kwargs"]["skip_install"] is False


def test_offer_setup_skips_install_when_llamacpp_present(offer_env):
    offer_env.setattr(
        cli.shutil, "which", lambda c: "/opt/homebrew/bin/llama-server" if c == "llama-server" else None
    )
    seen = {}

    def fake_run(plan, **kwargs):
        seen["kwargs"] = kwargs
        return "ok"

    offer_env.setattr(cli.bootstrap, "run", fake_run)
    assert cli._offer_setup() == "llamacpp"
    assert seen["kwargs"]["skip_install"] is True


def test_offer_setup_exits_when_server_fails(offer_env):
    offer_env.setattr(cli.bootstrap, "run", lambda *a, **k: "server_failed")
    with pytest.raises(SystemExit):
        cli._offer_setup()


def test_cmd_init_survives_bare_machine(monkeypatch, tmp_path, capsys):
    """No runtime anywhere: --no-setup init writes a virtual-tier config
    instead of crashing with a connection error."""
    monkeypatch.setattr(cli, "_running_runtime", lambda: None)
    monkeypatch.setattr(cli, "_available_clis", lambda: [])
    monkeypatch.delenv("KULTIVAIT_RUNTIME", raising=False)

    def refuse(runtime):
        raise httpx.ConnectError("nothing listening")

    monkeypatch.setattr(cli, "_survey_local", refuse)
    monkeypatch.setattr(cli, "CONFIG_PATH", tmp_path / "config.toml")
    cli.cmd_init(argparse.Namespace(no_setup=True))
    text = (tmp_path / "config.toml").read_text()
    assert 'kind = "virtual"' in text


def test_cmd_init_no_setup_never_offers(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "_running_runtime", lambda: None)
    monkeypatch.setattr(cli, "_offer_setup", lambda: 1 / 0)  # must not be reached
    monkeypatch.setattr(cli, "_available_clis", lambda: [])
    monkeypatch.delenv("KULTIVAIT_RUNTIME", raising=False)
    monkeypatch.setattr(cli, "_survey_local", lambda r: ([], {}))
    monkeypatch.setattr(cli, "CONFIG_PATH", tmp_path / "config.toml")
    cli.cmd_init(argparse.Namespace(no_setup=True))  # would ZeroDivisionError if offered
