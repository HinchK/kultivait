"""Z1 (#119) tests: the process wrapper — env injection, exit codes, signals."""

import argparse
import os
import signal
import subprocess
import sys
from unittest.mock import patch

import pytest

from kultivait.cli import cmd_run
from kultivait.config import Config


def run_cmd(command, host="127.0.0.1", port=None):
    cmd_run(argparse.Namespace(command=command, host=host, port=port))


@pytest.fixture(autouse=True)
def config():
    with patch("kultivait.cli.get_config", return_value=Config(port=4114)):
        yield


# ---------------------------------------------------------------- env injection


class _FakeProc:
    returncode = 0
    def wait(self): return 0
    def send_signal(self, s): pass

def test_child_sees_proxy_env_vars():
    """The wrapper injects the right env vars into the child."""
    with patch("subprocess.Popen", return_value=_FakeProc()) as mock_popen:
        with pytest.raises(SystemExit):
            run_cmd(["env"])
    env = mock_popen.call_args[1]["env"]
    assert env["OPENAI_BASE_URL"] == "http://127.0.0.1:4114/v1"
    assert env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:4114"
    assert env["OPENAI_API_KEY"] == "kultivait"
    assert env["ANTHROPIC_API_KEY"] == "kultivait"


def test_custom_port_rides_the_vars():
    with patch("subprocess.Popen", return_value=_FakeProc()) as mock_popen:
        with pytest.raises(SystemExit):
            run_cmd(["env"], port=9999)
    env = mock_popen.call_args[1]["env"]
    assert ":9999/v1" in env["OPENAI_BASE_URL"]


def test_setdefault_preserves_user_key():
    """If OPENAI_API_KEY is already set, the wrapper doesn't overwrite it."""
    with patch.dict(os.environ, {"OPENAI_API_KEY": "my-key"}):
        with patch("subprocess.Popen", return_value=_FakeProc()) as mock_popen:
            with pytest.raises(SystemExit):
                run_cmd(["env"])
    env = mock_popen.call_args[1]["env"]
    assert env["OPENAI_API_KEY"] == "my-key"


# ---------------------------------------------------------------- exit codes


def test_child_exit_code_forwarded(capsys):
    with pytest.raises(SystemExit) as exc_info:
        run_cmd(["echo", "out"])
    assert exc_info.value.code == 0


def test_nonzero_exit_code_forwarded():
    with pytest.raises(SystemExit) as exc_info:
        run_cmd(["false"])
    assert exc_info.value.code == 1


def test_command_not_found():
    with pytest.raises(SystemExit) as exc_info:
        run_cmd(["__nonexistent_cmd__"])
    assert exc_info.value.code == 127


# ---------------------------------------------------------------- PROXY_ENV_STRIP


def test_proxy_env_strip_invariant():
    """kultivait's own CLI dispatches strip these vars — the recursion guard.
    Verify PROXY_ENV_STRIP contains our injected vars."""
    from kultivait.backends import PROXY_ENV_STRIP
    assert "OPENAI_BASE_URL" in PROXY_ENV_STRIP
    assert "ANTHROPIC_BASE_URL" in PROXY_ENV_STRIP
