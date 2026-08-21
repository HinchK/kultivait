"""Pure state machine for the setup screen — a port of magnitude's
packages/client-common/src/local-models/setup-state.ts.

Phases and lifecycle (no back-navigation; Esc and cancel are the only
exits, exactly like magnitude):

    Closed --begin(first_run)--> Preparation{exit_kind = skip|close}
    Preparation --prep_done--> Chooser{operation = None}
    Preparation --esc--> Closing(outcome = skipped|closed)
    Chooser + Enter(download row) --> Chooser{Downloading, locked}
    Chooser + Enter(installed row) --> Closing(completed)
    Chooser + Enter(start row) --> Chooser{Starting, locked}
    Downloading --op_done ok--> [confirm_wired] --> Chooser{Starting}
    Downloading --esc--> confirm_cancel --Yes--> Chooser{unlocked, stopped}
                                            --No--> Downloading (thread kept)
    Any op --fail--> Chooser{unlocked, notice} (+ retryable = "start")
    Starting --op_done ok--> Closing(completed, started_llamacpp)
    Chooser --esc--> Closing(skipped | closed)

Everything here is frozen data and pure functions — no I/O, so the whole
machine is table-testable. The screen (setup_screen.py) owns threads,
keys, and rendering; the driver owns the machine itself.
"""

from dataclasses import dataclass, field, replace

PENDING, RUNNING, DONE, FAILED = "pending", "running", "done", "failed"

PREP_STEPS = (
    ("hardware", "Detecting hardware"),
    ("runtime", "Checking for a local runtime"),
    ("survey", "Surveying models"),
    ("recommendations", "Preparing recommendations"),
)


@dataclass(frozen=True)
class PrepStep:
    id: str
    label: str
    status: str = PENDING
    detail: str = ""


@dataclass(frozen=True)
class ChooserRow:
    kind: str  # "bundle" | "single" | "installed" | "start"
    label: str
    sub: str = ""  # right-hand meta: "11.4 GB" / "loaded"
    detail: tuple = ()  # detail-panel lines
    why: str = ""


@dataclass(frozen=True)
class Operation:
    tag: str  # "download" | "start" | "confirm_cancel" | "confirm_wired"
    done: int = 0
    total: int = 0
    confirm_yes: bool = False


@dataclass(frozen=True)
class Notice:
    message: str


@dataclass(frozen=True)
class Preparation:
    """The driver's survey result, carried through state so the renderer
    and cmd_init can act on it without another probe."""

    runtime: "str | None" = None
    models: tuple = ()
    sizes: dict = field(default_factory=dict)
    clis: tuple = ()
    plan: "object | None" = None  # hardware.SetupPlan
    profile: "object | None" = None  # hardware.HardwareProfile
    have_llamacpp: bool = False
    have_brew: bool = False
    have_ollama: bool = False


@dataclass(frozen=True)
class SetupState:
    phase: str = "closed"  # "closed" | "preparation" | "chooser" | "closing"
    exit_kind: str = "skip"  # Esc label + write semantics: "skip" | "close"
    steps: tuple = ()
    prep: "Preparation | None" = None
    rows: tuple = ()
    selected: int = 0
    operation: "Operation | None" = None
    notice: "Notice | None" = None
    retryable: "str | None" = None  # "start" | "switch" after a failed op
    wired_answer: bool = False
    started_llamacpp: bool = False
    stop_download: bool = False  # screen sets the driver's Event when True
    outcome: "str | None" = None  # "completed" | "skipped" | "closed"
    allow_downloads: bool = True  # remembered so switch_done can rebuild rows


@dataclass(frozen=True)
class SetupOutcome:
    exit: str  # "completed" | "skipped" | "closed"
    runtime: "str | None" = None  # what a survey should target


def begin(first_run: bool) -> SetupState:
    steps = tuple(PrepStep(id, label) for id, label in PREP_STEPS)
    return SetupState(
        phase="preparation", exit_kind="skip" if first_run else "close", steps=steps
    )


def prep_event(state: SetupState, step_id: str, status: str, detail: str = "") -> SetupState:
    steps = tuple(
        s if s.id != step_id else replace(s, status=status, detail=detail or s.detail)
        for s in state.steps
    )
    return replace(state, steps=steps)


