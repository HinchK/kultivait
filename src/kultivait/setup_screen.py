"""setup_screen: rich cards, the machine-composing driver, and the
interactive loop for the setup flow.

Renderers are pure functions from `setup_state.SetupState` to rich
renderables (capturable without a terminal, like tui.render_survey).
RealDriver composes the existing hardware/bootstrap seams — the screen is
the consent layer, so every confirm the driver passes down is auto-yes
(the sudo wired-limit answer arrives pre-resolved from its own card).
run_setup owns threads, keys, and the event queue.
"""

import dataclasses
import os
import queue
import shutil
import subprocess
import threading
import time
from collections import deque
from pathlib import Path

import httpx
from rich.console import Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

import kultivait.bootstrap as bootstrap
from kultivait import setup_state
from kultivait.setup_state import DONE, FAILED, PENDING, RUNNING

WIDE = 105  # at this width the chooser puts the detail panel beside the list
STEP_GLYPH = {PENDING: "○", RUNNING: "⠋", DONE: "✓", FAILED: "!"}
STEP_STYLE = {PENDING: "dim", RUNNING: "bold green", DONE: "green", FAILED: "bold red"}
BAR_WIDTH = 30


def _bar(done: int, total: int, width: int = BAR_WIDTH) -> str:
    if not total:
        return "░" * width
    filled = min(width, round(width * done / total))
    return "█" * filled + "░" * (width - filled)


def format_transfer(samples, total: int) -> str:
    """"8.2 MB/s · about 3 minutes remaining" from (monotonic_t, bytes) samples."""
    samples = list(samples)
    if len(samples) < 2:
        return ""
    (t0, d0), (t1, d1) = samples[0], samples[-1]
    dt = t1 - t0
    if dt <= 0 or d1 <= d0:
        return ""
    rate = (d1 - d0) / dt
    rate_s = f"{rate / 1e9:.1f} GB/s" if rate >= 1e9 else f"{rate / 1e6:.1f} MB/s"
    eta = max(total - d1, 0) / rate
    if eta < 60:
        eta_s = f"{eta:.0f} seconds"
    elif eta < 3600:
        eta_s = f"{eta / 60:.0f} minutes"
    else:
        eta_s = f"{eta / 3600:.0f} hours"
    return f"{rate_s} · about {eta_s} remaining"


def visible_window(selected: int, n: int, max_rows: int = 4) -> "tuple[int, int]":
    """Which row indices to show in narrow mode — a 4-row window that keeps
    the selection visible (magnitude clamps the list viewport the same way)."""
    if n <= max_rows:
        return (0, n)
    start = max(0, min(selected - 1, n - max_rows))
    return (start, start + max_rows)


def render_preparation(state) -> Panel:
    items = []
    for s in state.steps:
        line = f"{STEP_GLYPH[s.status]} {s.label}" + (f" · {s.detail}" if s.detail else "")
        items.append(Text(line, style=STEP_STYLE[s.status]))
    hint = Text(
        "Esc skip for now" if state.exit_kind == "skip" else "Esc close", style="dim"
    )
    return Panel(
        Group(*items, Text(), hint),
        title="Preparing your garden",
        border_style="green",
        expand=False,
    )


def _row_line(i: int, row, selected: int) -> Text:
    on = i == selected
    parts = [("› " if on else "  ", "bold green" if on else "dim")]
    parts.append((row.label, "bold" if on else ""))
    if row.sub:
        parts.append((f"  {row.sub}", "dim"))
    return Text.assemble(*parts)


def _list_block(state) -> list:
    lines = []
    win_start, win_stop = visible_window(state.selected, len(state.rows))
    sections = (
        (("bundle", "single"), "AVAILABLE TO DOWNLOAD"),
        (("installed", "start"), "ON THIS COMPUTER"),
    )
    for kinds, header in sections:
        idx = [i for i, r in enumerate(state.rows) if r.kind in kinds]
        if not idx:
            continue
        lines.append(Text(header, style="bold dim"))
        for i in idx:
            if win_start <= i < win_stop:
                lines.append(_row_line(i, state.rows[i], state.selected))
    return lines


def _operation_block(state, samples) -> list:
    op = state.operation
    if op is None:
        if state.notice is not None:
            return [Text(state.notice.message, style="yellow")]
        return []
    if op.tag == "download":
        pct = 100 * op.done // op.total if op.total else 0
        lines = [
            Text("Downloading"),
            Text.assemble((_bar(op.done, op.total), "green"), (f"  {pct}%", "bold")),
        ]
        transfer = format_transfer(samples, op.total)
        if transfer:
            lines.append(Text(transfer, style="dim"))
        lines.append(Text("Esc cancel", style="dim"))
        return lines
    if op.tag == "confirm_cancel":
        yes = "› Yes" if op.confirm_yes else "  Yes"
        no = "› No" if not op.confirm_yes else "  No"
        return [Text(f"Cancel the download?  {yes}   {no}   (←/→, Enter)")]
    if op.tag == "confirm_wired":
        return [
            Text(
                "Raise the GPU memory cap now? sudo will ask for your password (y/n)",
                style="yellow",
            )
        ]
    return [Text("⠋ Starting llama-server...", style="bold green")]


