"""Z4 (#122) tests: loopback redirection generators — config, pf, cert, revert."""

import argparse
from unittest.mock import patch

import pytest

from kultivait.cli import cmd_hook_loopback
from kultivait.config import Config
from kultivait.hook.loopback import (
    INTERCEPT_DOMAINS,
    LOOPBACK,
    full_setup_guide,
    generate_cert_instructions,
    generate_hosts_entries,
    generate_pf_rules,
    generate_uninstall,
)


def run_cmd(**kw):
    cmd_hook_loopback(argparse.Namespace(
        generate_hosts=kw.get("generate_hosts", False),
        generate_pf=kw.get("generate_pf", False),
        generate_cert=kw.get("generate_cert", False),
        generate_uninstall=kw.get("generate_uninstall", False),
        port=kw.get("port"),
    ))


@pytest.fixture(autouse=True)
def config():
    with patch("kultivait.cli.get_config", return_value=Config(port=4114)):
        yield


# ---------------------------------------------------------------- hosts


def test_hosts_entries_cover_both_apis():
    entries = generate_hosts_entries()
    for d in INTERCEPT_DOMAINS:
        assert f"{LOOPBACK} {d}" in entries


def test_hosts_has_kultivait_markers():
    entries = generate_hosts_entries()
    assert "kultivait" in entries  # the marker (for removal)
    assert "---" in entries  # the delimiters


# ---------------------------------------------------------------- pf rules


def test_pf_rules_redirect_443():
    rules = generate_pf_rules(port=8443)
    assert "rdr pass on lo0" in rules
    assert "port 443" in rules  # the intercepted port
    assert "port 8443" in rules  # the redirect target


def test_pf_rules_kultivait_marked():
    rules = generate_pf_rules()
    assert "kultivait" in rules


# ---------------------------------------------------------------- cert


def test_cert_instructions_cover_domains():
    cert = generate_cert_instructions()
    for d in INTERCEPT_DOMAINS:
        assert d in cert
    assert "subjectAltName" in cert
    assert "security add-trusted-cert" in cert  # the trust command


# ---------------------------------------------------------------- uninstall


def test_uninstall_covers_all_steps():
    un = generate_uninstall()
    assert "/etc/hosts" in un
    assert "pf.anchors" in un
    assert "delete-certificate" in un


# ---------------------------------------------------------------- full guide


def test_full_guide_contains_all_sections():
    guide = full_setup_guide(port=4114)
    for key in ("hosts", "pf_rules", "cert_instructions", "uninstall", "trade_offs"):
        assert key in guide
    assert "zero-root standard" in guide["trade_offs"]
    assert "TLS MITM" in guide["trade_offs"]


def test_full_guide_trade_off_explains_hierarchy():
    """The trade-off record explains WHY app-level is the standard."""
    guide = full_setup_guide()
    assert "run" in guide["trade_offs"]  # references Z1
    assert "hook" in guide["trade_offs"]  # references Z2/Z3


# ---------------------------------------------------------------- CLI


def test_cli_generate_hosts(capsys):
    run_cmd(generate_hosts=True)
    out = capsys.readouterr().out
    assert f"{LOOPBACK} api.anthropic.com" in out
    assert "kultivait" in out


def test_cli_generate_pf(capsys):
    run_cmd(generate_pf=True)
    out = capsys.readouterr().out
    assert "rdr pass" in out


def test_cli_full_guide(capsys):
    run_cmd()
    out = capsys.readouterr().out
    assert "hosts" in out.lower() or "127.0.0.1" in out
    assert "trade_offs" in out or "zero-root" in out


# ---------------------------------------------------------------- safety


def test_no_root_execution():
    """The generators produce text; they never modify system files."""
    # verify the module has no subprocess/os.system/sudo calls
    import inspect
    from kultivait.hook import loopback
    source = inspect.getsource(loopback)
    assert "subprocess" not in source
    assert "os.system" not in source
    # sudo appears only in instruction strings, never in code execution
