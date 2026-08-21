"""Raw single-key input for the setup screen: termios cbreak + ANSI CSI
parsing. The screen loop polls; nothing blocks. ScriptedKeys is the
deterministic stand-in used by setup_screen tests."""

import os
import select
import sys
import termios
import tty
from collections import deque

_CSI = {"A": "up", "B": "down", "C": "right", "D": "left"}


def parse_key(data: bytes) -> str:
    if data in (b"\r", b"\n"):
        return "enter"
    if data == b"\x03":
        return "ctrl-c"
    if data == b"\x1b":
        return "esc"
    if len(data) >= 3 and data[:2] == b"\x1b[":
        return _CSI.get(chr(data[2]), "other")
    if len(data) == 1:
        ch = chr(data[0])
        return ch.lower() if ch.isalnum() else "other"
    return "other"


class KeyReader:
    """cbreak context manager over a stdin fd; poll(timeout) returns one
    normalized key or None. The saved terminal attributes are restored in
    __exit__ no matter how the block exits."""

    def __init__(self, stdin_fd=None, termios_mod=termios, tty_mod=tty):
        self.stdin_fd = stdin_fd if stdin_fd is not None else sys.stdin.fileno()
        self._termios = termios_mod
        self._tty = tty_mod
        self._saved = None

    def __enter__(self):
        self._saved = self._termios.tcgetattr(self.stdin_fd)
        self._tty.setcbreak(self.stdin_fd, self._termios.TCSANOW)
        return self

    def __exit__(self, *exc):
        self._termios.tcsetattr(self.stdin_fd, self._termios.TCSANOW, self._saved)
        return False

    def poll(self, timeout: float) -> "str | None":
        ready, _, _ = select.select([self.stdin_fd], [], [], timeout)
        if not ready:
            return None
        return parse_key(os.read(self.stdin_fd, 8))


class ScriptedKeys:
    """Same shape as KeyReader; poll pops the next scripted key. The
    reserved pseudo-key "wait" yields one None poll — use it before a key
    whose effect depends on an async operation's result event landing."""

    def __init__(self, events):
        self._events = deque(events)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def poll(self, timeout: float) -> "str | None":
        if self._events and self._events[0] == "wait":
            self._events.popleft()
            return None
        return self._events.popleft() if self._events else None
