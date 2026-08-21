# Magnitude-Parity Setup Screen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild `kultivait init` as magnitude's setup screen: Preparation checklist → keyboard Chooser → download with cancel-confirm → server start with retry → Closing that writes config + onboarding marker.

**Architecture:** A pure state machine (`setup_state.py`) driven by a key reader (`keys.py`) and a `RealDriver` that composes existing `hardware`/`bootstrap`/cli seams; `setup_screen.py` renders rich cards via `Live` and reconciles key events + a worker-thread event queue. `cli.cmd_init` routes TTY first-runs to the screen; everything else keeps today's linear path.

**Tech Stack:** Python 3.12 stdlib + rich (already a dependency). No new packages.

**Spec:** `docs/superpowers/specs/2026-08-21-magnitude-parity-setup-design.md`

## Global Constraints

- Python >= 3.12; NO new dependencies (httpx/rich/fastapi/etc. only).
- Tests run with `uv run pytest`; every task leaves the full suite green.
- All machine access stays behind injectable seams (monkeypatch pattern used across `tests/`).
- State objects are frozen dataclasses; transitions are pure functions.
- Commit after every task, conventional-style subjects matching repo history.
- Copy rules: card titles "Preparing your garden" / "Choose your garden" / "Finishing onboarding"; Esc hint is "skip for now" (first run) or "close" (re-run).
- Marker file: `~/.kultivait/onboarding.json` = `{"completed": true, "completed_at": <iso>, "skipped": <bool>}`.

---

### Task 1: Onboarding completion marker

**Files:**
- Create: `src/kultivait/onboarding.py`
- Test: `tests/test_onboarding.py`

**Interfaces:**
- Produces: `ONBOARDING_PATH: Path`, `is_complete(path=ONBOARDING_PATH) -> bool`, `complete(skipped: bool = False, path=ONBOARDING_PATH) -> None`

- [ ] **Step 1: Write the failing tests**

```python
"""onboarding marker: magnitude writes {completed:true} once and never
un-sets it; kultivait adds skipped/completed_at for the skip path."""

import json

from kultivait import onboarding


def test_missing_marker_is_incomplete(tmp_path):
    assert onboarding.is_complete(tmp_path / "onboarding.json") is False


def test_complete_roundtrip_and_skip_flag(tmp_path):
    p = tmp_path / "onboarding.json"
    onboarding.complete(skipped=True, path=p)
    assert onboarding.is_complete(p) is True
    data = json.loads(p.read_text())
    assert data["completed"] is True
    assert data["skipped"] is True
    assert data["completed_at"]


def test_corrupt_marker_is_incomplete_not_a_crash(tmp_path):
    p = tmp_path / "onboarding.json"
    p.write_text("{not json")
    assert onboarding.is_complete(p) is False


def test_complete_is_idempotent(tmp_path):
    p = tmp_path / "onboarding.json"
    onboarding.complete(path=p)
    onboarding.complete(path=p)  # re-runs must not raise
    assert onboarding.is_complete(p) is True
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_onboarding.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kultivait.onboarding'`

- [ ] **Step 3: Implement**

```python
"""Onboarding completion marker — kultivait's analog of magnitude's
~/.magnitude/state/onboarding.json. `completed` is monotonic: once true it
is never written false. `skipped` records the Esc-skip-for-now path so the
survey panel can nudge the user to re-run init."""

import datetime
import json
from pathlib import Path

ONBOARDING_PATH = Path.home() / ".kultivait" / "onboarding.json"


def is_complete(path: Path = ONBOARDING_PATH) -> bool:
    try:
        return bool(json.loads(Path(path).read_text()).get("completed"))
    except (OSError, ValueError):
        return False


def complete(skipped: bool = False, path: Path = ONBOARDING_PATH) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "completed": True,
                "completed_at": datetime.datetime.now().isoformat(timespec="seconds"),
                "skipped": skipped,
            },
            indent=2,
        )
        + "\n"
    )
```

- [ ] **Step 4: Run tests — PASS**
- [ ] **Step 5: Commit** `git add src/kultivait/onboarding.py tests/test_onboarding.py && git commit -m "feat: onboarding completion marker"`

---

### Task 2: Raw-key reader (`keys.py`)

