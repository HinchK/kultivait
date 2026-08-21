"""setup_screen renderers: pure rich composition, captured to plain text
(the tests/test_tui.py trick). The loop and driver are exercised later in
this file as they land."""

from rich.console import Console

from kultivait.hardware import EMBED_PICK, QWEN3_14B, QWEN3_4B, SetupPlan
from kultivait.setup_state import (
    DONE,
    RUNNING,
    Notice,
    Operation,
    Preparation,
    begin,
    build_rows,
    handle_event,
    handle_key,
    prep_event,
    prep_done,
)
from kultivait.setup_screen import (
    _bar,
    format_transfer,
    render,
    render_closing,
    render_chooser,
    render_preparation,
    visible_window,
)

PLAN = SetupPlan(
    eligible=True,
    reason="Apple M3 with 48GB unified RAM",
    models=(QWEN3_4B, QWEN3_14B, EMBED_PICK),
    ctx=32768,
    wired_limit_mb=None,
)


def _plain(renderable, width=120) -> str:
    console = Console(width=width, force_terminal=False, highlight=False)
    with console.capture() as cap:
        console.print(renderable)
    return cap.get()


def _chooser(first_run=True, plan=PLAN):
    prep = Preparation(runtime=None, plan=plan, have_llamacpp=True, have_brew=True)
    return prep_done(begin(first_run=first_run), prep, build_rows(prep, True))


# --- pure helpers ------------------------------------------------------------


def test_bar_and_transfer_formatting():
    assert _bar(5, 10, 10) == "█" * 5 + "░" * 5
    assert _bar(0, 0, 10) == "░" * 10  # unknown total: all empty
    out = format_transfer([(0.0, 0), (1.0, 5_000_000)], 10_000_000)
    assert "5.0 MB/s" in out
    assert "about" in out  # ETA phrasing
    assert format_transfer([(0.0, 0)], 10) == ""  # one sample: no rate
    assert format_transfer([], 10) == ""


def test_visible_window_clamps_to_rows():
    assert visible_window(0, 6) == (0, 4)
    assert visible_window(5, 6) == (2, 6)
    assert visible_window(3, 3) == (0, 3)


# --- preparation card --------------------------------------------------------


def test_render_preparation_checklist_and_hints():
    state = prep_event(begin(first_run=True), "hardware", DONE, "Apple M3 · 48 GB")
    state = prep_event(state, "runtime", RUNNING)
    out = _plain(render(state))
    assert "Preparing your garden" in out
    assert "✓ Detecting hardware" in out
    assert "Apple M3 · 48 GB" in out
    assert "⠋ Checking for a local runtime" in out
    assert "○ Surveying models" in out
    assert "Esc skip for now" in out
    rerun = prep_event(begin(first_run=False), "hardware", DONE)
    assert "Esc close" in _plain(render(rerun))


# --- chooser card ------------------------------------------------------------


def test_render_chooser_sections_detail_and_hint():
    out = _plain(render(_chooser(), width=120))
    assert "Choose your garden" in out
    assert "AVAILABLE TO DOWNLOAD" in out
    assert "Tuned garden for this Mac" in out
    assert "›" in out  # selection marker
    assert "WHY THIS GARDEN" in out
    assert PLAN.reason in out
    assert "up/down choose · Enter to set up · Esc skip for now" in out


def test_render_chooser_on_this_computer_section():
    prep = Preparation(
        runtime="ollama", models=("qwen3:14b",), sizes={"qwen3:14b": 9_000_000_000},
        plan=PLAN,
    )
    state = prep_done(begin(first_run=True), prep, build_rows(prep, False))
    out = _plain(render(state))
    assert "ON THIS COMPUTER" in out
    assert "qwen3:14b" in out
    assert "AVAILABLE TO DOWNLOAD" not in out


def test_render_chooser_download_state_shows_bar_and_cancel_hint():
    state = handle_key(_chooser(), "enter")
    state = handle_event(state, ("progress", 5, 10))
    out = _plain(render(state, samples=((0.0, 0), (1.0, 5_000_000))))
    assert "Downloading" in out
    assert "█" in out and "░" in out
    assert "50%" in out
    assert "Esc cancel" in out
    assert "up/down choose" not in out  # list locked


def test_render_chooser_cancel_confirm_and_wired_confirm():
    state = handle_key(_chooser(), "enter")
    state = handle_key(state, "esc")
    out = _plain(render(state))
    assert "Cancel the download?" in out
    assert "Yes" in out and "No" in out

    from dataclasses import replace

    wired = replace(PLAN, wired_limit_mb=32768)
    state = handle_key(_chooser(plan=wired), "enter")
    state = handle_event(state, ("op_done", "download", True, ""))
    out = _plain(render(state))
    assert "Raise the GPU memory cap" in out
    assert "sudo" in out


def test_render_chooser_start_and_failure_notice():
    state = handle_key(_chooser(), "enter")
    state = handle_event(state, ("op_done", "download", True, ""))
    out = _plain(render(state))
    assert "Starting llama-server" in out

    state = handle_event(state, ("op_done", "start", False, "did not answer"))
    out = _plain(render(state))
    assert "did not answer" in out
    assert "r Retry · c Choose another" in out


def test_render_chooser_notice_survives_into_idle_chooser():
    state = handle_key(_chooser(), "enter")
    state = handle_event(state, ("op_done", "download", False, "interrupted"))
    out = _plain(render(state))
    assert "interrupted" in out
    assert "up/down choose" in out  # unlocked again


def test_render_closing_card():
    out = _plain(render_closing())
    assert "Finishing onboarding" in out
    assert "writing config" in out


def test_render_dispatches_on_phase():
    assert "Preparing your garden" in _plain(render(begin(first_run=True)))
    closing = handle_key(_chooser(), "esc")  # Esc out of the chooser -> closing
    assert closing.phase == "closing"
    assert "Finishing onboarding" in _plain(render(closing))
