"""V5 (#110) tests: the dashboard launcher — health check, URL, browser."""

import argparse
from unittest.mock import patch

import pytest

from kultivait.cli import cmd_dashboard
from kultivait.config import Config


def run_cmd(port=4114, host="127.0.0.1", no_open=False):
    cmd_dashboard(argparse.Namespace(port=port, host=host, no_open=no_open))


@pytest.fixture(autouse=True)
def config():
    with patch("kultivait.cli.get_config", return_value=Config(port=4114)):
        yield


# ---------------------------------------------------------------- URL + health


def test_url_construction(capsys):
    import httpx
    import webbrowser
    ok = type("R", (), {"status_code": 200})()
    with patch.object(httpx, "get", return_value=ok):
        with patch.object(webbrowser, "open") as mock_open:
            run_cmd(port=9999)
    assert mock_open.called
    assert mock_open.call_args[0][0] == "http://127.0.0.1:9999/dashboard"


def test_no_open_prints_url_without_browser(capsys):
    import httpx
    import webbrowser
    ok = type("R", (), {"status_code": 200})()
    with patch.object(httpx, "get", return_value=ok):
        with patch.object(webbrowser, "open") as mock_open:
            run_cmd(no_open=True)
    assert not mock_open.called
    out = capsys.readouterr().out
    assert "dashboard:" in out and "/dashboard" in out


def test_health_check_failure_does_not_open_browser(capsys):
    import httpx
    import webbrowser
    with patch.object(httpx, "get", side_effect=ConnectionError("no serve")):
        with patch("subprocess.Popen") as mock_popen:
            mock_popen.return_value = type("P", (), {"pid": 123})()
            with patch("time.sleep"):
                with patch.object(webbrowser, "open") as mock_open:
                    run_cmd()
    assert not mock_open.called
    assert "serve did not come up" in capsys.readouterr().err


# ---------------------------------------------------------------- defaults


def test_port_defaults_to_config(capsys):
    import httpx
    import webbrowser
    calls = []
    def fake_get(url, **kw):
        calls.append(url)
        return type("R", (), {"status_code": 200})()
    with patch.object(httpx, "get", side_effect=fake_get):
        with patch.object(webbrowser, "open") as mock_open:
            run_cmd(port=None)
    assert any(":4114/" in u for u in calls)
    assert ":4114/dashboard" in mock_open.call_args[0][0]


def test_custom_host_used(capsys):
    import httpx
    import webbrowser
    ok = type("R", (), {"status_code": 200})()
    with patch.object(httpx, "get", return_value=ok):
        with patch.object(webbrowser, "open") as mock_open:
            run_cmd(host="0.0.0.0", port=8080)
    assert mock_open.call_args[0][0] == "http://0.0.0.0:8080/dashboard"