**Files:**
- Create: `src/kultivait/keys.py`
- Test: `tests/test_keys.py`

**Interfaces:**
- Produces: `parse_key(data: bytes) -> str` (returns one of `"up","down","left","right","enter","esc","ctrl-c"` or the lowercase char, else `"other"`); `KeyReader` (context manager with `poll(timeout) -> str | None`, attrs `stdin_fd`, injected `termios`/`tty` modules); `ScriptedKeys(events)` — same duck type for tests, pops one event per poll, `None` when exhausted.

- [ ] **Step 1: Write the failing tests**

```python
"""keys: ANSI bytes -> normalized key names; KeyReader always restores the
terminal; ScriptedKeys drives the screen loop deterministically in tests."""

import termios

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


def test_key_reader_restores_terminal_even_on_error():
    """cbreak must be undone in finally — a crash mid-setup must not leave
    the user's terminal echo-less."""
    calls = []

    class FakeTermios:
        tcgetattr = staticmethod(lambda fd: ("saved",))
        tcsetattr = staticmethod(lambda fd, when, attrs: calls.append((when, attrs)))
        TCSANOW = 0

    class FakeTty:
        setcbreak = staticmethod(lambda fd, when: calls.append(("setcbreak", fd)))

    reader = KeyReader(stdin_fd=0, termios_mod=FakeTermios, tty_mod=FakeTty)
    with reader:
        assert ("setcbreak", 0) in calls
        raise RuntimeError("boom")


try:
    with KeyReader(stdin_fd=0, termios_mod=type("T", (), {
        "tcgetattr": staticmethod(lambda fd: ()),
        "tcsetattr": staticmethod(lambda *a: calls.append("restore")),
        "TCSANOW": 0,
    }), tty_mod=type("T", (), {"setcbreak": staticmethod(lambda *a: None)})):
        pass
except RuntimeError:
    pass
assert "restore" in calls


def test_scripted_keys_yields_then_none():
    sk = ScriptedKeys(["down", "enter"])
    assert sk.poll(0) == "down"
    assert sk.poll(0) == "enter"
    assert sk.poll(0) is None
```

- [ ] **Step 2: Run — FAIL (module missing)**
- [ ] **Step 3: Implement**

```python
"""Raw single-key input for the setup screen: termios cbreak + ANSI CSI
parsing. The screen loop polls; nothing blocks. ScriptedKeys is the
deterministic stand-in used by setup_screen tests."""

import os
import select
import sys
import termios
import tty
from collections import deque
from contextlib import contextmanager

_CSI = {"A": "up", "B": "down", "C": "right", "D": "left"}


def parse_key(data: bytes) -> str:
    if data in (b"\r", b"\n"):
        return "enter"
    if data == b"\x03":
        return "ctrl-c"
    if data == b"\x1b":
        return "esc"
    if len(data) >= 3 and data[:2] == b"\x1b[":
        return _CSI.get(chr(data[2:3] and data[2]), "other")
    if len(data) == 1:
        ch = chr(data[0])
        return ch.lower() if ch.isalnum() else "other"
    return "other"


class KeyReader:
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
    """Same shape as KeyReader; poll pops the next scripted key."""

    def __init__(self, events):
        self._events = deque(events)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def poll(self, timeout: float) -> "str | None":
        return self._events.popleft() if self._events else None
```

- [ ] **Step 4: Run tests — PASS** (tidy the restore-test into one function if written awkwardly; keep the assertion that restore happens on exception)
- [ ] **Step 5: Commit** `git commit -m "feat: raw-key reader with ANSI parsing and scripted test seam"`

---

### Task 3: State machine — preparation, rows, outcome

**Files:**
- Create: `src/kultivait/setup_state.py`
- Test: `tests/test_setup_state.py`

**Interfaces:**
- Produces: `PENDING/RUNNING/DONE/FAILED`; `PrepStep`, `ChooserRow`, `Operation(tag, done, total, confirm_yes)`, `Notice(message)`, `Preparation(runtime, models, sizes, clis, plan, profile, have_llamacpp, have_brew, have_ollama)`, `SetupState`, `SetupOutcome(exit, runtime)`; `begin(first_run) -> SetupState`; `prep_event(state, step_id, status, detail="")`; `prep_done(state, prep, rows)`; `build_rows(prep, allow_downloads) -> tuple[ChooserRow, ...]`; `outcome_of(state) -> SetupOutcome`. Consumes: `kultivait.hardware.SetupPlan` (only for attrs).