def _detail_block(state) -> list:
    if not state.rows or state.operation is not None:
        return []
    row = state.rows[state.selected]
    lines = [Text(row.label, style="bold")]
    lines += [Text(d, style="dim") for d in row.detail]
    if row.why:
        lines += [Text("WHY THIS GARDEN", style="bold dim"), Text(row.why)]
    return lines


def _hint(state) -> Text:
    op = state.operation
    if op is None:
        esc = "skip for now" if state.exit_kind == "skip" else "close"
        return Text(f"up/down choose · Enter to set up · Esc {esc}", style="dim")
    if op.tag == "download":
        return Text("Download in progress · Esc cancel", style="dim")
    if op.tag == "confirm_cancel":
        return Text("←/→ choose · Enter confirms", style="dim")
    if op.tag == "confirm_wired":
        return Text("y raise the cap · n skip it", style="dim")
    return Text("Loading model weights...", style="dim")


def _subtitle(state) -> str:
    profile = state.prep.profile if state.prep is not None else None
    if profile is None or not getattr(profile, "chip", ""):
        return ""
    return f"{profile.chip} · {profile.ram_gb:.0f} GB unified"


def render_chooser(state, samples=(), width: int = 80) -> Panel:
    left = _list_block(state)
    if not left:
        left = [Text("(nothing to set up on this machine)", style="dim")]
    left += _operation_block(state, samples)
    detail = _detail_block(state)

    if width >= WIDE and detail:
        grid = Table.grid(padding=(0, 3))
        grid.add_column()
        grid.add_column()
        grid.add_row(Group(*left), Group(*detail))
        body = grid
    else:
        body = Group(*left, Text(), *detail)

    subtitle = _subtitle(state)
    parts = [Text(subtitle, style="dim"), Text()] if subtitle else []
    return Panel(
        Group(*parts, body, Text(), _hint(state)),
        title="Choose your garden",
        border_style="green",
        expand=False,
    )


def render_closing() -> Panel:
    return Panel(
        Text("⠋ writing config · surveying tiers"),
        title="Finishing onboarding",
        border_style="green",
        expand=False,
    )


def render(state, samples=(), width: int = 80):
    if state.phase == "preparation":
        return render_preparation(state)
    if state.phase == "closing":
        return render_closing()
    return render_chooser(state, samples=samples, width=width)


class RealDriver:
    """The machine-facing half of the screen: everything the state machine
    says "do" becomes a call into the existing hardware/bootstrap seams.
    All knobs are injected (mirroring bootstrap.py), so tests never touch
    brew, the network, or the real home dir."""

    def __init__(
        self,
        scan,
        plan,
        probe,
        survey,
        clis,
        which=shutil.which,
        home: "Path | None" = None,
        run_cmd=subprocess.run,
        popen=subprocess.Popen,
        http_get=httpx.get,
        log=lambda *a, **k: None,
    ):
        self._scan = scan
        self._plan = plan
        self._probe = probe
        self._survey = survey
        self._clis = clis
        self._which = which
        self._home = home or Path.home() / ".kultivait"
        self._run_cmd = run_cmd
        self._popen = popen
        self._http_get = http_get
        self._log = log
        self._prep: "setup_state.Preparation | None" = None
        self._last_progress = 0.0

    def prepare(self, emit) -> setup_state.Preparation:
        emit("hardware", RUNNING)
        profile = self._scan()
        detail = f"{profile.chip} · {profile.ram_gb:.0f} GB" if profile.chip else ""
        emit("hardware", DONE, detail)
        emit("runtime", RUNNING)
        runtime = self._probe()
        emit("runtime", DONE, runtime or "none running")
        models, sizes = [], {}
        if runtime:
            emit("survey", RUNNING)
            try:
                models, sizes = self._survey(runtime)
            except Exception:
                pass  # a dead runtime mid-survey is a finding, not a crash
            emit("survey", DONE, f"{len(models)} found")
        else:
            emit("survey", DONE, "no runtime running")
        emit("recommendations", RUNNING)
        plan = self._plan(profile)
        if plan.eligible:
            emit("recommendations", DONE, plan.reason)
        else:
            emit("recommendations", FAILED, plan.reason)
        self._prep = setup_state.Preparation(
            runtime=runtime,
            models=tuple(models),
            sizes=sizes,
            clis=tuple(self._clis()),
            plan=plan,
            profile=profile,
            have_llamacpp=bool(self._which("llama-server")),
            have_brew=bool(self._which("brew")),
            have_ollama=bool(self._which("ollama")),
        )
        return self._prep

    def download(self, single: bool, post, stop: threading.Event) -> None:
        if not self._prep.have_llamacpp:
            state = bootstrap.ensure_llamacpp(
                confirm=lambda m: True, run_cmd=self._run_cmd, which=self._which
            )
            if state not in ("present", "installed"):
                post(
                    (
                        "op_done",
                        "download",
                        False,
                        f"llama.cpp install {state} — see manual steps above",
                    )
                )
                return
        plan = self._prep.plan
        if single:
            keep = tuple(m for m in plan.models if m.role in ("reasoning", "embed"))
            plan = dataclasses.replace(plan, models=keep)

        def on_progress(done: int, total: int) -> None:
            now = time.monotonic()
            if done >= total or now - self._last_progress >= 0.2:
                self._last_progress = now
                post(("progress", done, total))

        self._last_progress = 0.0
        ok = bootstrap.download_models(
            plan,
            bootstrap.models_dir(),
            confirm=lambda m: True,
            on_progress=on_progress,
            log=self._log,
            stop=stop,
        )
        post(
            (
                "op_done",
                "download",
                ok,
                "" if ok else "download stopped — .part files kept; Enter retries with resume",
            )
        )

    def start_server(self, wired: bool, post) -> None:
        plan = self._prep.plan
        preset, script = bootstrap.write_artifacts(plan, self._home, bootstrap.models_dir())
        self._log(f"wrote {preset}")
        self._log(f"wrote {script}")
        bootstrap.offer_wired_limit(
            plan, confirm=lambda m: wired, run_cmd=self._run_cmd, log=self._log
        )
        ok = bool(
            bootstrap.start_server(
                script, popen=self._popen, http_get=self._http_get, log=self._log
            )
        )
        reason = "" if ok else bootstrap._tail(self._home / "llamacpp.log")
        post(("op_done", "start", ok, reason))


