"""setup_screen: rich cards + the interactive loop for the setup flow.

Renderers are pure functions from `setup_state.SetupState` to rich
renderables (capturable without a terminal, like tui.render_survey). The
driver and run_setup loop live here too — added as the plan lands them.
"""

from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

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