- [ ] **Step 1: Write the failing tests**

```python
"""setup_state part 1: preparation checklist transitions, chooser-row
construction from a Preparation survey, and the outcome snapshot. Pure —
no I/O anywhere in this module's tests."""

from kultivait.hardware import HardwareProfile, SetupPlan
from kultivait.setup_state import (
    DONE, FAILED, RUNNING, Preparation, begin, build_rows, outcome_of,
    prep_done, prep_event,
)
from kultivait.hardware import QWEN3_4B, QWEN3_14B, EMBED_PICK

PLAN = SetupPlan(
    eligible=True, reason="Apple M3 with 48GB unified RAM",
    models=(QWEN3_4B, QWEN3_14B, EMBED_PICK), ctx=32768, wired_limit_mb=None,
)


def test_begin_first_run_vs_re_run():
    first = begin(first_run=True)
    assert first.phase == "preparation"
    assert first.exit_kind == "skip"
    assert [s.id for s in first.steps] == ["hardware", "runtime", "survey", "recommendations"]
    assert begin(first_run=False).exit_kind == "close"


def test_prep_event_marks_steps_and_keeps_detail():
    state = begin(first_run=True)
    state = prep_event(state, "hardware", DONE, "Apple M3 · 48 GB")
    state = prep_event(state, "runtime", RUNNING)
    hw = next(s for s in state.steps if s.id == "hardware")
    assert (hw.status, hw.detail) == (DONE, "Apple M3 · 48 GB")
    assert next(s for s in state.steps if s.id == "runtime").status == RUNNING


def test_prep_done_moves_to_chooser_with_rows():
    prep = Preparation(runtime=None, plan=PLAN, have_llamacpp=True, have_brew=True)
    rows = build_rows(prep, allow_downloads=True)
    state = prep_done(begin(first_run=True), prep, rows)
    assert state.phase == "chooser"
    assert rows[0].kind == "bundle"
    assert "GB" in rows[0].sub
    assert rows[0].why == PLAN.reason
    assert rows[1].kind == "single"


def test_build_rows_no_downloads_when_runtime_serves():
    prep = Preparation(runtime="ollama", models=("qwen3:14b",), sizes={"qwen3:14b": 9_000_000_000}, plan=PLAN)
    rows = build_rows(prep, allow_downloads=False)
    assert [r.kind for r in rows] == ["installed"]
    assert rows[0].label == "qwen3:14b"


def test_build_rows_start_row_when_llamacpp_installed_idle():
    prep = Preparation(runtime=None, plan=PLAN, have_llamacpp=True)
    rows = build_rows(prep, allow_downloads=False)  # e.g. no brew but binary present
    assert rows[-1].kind == "start"


def test_outcome_of_maps_runtime_and_started():
    prep = Preparation(runtime="ollama", models=("m",), sizes={}, clis=())
    state = prep_done(begin(first_run=False), prep, ())
    state = prep_event(state, "hardware", DONE)
    # simulate closing with outcome set by later transitions
    from dataclasses import replace
    state = replace(state, phase="closing", outcome="completed", started_llamacpp=True)
    out = outcome_of(state)
    assert out.exit == "completed"
    assert out.runtime == "ollama"  # runtime wins over started flag? no — started means we now serve
```

Note while implementing: `outcome_of` prefers `started_llamacpp` → `"llamacpp"` (a freshly started server is what a survey should target), falling back to `prep.runtime`, else `None`. Fix the last assertion accordingly (`== "llamacpp"`).

- [ ] **Step 2: Run — FAIL (module missing)**
- [ ] **Step 3: Implement** `setup_state.py` with the dataclasses and functions above; `build_rows` builds: bundle row (label "Tuned garden for this Mac", sub `f"{roles} + embed · {total_gb:.1f} GB"`, detail = one `filename (role, X.X GB)` line per pick, why = plan.reason), single row (reasoning pick + embed only), `installed` rows per surveyed model (`sub = GB from sizes`), and a trailing `start` row when `have_llamacpp and runtime is None and not have_ollama`. Download rows only when `allow_downloads and plan is not None and plan.eligible and runtime is None`.
- [ ] **Step 4: Run tests — PASS**
- [ ] **Step 5: Commit** `git commit -m "feat: setup state machine — preparation, rows, outcome"`