def _spawn_thread(fn) -> None:
    threading.Thread(target=fn, daemon=True).start()


def _drain(state, events: "queue.Queue", samples: "deque",
           spawned: "dict | None" = None, stop: "threading.Event | None" = None):
    """Apply queued driver events. When an operation ends (op becomes None),
    retire its instance immediately — a retry key in the same pass must be
    able to spawn a fresh one (the None state can be transient within a
    single drain-then-key pass, so _sync's own reset is not enough)."""
    while True:
        try:
            ev = events.get_nowait()
        except queue.Empty:
            return state
        if ev[0] == "progress":
            samples.append((time.monotonic(), ev[1]))
        state = setup_state.handle_event(state, ev)
        if spawned is not None and state.operation is None:
            spawned["tag"] = None
            if state.stop_download and stop is not None:
                stop.set()


def _sync(state, driver, spawn, post, stop: threading.Event, spawned: dict) -> None:
    """Launch/stop real work for the state's current operation instance.

    Instance-based (`spawned`), not transition-diffed: a confirm_cancel ->
    download round-trip keeps the running thread (same instance), while a
    fresh download after a confirmed cancel re-launches — clearing the stop
    event first. Robust to several state transitions landing between polls."""
    op = state.operation
    tag = op.tag if op is not None else None
    if tag == "download" and spawned["tag"] != "download":
        stop.clear()
        single = bool(state.rows) and state.rows[state.selected].kind == "single"
        spawn(lambda: driver.download(single=single, post=post, stop=stop))
        spawned["tag"] = "download"
    elif tag == "start" and spawned["tag"] != "start":
        spawn(lambda: driver.start_server(wired=state.wired_answer, post=post))
        spawned["tag"] = "start"
    if op is None and spawned["tag"] is not None:
        if state.stop_download:
            stop.set()
        spawned["tag"] = None


def run_setup(
    *,
    driver,
    keys,
    first_run: bool,
    console=None,
    spawn=None,
    poll_s: float = 0.05,
) -> "setup_state.SetupOutcome":
    """Drive the state machine with keys + driver events until Closing.

    `spawn` defaults to a daemon thread per operation; tests pass a
    synchronous runner so event ordering is deterministic (with the
    ScriptedKeys "wait" pseudo-key standing in for human reaction time)."""
    from kultivait import tui

    console = console or tui.console
    spawn = spawn or _spawn_thread
    events: "queue.Queue" = queue.Queue()
    post = events.put
    state = setup_state.begin(first_run=first_run)
    stop = threading.Event()
    spawned = {"tag": None}
    samples: "deque" = deque(maxlen=32)
    allow_downloads = not bool(os.environ.get("KULTIVAIT_RUNTIME"))

    def work() -> None:
        try:
            prep = driver.prepare(lambda *ev: post(("prep",) + ev))
            post(("prep_done", prep, allow_downloads))
        except Exception as exc:  # a broken probe is a notice, not a crash
            post(("prep_failed", str(exc)))

    spawn(work)
    with keys:
        with Live(console=console, refresh_per_second=10) as live:
            while state.phase != "closing":
                # quiesce: handle every pending event and key — and anything
                # the work they trigger produces — before painting the frame
                while True:
                    before = state
                    state = _drain(state, events, samples, spawned, stop)
                    key = keys.poll(
                        0 if (state is not before or not events.empty()) else poll_s
                    )
                    if key is not None:
                        state = setup_state.handle_key(state, key)
                    _sync(state, driver, spawn, post, stop, spawned)
                    if key is None and events.empty() and state is before:
                        break
                live.update(render(state, samples=samples, width=console.width))
    return setup_state.outcome_of(state)
