"""#198: the setup screen redraws in place during a model download.

Two regression mechanisms, both observed live under a pseudo-terminal:

1. Frame fairness — a progress-event storm (5 ms cadence, ~40x production)
   used to starve ``live.update`` inside the quiesce loop, freezing the
   panel for the whole download (one painted frame per run). The fix paints
   at the Live's own ~10 fps cadence even mid-storm.
2. Subprocess capture — ``brew install llama.cpp`` runs with capture_output
   so its progress can never interleave with the Live region, and the
   brew-missing hint routes through an injected sink, never the console.
"""

import os
import pty
import re
import threading
import time
from types import SimpleNamespace

import rich.console

from kultivait import bootstrap, setup_screen, setup_state
from kultivait.hardware import (
    HardwareProfile, SetupPlan, QWEN3_4B, QWEN3_14B, EMBED_PICK,
)

TERM_W, TERM_H = 100, 30
PROFILE = HardwareProfile("darwin", "Apple M3 Pro", True, 36.0)
PLAN = SetupPlan(
    eligible=True,
    reason="36 GB unified · Apple Silicon",
    models=(QWEN3_4B, QWEN3_14B, EMBED_PICK),
    ctx=32768,
    server_flags=(),
    default_gpu_cap_mb=24576,
    wired_limit_mb=None,
)


class ChooserKeys:
    """KeyReader stand-in: "enter" lands only after prepare() completed, so
    it always selects from the chooser phase."""

    def __init__(self, prep_done: threading.Event, delay: float = 0.1):
        self._prep_done = prep_done
        self._delay = delay
        self._sent = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def poll(self, timeout: float):
        if not self._prep_done.is_set():
            time.sleep(min(timeout, 0.05))
            return None
        if not self._sent:
            time.sleep(self._delay)
            self._sent = True
            return "enter"
        time.sleep(min(timeout, 0.05))
        return None


class StormDriver:
    """Streams download progress at 5 ms cadence — 40x production — to
    reproduce the quiesce starvation that froze the panel."""

    def __init__(self):
        self.prep_done = threading.Event()

    def prepare(self, emit):
        for sid, _ in setup_state.PREP_STEPS:
            emit(sid, "done")
        prep = setup_state.Preparation(
            runtime=None, models=(), sizes={}, clis=(), plan=PLAN,
            profile=PROFILE, have_llamacpp=True, have_brew=True,
            have_ollama=False,
        )
        self.prep_done.set()
        return prep

    def download(self, single, post, stop):
        total, steps = 9_001_752_960, 150
        done = 0
        for _ in range(steps):
            done += total // steps
            post(("progress", min(done, total), total))
            time.sleep(0.005)
        post(("op_done", "download", True, ""))

    def start_server(self, wired, post):
        post(("op_done", "start", True, ""))

    def switch_to_ollama(self, post):
        post(("op_done", "switch", False, "n/a"))


class TinyScreen:
    """Minimal VT100 model: rows grow when the cursor passes the bottom —
    stacked panel copies would exceed the terminal height."""

    def __init__(self, width, height):
        self.rows = ["" for _ in range(height)]
        self.r = self.c = 0

    def _ensure(self):
        while self.r >= len(self.rows):
            self.rows.append("")

    def feed(self, data: str):
        i = 0
        while i < len(data):
            ch = data[i]
            if ch == "\x1b" and i + 1 < len(data) and data[i + 1] == "[":
                m = re.match(r"\x1b\[([0-9;]*)([A-Za-zJK])", data[i:])
                if m:
                    params, cmd = m.group(1), m.group(2)
                    n = int(params) if params.isdigit() else 1
                    if cmd == "A":
                        self.r = max(0, self.r - n)
                    elif cmd == "B":
                        self.r += n
                        self._ensure()
                    elif cmd == "C":
                        self.c += n
                    elif cmd == "D":
                        self.c = max(0, self.c - n)
                    elif cmd == "K":
                        mode = int(params) if params else 0
                        row = self.rows[self.r]
                        if mode == 0:
                            self.rows[self.r] = row[: self.c]
                        elif mode == 1:
                            self.rows[self.r] = " " * self.c + row[self.c:]
                        else:
                            self.rows[self.r] = ""
                    elif cmd == "J":
                        if (params or "0") == "0":
                            self.rows[self.r] = self.rows[self.r][: self.c]
                            del self.rows[self.r + 1:]
                    i += m.end()
                    continue
            if ch == "\r":
                self.c = 0
            elif ch == "\n":
                self.r += 1
                self._ensure()
            else:
                self._ensure()
                row = self.rows[self.r]
                if len(row) < self.c:
                    row += " " * (self.c - len(row))
                self.rows[self.r] = row[: self.c] + ch + row[self.c + 1:]
                self.c += 1
            i += 1