---

### Task 4: State machine — keys and operation lifecycle

**Files:**
- Modify: `src/kultivait/setup_state.py`
- Test: `tests/test_setup_state.py` (append)

**Interfaces:**
- Produces: `handle_key(state, key) -> SetupState`; `handle_event(state, event) -> SetupState` where event tuples are `("prep", id, status, detail)`, `("prep_done", prep, allow_downloads)`, `("prep_failed", reason)`, `("progress", done, total)`, `("op_done", which, ok, reason)`; `SetupState` gains `selected`, `operation`, `notice`, `retryable`, `wired_answer`, `started_llamacpp`, `stop_download`, `outcome`.

- [ ] **Step 1: Append failing tests** covering: up/down/j/k clamped movement; Enter on bundle → `Operation("download")`; Enter on installed row → phase closing, outcome completed; Esc first-run → closing outcome skipped; Esc re-run → outcome closed; Esc during download → `confirm_cancel`; ←/→ toggles `confirm_yes` (default False); Enter yes → operation None + `stop_download` True + notice mentions resume; Enter no → back to `Operation("download")` with done/total preserved; `("progress", ...)` updates operation counters; `("op_done","download",True,"")` → `confirm_wired` when plan.wired_limit_mb else `Operation("start")`; y/n on confirm_wired sets wired_answer and moves to start; `("op_done","start",True,"")` → closing completed + `started_llamacpp`; `("op_done","start",False,"boom")` → unlocked with `retryable == "start"` and notice contains "r Retry"; `r` relaunches start; `c` clears; `("op_done","download",False,"x")` → unlocked with notice; keys ignored while `Operation("start")` runs; `("prep_failed", "x")` → chooser with no rows and a notice. Representative test:

```python
def test_esc_during_download_needs_confirmation_to_stop():
    state = _chooser()  # helper: begin → prep_done with bundle row selected
    state = handle_key(state, "enter")           # start download
    state = handle_event(state, ("progress", 5, 10))
    state = handle_key(state, "esc")             # ask, not stop
    assert state.operation.tag == "confirm_cancel"
    assert state.operation.confirm_yes is False  # default No — cancel is opt-in
    state = handle_key(state, "right")           # → Yes
    state = handle_key(state, "enter")
    assert state.operation is None
    assert state.stop_download is True
    assert "resume" in state.notice.message
```

- [ ] **Step 2: Run — FAIL**
- [ ] **Step 3: Implement** `handle_key` / `handle_event` per the spec's state diagram (module docstring carries the diagram). Rules: ctrl-c aliases esc; navigation only when `operation is None`; `retryable` only honored at `"start"`; wired-limit confirm asks BEFORE start_server so the driver never blocks.
- [ ] **Step 4: Run tests — PASS**
- [ ] **Step 5: Commit** `git commit -m "feat: setup state — key handling and download/start lifecycle"`

---

### Task 5: Cooperative cancel seam in `bootstrap.download_models`

**Files:**
- Modify: `src/kultivait/bootstrap.py:151-190` (`download_models`)
- Test: `tests/test_bootstrap.py` (append)

**Interfaces:**
- Produces: `download_models(..., stop: "threading.Event | None" = None)` — checked between files; `True` still means all-present.

- [ ] **Step 1: Failing test**

```python
def test_download_models_stop_event_cancels_between_files(tmp_path):
    """Esc-cancel stops between files, keeps .part resume behavior, and
    never touches the network once stop is set."""
    import threading

    dest = tmp_path / "ggufs"
    plan = SetupPlan(eligible=True, reason="r", models=(QWEN3_4B, QWEN3_14B))
    stop = threading.Event(); stop.set()
    called = []

    class Client:
        def stream(self, *a, **k):
            called.append(1)
            raise AssertionError("network must not be touched")

    ok = bootstrap.download_models(
        plan, dest, confirm=lambda m: True, client=Client(),
        on_progress=None, log=lambda *a, **k: None, stop=stop,
    )
    assert ok is False
    assert called == []
```

