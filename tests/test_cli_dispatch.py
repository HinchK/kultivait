"""CLI dispatch tests: bare group invocations (`kultivait shadow`, `kultivait
distill`) must reach a handler with a fully-populated namespace instead of
raising AttributeError out of `main()`.

Handlers are stubbed throughout — a real `cmd_shadow` with `log=None` reads the
operator's live ~/.kultivait/shadow.jsonl.
"""

import argparse

import pytest

from kultivait import cli


@pytest.fixture
def dispatched(monkeypatch):
    """Stub every command handler; return the (name, namespace) that ran."""
    seen: dict = {}

    def spy(name):
        def handler(args: argparse.Namespace) -> None:
            seen["func"] = name
            seen["args"] = args
        return handler

    for name in ("cmd_shadow", "cmd_shadow_probe", "cmd_distill_corpus",
                 "cmd_distill_status"):
        monkeypatch.setattr(cli, name, spy(name))
    return seen


# ---------------------------------------------------------------- shadow


def test_bare_shadow_dispatches_with_read_defaults(dispatched):
    """The crash repro: bare `shadow` reached cmd_shadow without args.log."""
    cli.main(["shadow"])
    assert dispatched["func"] == "cmd_shadow"
    assert dispatched["args"].log is None
    assert dispatched["args"].json is False


def test_bare_shadow_accepts_log_flag(dispatched, tmp_path):
    """README documents `kultivait shadow [--log <path>]` — the bare form must
    parse the flag, not merely default it."""
    log = tmp_path / "shadow.jsonl"
    cli.main(["shadow", "--log", str(log)])
    assert dispatched["func"] == "cmd_shadow"
    assert dispatched["args"].log == str(log)


def test_bare_shadow_accepts_json_flag(dispatched):
    cli.main(["shadow", "--json"])
    assert dispatched["args"].json is True


def test_shadow_read_subcommand_still_works(dispatched, tmp_path):
    log = tmp_path / "shadow.jsonl"
    cli.main(["shadow", "read", "--log", str(log), "--json"])
    assert dispatched["func"] == "cmd_shadow"
    assert dispatched["args"].log == str(log)
    assert dispatched["args"].json is True


def test_shadow_probe_subcommand_still_works(dispatched):
    """The parent's func default must not shadow a subcommand's handler."""
    cli.main(["shadow", "probe", "--band", "simple", "--n", "3"])
    assert dispatched["func"] == "cmd_shadow_probe"
    assert dispatched["args"].band == "simple"
    assert dispatched["args"].n == 3


# ---------------------------------------------------------------- distill


def test_bare_distill_prints_help_and_exits_nonzero(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["distill"])
    assert exc.value.code == 2
    out = capsys.readouterr().out
    for token in ("corpus", "generate", "train", "export", "eval"):
        assert token in out, f"distill help omits {token}"


def test_distill_subcommand_still_dispatches(dispatched, tmp_path):
    cli.main(["distill", "corpus", "--dry-run", "--harvest-dir", str(tmp_path)])
    assert dispatched["func"] == "cmd_distill_corpus"
    assert dispatched["args"].dry_run is True


def test_distill_status_subcommand_still_dispatches(dispatched):
    cli.main(["distill", "status", "--json"])
    assert dispatched["func"] == "cmd_distill_status"
    assert dispatched["args"].json is True


# ---------------------------------------------------------------- audit


@pytest.mark.parametrize("group", ["shadow", "distill"])
def test_every_group_parser_handles_a_bare_invocation(group, dispatched):
    """Both group parsers must resolve bare invocations — either to a default
    handler (shadow -> read) or to help + exit (distill). Neither may raise
    AttributeError over a missing `func` or a missing subcommand flag.
    """
    try:
        cli.main([group])
    except SystemExit as exc:
        assert exc.code != 0, f"bare `{group}` should exit non-zero"
    except AttributeError as exc:  # pragma: no cover - the regression itself
        pytest.fail(f"bare `kultivait {group}` raised AttributeError: {exc}")
