"""Z2 (#120) tests: the shell integration — export, unset, check, shells."""

import argparse
import os
from unittest.mock import patch

import pytest

from kultivait.cli import cmd_hook
from kultivait.config import Config


def run_hook(shell="sh", unset=False, check=False, host="127.0.0.1", port=None):
    cmd_hook(argparse.Namespace(shell=shell, unset=unset, check=check,
                                host=host, port=port))


@pytest.fixture(autouse=True)
def config():
    with patch("kultivait.cli.get_config", return_value=Config(port=4114)):
        yield


# ---------------------------------------------------------------- export


def test_default_sh_export(capsys):
    run_hook()
    out = capsys.readouterr().out
    assert 'export OPENAI_BASE_URL="http://127.0.0.1:4114/v1"' in out
    assert 'export ANTHROPIC_BASE_URL="http://127.0.0.1:4114"' in out
    assert 'export OPENAI_API_KEY="kultivait"' in out
    assert 'export ANTHROPIC_API_KEY="kultivait"' in out


def test_fish_syntax(capsys):
    run_hook(shell="fish")
    out = capsys.readouterr().out
    assert 'set -gx OPENAI_BASE_URL' in out
    assert "fish" in out or "set -gx" in out  # the fish marker
    assert "export" not in out


def test_custom_port(capsys):
    run_hook(port=9999)
    out = capsys.readouterr().out
    assert ":9999/v1" in out


def test_zsh_same_as_sh(capsys):
    run_hook(shell="zsh")
    out = capsys.readouterr().out
    assert "export" in out  # zsh uses export too


# ---------------------------------------------------------------- unset


def test_unset_sh(capsys):
    run_hook(unset=True)
    out = capsys.readouterr().out
    assert "unset OPENAI_BASE_URL" in out
    assert "unset ANTHROPIC_BASE_URL" in out
    assert "unset OPENAI_API_KEY" in out
    assert "unset ANTHROPIC_API_KEY" in out


def test_unset_fish(capsys):
    run_hook(shell="fish", unset=True)
    out = capsys.readouterr().out
    assert "set -e OPENAI_BASE_URL" in out
    assert "export" not in out


def test_unset_overrides_export(capsys):
    """--unset wins over the default export mode."""
    run_hook(unset=True)
    out = capsys.readouterr().out
    assert "export" not in out


# ---------------------------------------------------------------- check


def test_check_reports_unset(capsys):
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("OPENAI_BASE_URL", None)
        os.environ.pop("ANTHROPIC_BASE_URL", None)
        run_hook(check=True)
    out = capsys.readouterr().out
    assert "hooked: no" in out


def test_check_reports_hooked(capsys):
    with patch.dict(os.environ, {
        "OPENAI_BASE_URL": "http://127.0.0.1:4114/v1",
        "ANTHROPIC_BASE_URL": "http://127.0.0.1:4114",
    }):
        run_hook(check=True)
    out = capsys.readouterr().out
    assert "hooked: yes" in out