- [ ] **Step 2: FAIL → Step 3:** add `stop=None` param; first line inside the per-file loop: `if stop is not None and stop.is_set(): log("download cancelled — .part files kept for resume"); return False`. **Step 4:** run the full bootstrap suite (all existing download tests must stay green — `stop` defaults to None). **Step 5:** Commit `git commit -m "feat: cooperative cancel seam for bootstrap downloads"`

---

### Task 6: Renderers (`setup_screen.py`)

**Files:**
- Create: `src/kultivait/setup_screen.py`
- Test: `tests/test_setup_screen.py`

**Interfaces:**
- Consumes: `setup_state` types, `tui.console`.
- Produces: `STEP_GLYPH`, `_bar(done, total, width=30) -> str`, `format_transfer(samples, total) -> str` (samples = iterable of `(monotonic_t, done)`), `visible_window(selected, n, max_rows=4) -> (start, stop)`, `render(state, samples=(), width=80) -> RenderableType` dispatching to `render_preparation` / `render_chooser` / `render_closing`. Cards are `Panel(..., border_style="green", expand=False)` titled "Preparing your garden" / "Choose your garden" / "Finishing onboarding"; hint line swaps on `exit_kind`; wide layout (list left, detail right) at width >= 105 via `Table.grid`.

- [ ] **Step 1: Failing tests** (capture style from `tests/test_tui.py`): preparation shows `○`, `⠋`, `✓` glyphs, step labels, and "Esc skip for now" vs "Esc close"; chooser lists section headers "AVAILABLE TO DOWNLOAD" / "ON THIS COMPUTER", `›` marker on selection, the selected row's `why` under "WHY THIS GARDEN", and hint "up/down choose · Enter to set up · Esc skip for now"; during `Operation("download")` the bar `█░` and "Esc cancel" appear and the hint line changes; `confirm_cancel` renders "Cancel the download?" with Yes/No; `confirm_wired` renders the sudo question; start failure notice renders "r Retry · c Choose another"; closing renders "Finishing onboarding"; `format_transfer([(0, 0), (1.0, 5_000_000)], 10_000_000)` → `"5.0 MB/s"` and an "about" ETA; `_bar(5, 10, 10)` == `"█" * 5 + "░" * 5`; `visible_window(0, 6)` == `(0, 4)` and `visible_window(5, 6)` == `(2, 6)`.

- [ ] **Step 2: FAIL → Step 3: Implement** renderers as pure rich composition (Group/Panel/Table/Text, styles: done green, running bold-green spinner glyph, failed red, dim hints). **Step 4: PASS → Step 5: Commit** `git commit -m "feat: rich card renderers for the setup screen"`

---

### Task 7: Driver — `RealDriver` composing existing seams

**Files:**
- Modify: `src/kultivait/setup_screen.py`
- Test: `tests/test_setup_screen.py` (append)

**Interfaces:**
- Produces: `RealDriver(scan, plan, probe, survey, clis, which=shutil.which)` with `prepare(emit) -> Preparation` (emits prep events, catches survey errors, never raises), `download(single, post, stop)` (ensure_llamacpp with auto-yes → advisory/failed posts `("op_done","download",False,reason)`; else `bootstrap.download_models(plan, models_dir(), confirm=lambda m: True, on_progress=<throttled post>, stop=stop)`, progress throttled to ~5/s), `start_server(wired, post)` (write_artifacts → offer_wired_limit with `confirm=lambda m: wired` → bootstrap.start_server; posts ok/failure with `bootstrap._tail(log)` as reason). `single=True` downloads only the reasoning pick + embed via `dataclasses.replace(plan, models=...)`.
- Tests inject fake `scan/probe/survey/which` and monkeypatch `bootstrap.download_models`/`write_artifacts`/`offer_wired_limit`/`start_server` — assert event sequences and that `stop` is forwarded. Test that a brew-less, llama-less machine yields `("op_done","download",False,"advisory...")`.

- [ ] **Step 1: Failing tests → Step 2: FAIL → Step 3: Implement → Step 4: PASS → Step 5: Commit** `git commit -m "feat: setup driver over hardware/bootstrap seams"`

---