def _run_under_pty(driver, keys):
    """Real run_setup (threads + Rich Live) under a pseudo-terminal; returns
    (outcome, decoded stream). Cleanup closes the slave before the master —
    macOS blocks master-close while the slave is open (#198 harness hang)."""
    master, slave = pty.openpty()
    outfile = os.fdopen(slave, "w")
    console = rich.console.Console(
        file=outfile, force_terminal=True, width=TERM_W, height=TERM_H,
        legacy_windows=False,
    )
    captured = bytearray()
    stop_cap = threading.Event()

    def reader():
        while not stop_cap.is_set():
            try:
                chunk = os.read(master, 65536)
            except OSError:
                break
            if not chunk:
                break
            captured.extend(chunk)

    rt = threading.Thread(target=reader, daemon=True)
    rt.start()
    try:
        outcome = setup_screen.run_setup(
            driver=driver, keys=keys, first_run=True, console=console,
        )
        time.sleep(0.2)  # let the tail drain
    finally:
        stop_cap.set()
        try:
            outfile.close()  # slave first
        except OSError:
            pass
        try:
            os.close(master)
        except OSError:
            pass
        rt.join(timeout=2)
    return outcome, captured.decode("utf-8", errors="replace")


def test_progress_storm_keeps_redrawing_in_place():
    driver = StormDriver()
    outcome, data = _run_under_pty(driver, ChooserKeys(driver.prep_done))
    assert outcome.exit == "completed"
    # the download ran and its frames PAINTED: many distinct in-place
    # redraws, not one frozen frame for the whole run (#198)
    assert data.count("Downloading") > 3
    # in-place redraws ride cursor-up sequences; stacked copies would push
    # newlines and grow past the 30-row terminal instead
    cursor_ups = len(re.findall(r"\x1b\[\d*A", data))
    assert cursor_ups >= 3
    screen = TinyScreen(TERM_W, TERM_H)
    screen.feed(data)
    assert len(screen.rows) <= TERM_H + 2  # no stacked panel copies


def test_brew_output_is_captured_not_inherited():
    calls = {}

    def run_cmd(cmd, **kw):
        calls["cmd"] = cmd
        calls["kw"] = kw
        return SimpleNamespace(returncode=0)

    which = lambda c: "/opt/homebrew/bin/brew" if c == "brew" else None
    state = bootstrap.ensure_llamacpp(
        confirm=lambda p: True, run_cmd=run_cmd, which=which
    )
    assert state == "installed"
    assert calls["cmd"] == ["brew", "install", "llama.cpp"]
    assert calls["kw"].get("capture_output") is True  # never hits the tty


def test_brew_missing_hint_routes_through_sink_not_console(capsys):
    hints = []
    which = lambda c: None  # no llama-server, no brew
    state = bootstrap.ensure_llamacpp(
        confirm=lambda p: True,
        run_cmd=lambda *a, **k: None,
        which=which,
        hint=hints.append,
    )
    assert state == "advisory"
    assert len(hints) == 1 and "brew" in hints[0].lower()
    assert capsys.readouterr().out == ""  # nothing on the raw console
