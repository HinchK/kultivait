"""keys: ANSI bytes -> normalized key names; KeyReader always restores the
terminal; ScriptedKeys drives the screen loop deterministically in tests."""

import pytest

from kultivait.keys import KeyReader, ScriptedKeys, parse_key


def test_parse_key_csi_and_plain():
    assert parse_key(b"\x1b[A") == "up"
    assert parse_key(b"\x1b[B") == "down"
    assert parse_key(b"\x1b[C") == "right"
    assert parse_key(b"\x1b[D") == "left"
    assert parse_key(b"\r") == "enter"
    assert parse_key(b"\n") == "enter"
    assert parse_key(b"\x1b") == "esc"
    assert parse_key(b"\x03") == "ctrl-c"
    assert parse_key(b"j") == "j"
    assert parse_key(b"Q") == "q"
    assert parse_key(b"\x1b[200~") == "other"


class _FakeTermios:
    TCSANOW = 0

    def __init__(self):
        self.calls = []

    def tcgetattr(self, fd):
        return ("saved",)

    def tcsetattr(self, fd, when, attrs):
        self.calls.append(("restore", attrs))


class _FakeTty:
    def __init__(self):
        self.calls = []

    def setcbreak(self, fd, when):
        self.calls.append(("cbreak", fd))


def test_key_reader_restores_terminal_even_on_error():
    """cbreak must be undone in __exit__ even on a crash mid-setup — a
    half-configured terminal (no echo) is worse than the crash itself."""
    termios_mod, tty_mod = _FakeTermios(), _FakeTty()
    reader = KeyReader(stdin_fd=0, termios_mod=termios_mod, tty_mod=tty_mod)
    with pytest.raises(RuntimeError):
        with reader:
            assert ("cbreak", 0) in tty_mod.calls
            raise RuntimeError("boom")
    assert ("restore", ("saved",)) in termios_mod.calls


def test_key_reader_restores_on_clean_exit():
    termios_mod = _FakeTermios()
    with KeyReader(stdin_fd=0, termios_mod=termios_mod, tty_mod=_FakeTty()):
        pass
    assert ("restore", ("saved",)) in termios_mod.calls


def test_scripted_keys_yields_then_none():
    sk = ScriptedKeys(["down", "enter"])
    assert sk.poll(0) == "down"
    assert sk.poll(0) == "enter"
    assert sk.poll(0) is None


def test_scripted_keys_wait_yields_one_none():
    """The "wait" pseudo-key stands in for human reaction time: one empty
    poll so pending async events can land before the next real key."""
    sk = ScriptedKeys(["wait", "r"])
    assert sk.poll(0) is None
    assert sk.poll(0) == "r"