### Task 8: The screen loop — `run_setup`

**Files:**
- Modify: `src/kultivait/setup_screen.py`
- Test: `tests/test_setup_screen.py` (append)

**Interfaces:**
- Produces: `run_setup(*, driver, keys, first_run, console=None, spawn=None, poll_s=0.05) -> SetupOutcome`. Default `spawn` runs work on a daemon thread; tests pass `spawn=lambda fn: fn()` for deterministic synchronous execution. `KULTIVAIT_RUNTIME` in env hides download rows (allow_downloads False). Internal `_drain`, `_sync(prev, state, ...)` (spawns download/start on operation transitions, sets the stop event when `stop_download` flips True, clears it on launch), `render` per state, samples deque for transfer rate.

- [ ] **Step 1: Failing end-to-end tests** with a `FakeDriver` (instant, posts `op_done` before returning) + `ScriptedKeys` + `spawn=sync` + a recording `Console(record=True)`:
  1. happy path: keys `["enter", "n"]` (download bundle → wired confirm "n" → start ok) → outcome `exit == "completed"`, `runtime == "llamacpp"`;
  2. skip: `["esc"]` → `exit == "skipped"`, runtime from prep;
  3. re-run close: `first_run=False`, `["esc"]` → `exit == "closed"`;
  4. cancel: `["enter", "esc", "right", "enter"]` → back at chooser, FakeDriver's stop event set;
  5. start failure then retry: driver fails first start, keys `["enter", "n", "r"]` → second start ok → completed.
- [ ] **Step 2: FAIL → Step 3: Implement** the loop exactly as spec'd: queue + `Live` + `keys.poll` + `_drain` + `_sync`; `while state.phase != "closing"`. **Step 4: PASS → Step 5: Commit** `git commit -m "feat: interactive setup screen loop"`

---

### Task 9: CLI integration

**Files:**
- Modify: `src/kultivait/cli.py` (`cmd_init`, add `_survey_and_save`, `_run_setup_screen`, `--setup` flag; delete `_offer_setup`; import `onboarding`, `setup_screen`, `keys`)
- Modify: `tests/test_cli_init.py` (drop `_offer_setup` tests; keep both `--no-setup` tests unchanged; add routing tests)
- Test: `tests/test_cli_init.py`