def prep_done(state: SetupState, prep: Preparation, rows: tuple) -> SetupState:
    return replace(state, phase="chooser", prep=prep, rows=rows)


def analyze_model(name: str, size_bytes: int = 0) -> str:
    """One-line sizing note for a surveyed model, so every offering carries
    its own analysis (name-based param estimate, disk size as the fallback)."""
    from kultivait.config import _param_billions

    b = _param_billions(name, size_bytes)
    if b >= 13:
        tier = "reasoning-tier class"
    elif b >= 4:
        tier = "simple + reasoning-capable"
    elif b > 0:
        tier = "light — below the 4B simple floor"
    else:
        return "param count unknown from name/size"
    return f"≈{b:.1f}B params · {tier}"


def build_rows(prep: Preparation, allow_downloads: bool) -> tuple:
    """Chooser contents from a survey. Downloads are offered even when a
    runtime is already serving — that's the pivot path (selecting a garden
    stops the other runtime first; they are never both up). A switch row
    appears only when llama-server is serving, ollama is installed, and no
    runtime was forced."""

    rows = []
    plan = prep.plan
    if allow_downloads and plan is not None and getattr(plan, "eligible", False):
        total_gb = sum(m.approx_bytes for m in plan.models) / 2**30
        rows.append(
            ChooserRow(
                kind="bundle",
                label="Tuned garden for this Mac",
                sub=f"{total_gb:.1f} GB · {len(plan.models)} models",
                detail=tuple(
                    f"{m.filename} ({m.role}, {m.approx_bytes / 2**30:.1f} GB)"
                    for m in plan.models
                ),
                why=plan.reason,
            )
        )
        reasoning = next((m for m in plan.models if m.role == "reasoning"), None)
        if reasoning is not None:
            single = (reasoning,) + tuple(m for m in plan.models if m.role == "embed")
            gb = sum(m.approx_bytes for m in single) / 2**30
            rows.append(
                ChooserRow(
                    kind="single",
                    label=f"{reasoning.filename} only",
                    sub=f"{gb:.1f} GB · {len(single)} models",
                    detail=tuple(
                        f"{m.filename} ({m.role}, {m.approx_bytes / 2**30:.1f} GB)"
                        for m in single
                    ),
                    why=plan.reason,
                )
            )
    if prep.runtime is not None:
        for m in prep.models:
            rows.append(
                ChooserRow(
                    kind="installed",
                    label=m,
                    sub=f"{prep.runtime} · {prep.sizes.get(m, 0) / 2**30:.1f} GB",
                    detail=(analyze_model(m, prep.sizes.get(m, 0)), f"served by {prep.runtime}"),
                )
            )
    elif prep.have_llamacpp and not prep.have_ollama and not rows:
        rows.append(ChooserRow(kind="start", label="Start llama-server", sub="already installed"))
    if (
        prep.runtime == "llamacpp"
        and prep.have_ollama
        and allow_downloads
    ):
        rows.append(
            ChooserRow(
                kind="switch",
                label="Switch to ollama",
                sub="stops llama-server · lists its models",
                why="ollama and llama.cpp take turns on this machine — never both up",
            )
        )
    return tuple(rows)


def outcome_of(state: SetupState) -> SetupOutcome:
    runtime = None
    if state.started_llamacpp:
        runtime = "llamacpp"
    elif state.prep is not None:
        runtime = state.prep.runtime
    return SetupOutcome(exit=state.outcome or "closed", runtime=runtime)


def _close(state: SetupState, outcome: str) -> SetupState:
    return replace(state, phase="closing", outcome=outcome, operation=None)


def _skip_or_close(state: SetupState) -> SetupState:
    return _close(state, "skipped" if state.exit_kind == "skip" else "closed")


def handle_key(state: SetupState, key: str) -> SetupState:
    if key == "ctrl-c":
        key = "esc"
    if state.phase == "preparation":
        return _skip_or_close(state) if key == "esc" else state
    if state.phase != "chooser":
        return state

    op = state.operation
    if op is None:
        if key in ("up", "k"):
            return replace(state, selected=max(0, state.selected - 1))
        if key in ("down", "j"):
            return replace(state, selected=min(max(len(state.rows) - 1, 0), state.selected + 1))
        if key == "esc":
            return _skip_or_close(state)
        if key == "enter" and state.rows:
            row = state.rows[state.selected]
            if row.kind in ("bundle", "single"):
                return replace(
                    state,
                    operation=Operation("download"),
                    notice=None,
                    retryable=None,
                    stop_download=False,
                )
            if row.kind == "installed":
                return _close(state, "completed")
            if row.kind in ("start", "switch"):
                return replace(state, operation=Operation(row.kind), notice=None, retryable=None)
        if key == "r" and state.retryable in ("start", "switch"):
            return replace(state, operation=Operation(state.retryable), notice=None, retryable=None)
        if key == "c" and state.retryable in ("start", "switch"):
            return replace(state, retryable=None, notice=None)
        return state

    if op.tag == "download":
        if key == "esc":
            return replace(
                state, operation=Operation("confirm_cancel", done=op.done, total=op.total)
            )
        return state
    if op.tag == "confirm_cancel":
        if key in ("left", "h"):
            return replace(state, operation=replace(op, confirm_yes=False))
        if key in ("right", "l"):
            return replace(state, operation=replace(op, confirm_yes=True))
        if key == "enter":
            if op.confirm_yes:
                return replace(
                    state,
                    operation=None,
                    stop_download=True,
                    notice=Notice(
                        "download cancelled — .part files kept; Enter retries with resume"
                    ),
                )
            return replace(state, operation=Operation("download", done=op.done, total=op.total))
        if key == "esc":  # changed our mind: keep downloading
            return replace(state, operation=Operation("download", done=op.done, total=op.total))
        return state
    if op.tag == "confirm_wired":
        if key == "y":
            return replace(state, wired_answer=True, operation=Operation("start"))
        if key == "n":
            return replace(state, wired_answer=False, operation=Operation("start"))
        return state
    return state  # "start": locked, not even Esc (Ctrl-C still quits via the OS)


def handle_event(state: SetupState, event: tuple) -> SetupState:
    tag = event[0]
    if tag == "prep":
        return prep_event(state, *event[1:])
    if tag == "prep_done":
        prep, allow_downloads = event[1], event[2]
        return replace(
            state, phase="chooser", prep=prep, rows=build_rows(prep, allow_downloads),
            allow_downloads=allow_downloads,
        )
    if tag == "switch_done":
        # the pivot completed: fresh survey, chooser rebuilt in place
        prep = event[1]
        return replace(
            state,
            phase="chooser",
            prep=prep,
            rows=build_rows(prep, state.allow_downloads),
            selected=0,
            operation=None,
            notice=None,
            retryable=None,
            started_llamacpp=False,
        )
    if tag == "prep_failed":
        reason = event[1]
        state = prep_event(state, "recommendations", FAILED, reason)
        state = prep_done(state, Preparation(), ())
        return replace(state, notice=Notice(f"preparation failed: {reason}"))
    if tag == "progress":
        op = state.operation
        if op is not None and op.tag == "download":
            return replace(state, operation=replace(op, done=event[1], total=event[2]))
        return state
    if tag == "op_done":
        _, which, ok, reason = event
        if which == "download":
            if not ok:
                return replace(
                    state, operation=None, notice=Notice(reason or "download failed")
                )
            plan = state.prep.plan if state.prep is not None else None
            if plan is not None and getattr(plan, "wired_limit_mb", None):
                return replace(state, operation=Operation("confirm_wired"))
            return replace(state, operation=Operation("start"))
        if which == "start":
            if ok:
                return _close(replace(state, started_llamacpp=True), "completed")
            return replace(
                state,
                operation=None,
                retryable="start",
                notice=Notice(f"{reason}\nr Retry · c Choose another"),
            )
        if which == "switch" and not ok:
            return replace(
                state,
                operation=None,
                retryable="switch",
                notice=Notice(f"{reason}\nr Retry · c Choose another"),
            )
    return state
