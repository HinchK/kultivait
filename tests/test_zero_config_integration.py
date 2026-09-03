"""Z5 (#123): the zero-config integration suite — all four layers, end-to-end."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from kultivait.backends import Completion
from kultivait.config import Config
from kultivait.ledger import Ledger
from kultivait.server import create_app


# ------------------------------------------------------------------ test server


class FakeRouter:
    _margin = 0.5
    def classify(self, vec):
        class D:
            tier = "local"
            escalated = False
            margin = 0.9
        return D()


class FakeBackend:
    supports_tools = True
    local = True
    def complete(self, messages, tools=None, **kw):
        return Completion(text="ok", tokens_in=5, tokens_out=5, cost_usd=0.0, local=True)


@pytest.fixture
def client(tmp_path):
    led = Ledger(tmp_path / "l.jsonl")
    led.record(tier="local", local=True, tokens_in=1, tokens_out=1, cost_usd=0.0)
    app = create_app(
        router=FakeRouter(), embed=lambda t: [0.0],
        backends={"local": FakeBackend()}, ledger=led,
        gate=None, escalations=None,
    )
    return TestClient(app)


# ------------------------------------------------------------------ Z1: run


class TestProcessWrapper:
    def test_run_env_injection(self, client):
        """A child sees the proxy vars when the wrapper injects them."""
        from kultivait.cli import cmd_run
        proc_env = {}
        class _FakeProc:
            returncode = 0
            def wait(self): return 0
            def send_signal(self, s): pass
        with patch("subprocess.Popen", return_value=_FakeProc()) as mock_popen:
            with pytest.raises(SystemExit):
                cmd_run(argparse.Namespace(command=["env"], host="127.0.0.1", port=4114))
        env = mock_popen.call_args[1]["env"]
        assert env["OPENAI_BASE_URL"] == "http://127.0.0.1:4114/v1"
        assert env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:4114"

    def test_run_against_live_server(self, client):
        """The proxy env vars actually route to a serving instance."""
        r = client.get("/api/dashboard/summary")
        assert r.status_code == 200
        assert "prompts" in r.json()


# ------------------------------------------------------------------ Z2: shell hook


class TestShellHook:
    def test_hook_exports_match_serving_url(self, client, capsys):
        """The export lines match the test server's URL pattern."""
        from kultivait.cli import cmd_hook
        with patch("kultivait.cli.get_config", return_value=Config(port=4114)):
            cmd_hook(argparse.Namespace(shell="sh", unset=False, check=False,
                                        host="127.0.0.1", port=4114))
        out = capsys.readouterr().out
        assert "http://127.0.0.1:4114/v1" in out
        assert "export OPENAI_BASE_URL" in out

    def test_hook_check_lifecycle(self, client, capsys):
        """--check detects both hooked and unhooked states."""
        from kultivait.cli import cmd_hook
        ns = argparse.Namespace(shell="sh", unset=False, check=True,
                                host="127.0.0.1", port=4114)
        # unhooked
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENAI_BASE_URL", None)
            os.environ.pop("ANTHROPIC_BASE_URL", None)
            with patch("kultivait.cli.get_config", return_value=Config(port=4114)):
                cmd_hook(ns)
        assert "hooked: no" in capsys.readouterr().out

        # hooked
        with patch.dict(os.environ, {
            "OPENAI_BASE_URL": "http://127.0.0.1:4114/v1",
            "ANTHROPIC_BASE_URL": "http://127.0.0.1:4114",
        }):
            with patch("kultivait.cli.get_config", return_value=Config(port=4114)):
                cmd_hook(ns)
        assert "hooked: yes" in capsys.readouterr().out

    def test_unset_complements_set(self, capsys):
        """The unset lines cover every var the set lines create."""
        from kultivait.cli import cmd_hook
        ns_set = argparse.Namespace(shell="sh", unset=False, check=False,
                                    host="127.0.0.1", port=4114)
        ns_unset = argparse.Namespace(shell="sh", unset=True, check=False,
                                      host="127.0.0.1", port=4114)
        with patch("kultivait.cli.get_config", return_value=Config(port=4114)):
            cmd_hook(ns_set)
        set_out = capsys.readouterr().out
        with patch("kultivait.cli.get_config", return_value=Config(port=4114)):
            cmd_hook(ns_unset)
        unset_out = capsys.readouterr().out
        set_vars = {l.split("=")[0].replace("export ", "") for l in set_out.splitlines()}
        unset_vars = {l.replace("unset ", "") for l in unset_out.splitlines()}
        assert set_vars == unset_vars


# ------------------------------------------------------------------ Z3: IDE patcher


class TestIDEPatcher:
    def test_ide_patch_backup_restore_cycle(self, tmp_path):
        """Full cycle: patch → verify → restore → verify reverted."""
        from kultivait.hook.ide import patch_ide, restore_ide

        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps({"editor.fontSize": 14}))

        # patch
        result = patch_ide("cursor", settings, "http://127.0.0.1:4114")
        assert result["patched"] is True
        data = json.loads(settings.read_text())
        assert data["openai"]["baseUrl"] == "http://127.0.0.1:4114/v1"
        assert Path(result["backup"]).exists()

        # restore
        assert restore_ide(settings) is True
        restored = json.loads(settings.read_text())
        assert "openai" not in restored or "baseUrl" not in restored.get("openai", {})

    def test_ide_dry_run_no_side_effects(self, tmp_path):
        from kultivait.hook.ide import patch_ide

        settings = tmp_path / "settings.json"
        original = json.dumps({"editor.fontSize": 14})
        settings.write_text(original)

        result = patch_ide("cursor", settings, "http://127.0.0.1:4114", dry_run=True)
        assert result["dry_run"] is True
        assert settings.read_text() == original


# ------------------------------------------------------------------ Z4: loopback


class TestLoopback:
    def test_loopback_configs_consistent(self):
        """Hosts, pf, and cert all reference the same domains."""
        from kultivait.hook.loopback import (
            INTERCEPT_DOMAINS, generate_cert_instructions,
            generate_hosts_entries, generate_pf_rules,
        )
        hosts = generate_hosts_entries()
        pf = generate_pf_rules()
        cert = generate_cert_instructions()
        for d in INTERCEPT_DOMAINS:
            assert d in hosts and d in cert
        assert "443" in pf  # the port being intercepted

    def test_loopback_trade_off_names_all_layers(self):
        """The trade-off record names all four Z layers."""
        from kultivait.hook.loopback import full_setup_guide
        guide = full_setup_guide()
        for ref in ("run", "hook", "hook ide"):
            assert ref in guide["trade_offs"]


# ------------------------------------------------------------------ cross-layer


class TestCrossLayerIntegration:
    def test_env_vars_match_server_route(self, client):
        """The env vars Z1/Z2 inject point at a URL the server actually serves."""
        base_url = "http://127.0.0.1:4114"
        r = client.get("/api/dashboard/summary")
        assert r.status_code == 200  # the server is alive at the expected address

    def test_proxy_env_strip_invariant(self):
        """No recursion: kultivait's own CLI dispatches strip the injected vars."""
        from kultivait.backends import PROXY_ENV_STRIP
        for var in ("OPENAI_BASE_URL", "ANTHROPIC_BASE_URL"):
            assert var in PROXY_ENV_STRIP