**Interfaces:**
- Consumes: `onboarding.is_complete/complete`, `setup_screen.run_setup/RealDriver/SetupOutcome`, `keys.KeyReader`.
- Produces: `cmd_init` routing (TTY + (`--setup` or marker incomplete) → screen; else linear path); `_survey_and_save(runtime) -> None` (today's survey/detect/render/save block, extracted verbatim); marker written only when `not onboarding.is_complete()` at entry, with `skipped = outcome.exit == "skipped"`; `outcome.exit == "closed"` returns without writing.

- [ ] **Step 1: Failing tests**

```python
def test_cmd_init_first_run_routes_to_screen_and_writes_marker(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "_stdin_is_tty", lambda: True)
    monkeypatch.setattr(cli.onboarding, "ONBOARDING_PATH", tmp_path / "onboarding.json")
    monkeypatch.setattr(cli, "CONFIG_PATH", tmp_path / "config.toml")
    monkeypatch.setattr(cli, "_survey_local", lambda r: ([], {}))
    monkeypatch.setattr(cli, "_available_clis", lambda: [])
    monkeypatch.setattr(cli, "_detect_runtime", lambda: "ollama")
    monkeypatch.setattr(cli.setup_screen, "run_setup",
                       lambda **k: cli.setup_screen.SetupOutcome(exit="skipped", runtime=None))
    cli.cmd_init(argparse.Namespace(no_setup=False, setup=False))
    assert '"completed": true' in (tmp_path / "onboarding.json").read_text()
    assert '"skipped": true' in (tmp_path / "onboarding.json").read_text()
    assert (tmp_path / "config.toml").exists()  # skip still writes virtual-tier config


def test_cmd_init_closed_re_run_writes_nothing(monkeypatch, tmp_path):
    ... same fixtures, run_setup returns SetupOutcome(exit="closed")
    assert not (tmp_path / "onboarding.json").exists()
    assert not (tmp_path / "config.toml").exists()


def test_cmd_init_setup_flag_forces_screen_when_marker_complete(monkeypatch, tmp_path):
    ... pre-write marker via onboarding.complete(path=...), pass setup=True,
    assert run_setup was called (monkeypatch records kwargs first_run=False)
```

(Also assert `first_run` is `False` when the marker exists, `True` otherwise.)

- [ ] **Step 2: FAIL → Step 3: Implement.** `cmd_init`:

```python
def cmd_init(args: argparse.Namespace) -> None:
    forced = os.environ.get("KULTIVAIT_RUNTIME")
    first_run = not onboarding.is_complete()
    if not args.no_setup and _stdin_is_tty() and (args.setup or first_run):
        outcome = _run_setup_screen(first_run=first_run)
        if outcome.exit != "closed":
            _survey_and_save(outcome.runtime or forced or _detect_runtime())
            if first_run:
                onboarding.complete(skipped=outcome.exit == "skipped")
        return
    _survey_and_save(forced or _detect_runtime())
```

`_run_setup_screen` builds `RealDriver(scan=hardware.scan, plan=hardware.plan, probe=_running_runtime, survey=_survey_local, clis=_available_clis)` and runs `run_setup(driver=..., keys=KeyReader(), first_run=...)`. Add `--setup` to the init subparser (`action="store_true"`).

- [ ] **Step 4: full suite PASS (test_cli_init's old `_offer_setup` tests deleted with the function; `test_bootstrap.py` untouched) → Step 5: Commit** `git commit -m "feat: init routes first-run TTY through the setup screen"`

---

### Task 10: Installer + README

**Files:**
- Modify: `landing/install.sh`
- Modify: `README.md` (sections "Quickstart" bullet list and "Zero to local")

**Interfaces:** none.

- [ ] **Step 1:** Replace `install.sh` body with: uv install (unchanged) → `uv tool install` (unchanged) → `kultivait init </dev/tty` (the `/dev/tty` redirection is required: `curl | sh` leaves stdin as the pipe, which is why the interactive path never fired from scripted installs) → keep the "planted. next:" footer. Drop the ollama hard-exit and the `ollama pull` block — runtime choice now belongs to the setup screen, and the zero-to-local path is llama.cpp anyway.
- [ ] **Step 2:** `sh -n landing/install.sh` (syntax check) and re-read for correctness.
- [ ] **Step 3:** README: rewrite the `init` bullet in Quickstart ("opens the setup screen: preparation checklist → choose a garden → download → serve; `--no-setup` keeps the old survey-only flow") and the "Zero to local" section (screen narrative replacing the four `[Y/n]` prompts; note Enter-is-consent, the one sudo confirm, Esc-skip semantics, `onboarding.json`, `kultivait init --setup` to reopen, and the `</dev/tty` installer detail).
- [ ] **Step 4:** `uv run pytest` full suite one last time.
- [ ] **Step 5: Commit** `git commit -m "docs: installer hands off to the setup screen; README covers the new flow"`

---

## Self-Review (done at write time)

- Spec coverage: preparation card (T3/T6), chooser + detail + wide layout (T3/T6), Enter-as-consent + sudo exception (T4/T7), download rate/ETA + cancel-confirm (T4/T5/T6), starting + retry/choose (T4/T7/T8), closing + marker (T1/T9), skip-completes semantics (T4/T9), `--setup` re-entry (T9), non-TTY/`--no-setup`/`KULTIVAIT_RUNTIME` fallbacks (T9/T8), install.sh `</dev/tty` + slimming (T10), README (T10). Radar/mouse/themes: documented as not-ported in spec — no tasks by design.
- Type consistency: `SetupOutcome(exit, runtime)` used identically in T3/T8/T9; `Operation` fields match between T4 states and T6 renderers; `RealDriver(scan, plan, probe, survey, clis, which)` matches T7 tests and T9 construction; `download_models(..., stop=)` in T5 matches T7's call.
- Known refinement vs spec (accepted): Closing renders one static frame (config writes are millisecond-local; an animated spinner would be theater) — spec mockup shows a spinner glyph, the renderer still draws `⠋`.
```

Plan complete. Executing inline (the autonomous-session choice — subagent-per-task would re-pay all the context I already hold). Loading executing-plans: