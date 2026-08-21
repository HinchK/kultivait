"""setup_state: the pure screen state machine ported from magnitude's
setup-state.ts. Two groups: preparation/rows/outcome (part 1) and
key/event handling through the download/start lifecycle (part 2)."""

from dataclasses import replace

from kultivait.hardware import EMBED_PICK, QWEN3_14B, QWEN3_4B, SetupPlan
from kultivait.setup_state import (
    DONE,
    FAILED,
    RUNNING,
    ChooserRow,
    Notice,
    Operation,
    Preparation,
    begin,
    build_rows,
    handle_event,
    handle_key,
    outcome_of,
    prep_done,
    prep_event,
)

PLAN = SetupPlan(
    eligible=True,
    reason="Apple M3 with 48GB unified RAM",
    models=(QWEN3_4B, QWEN3_14B, EMBED_PICK),
    ctx=32768,
    wired_limit_mb=None,
)
PLAN_WIRED = replace(PLAN, wired_limit_mb=32768, default_gpu_cap_mb=24576)


# --- part 1: preparation, rows, outcome -------------------------------------


def test_begin_first_run_vs_re_run():
    first = begin(first_run=True)
    assert first.phase == "preparation"
    assert first.exit_kind == "skip"
    assert [s.id for s in first.steps] == [
        "hardware", "runtime", "survey", "recommendations",
    ]
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
    assert state.rows is rows
    assert rows[0].kind == "bundle"
    assert rows[0].label == "Tuned garden for this Mac"
    assert "GB" in rows[0].sub
    assert rows[0].why == PLAN.reason
    assert rows[1].kind == "single"


def test_build_rows_no_downloads_when_runtime_serves():
    prep = Preparation(
        runtime="ollama", models=("qwen3:14b",),
        sizes={"qwen3:14b": 9_000_000_000}, plan=PLAN,
    )
    rows = build_rows(prep, allow_downloads=False)
    assert [r.kind for r in rows] == ["installed"]
    assert rows[0].label == "qwen3:14b"
    assert "GB" in rows[0].sub


def test_build_rows_start_row_when_llamacpp_installed_idle():
    prep = Preparation(runtime=None, plan=PLAN, have_llamacpp=True)
    rows = build_rows(prep, allow_downloads=False)
    assert rows[-1].kind == "start"


def test_build_rows_empty_when_ineligible_and_nothing_running():
    from kultivait.hardware import HardwareProfile, plan as make_plan

    ineligible = make_plan(HardwareProfile("darwin", "Intel Mac", False, 16.0))
    rows = build_rows(Preparation(plan=ineligible), allow_downloads=True)
    assert rows == ()


def test_outcome_of_prefers_started_llamacpp_then_runtime():
    state = prep_done(
        begin(first_run=False),
        Preparation(runtime="ollama", models=("m",), sizes={}, clis=()),
        (),
    )
    assert outcome_of(state).runtime == "ollama"
    state = replace(state, started_llamacpp=True)
    assert outcome_of(state).runtime == "llamacpp"
    bare = prep_done(begin(first_run=True), Preparation(), ())
    assert outcome_of(bare).runtime is None


# --- part 2: keys and the operation lifecycle --------------------------------


def _chooser(first_run=True, plan=PLAN, rows=None, prep=None):
    prep = prep or Preparation(runtime=None, plan=plan, have_llamacpp=True, have_brew=True)
    rows = rows if rows is not None else build_rows(prep, allow_downloads=True)
    return prep_done(begin(first_run=first_run), prep, rows)


def test_movement_clamped_and_vim_keys():
    rows = (ChooserRow("bundle", "a"), ChooserRow("single", "b"), ChooserRow("start", "c"))
    state = _chooser(rows=rows)
    state = handle_key(state, "down")
    assert state.selected == 1
    state = handle_key(state, "j")
    assert state.selected == 2
    state = handle_key(state, "down")  # clamped
    assert state.selected == 2
    state = handle_key(state, "k")
    assert state.selected == 1
    state = handle_key(state, "up")
    assert state.selected == 0
    state = handle_key(state, "up")  # clamped
    assert state.selected == 0


def test_enter_download_row_locks_into_download():
    state = handle_key(_chooser(), "enter")
    assert state.operation == Operation("download")
    assert state.phase == "chooser"


def test_enter_installed_row_goes_straight_to_closing():
    prep = Preparation(runtime="ollama", models=("qwen3:14b",), sizes={}, plan=PLAN)
    state = prep_done(begin(first_run=True), prep, build_rows(prep, allow_downloads=False))
    state = handle_key(state, "enter")
    assert state.phase == "closing"
    assert state.outcome == "completed"
    assert state.started_llamacpp is False


def test_enter_start_row_becomes_start_operation():
    rows = (ChooserRow("start", "Start llama-server"),)
    state = handle_key(_chooser(rows=rows), "enter")
    assert state.operation == Operation("start")


def test_esc_first_run_skips_and_re_run_closes():
    assert handle_key(_chooser(first_run=True), "esc").outcome == "skipped"
    assert handle_key(_chooser(first_run=False), "esc").outcome == "closed"


def test_ctrl_c_behaves_like_esc():
    assert handle_key(_chooser(first_run=True), "ctrl-c").outcome == "skipped"


def test_esc_during_preparation_exits():
    state = prep_event(begin(first_run=True), "hardware", DONE, "Apple M3")
    assert handle_key(state, "esc").outcome == "skipped"


def test_esc_during_download_needs_confirmation_to_stop():
    state = handle_key(_chooser(), "enter")  # start download
    state = handle_event(state, ("progress", 5, 10))
    assert state.operation.done == 5 and state.operation.total == 10
    state = handle_key(state, "esc")  # ask, not stop
    assert state.operation.tag == "confirm_cancel"
    assert state.operation.confirm_yes is False  # default No — cancel is opt-in
    state = handle_key(state, "right")  # -> Yes
    assert state.operation.confirm_yes is True
    state = handle_key(state, "left")  # back to No
    assert state.operation.confirm_yes is False
    state = handle_key(state, "right")
    state = handle_key(state, "enter")
    assert state.operation is None
    assert state.stop_download is True
    assert "resume" in state.notice.message


def test_cancel_denied_resumes_download_display():
    state = handle_key(_chooser(), "enter")
    state = handle_event(state, ("progress", 5, 10))
    state = handle_key(state, "esc")
    state = handle_key(state, "enter")  # confirm default No
    assert state.operation == Operation("download", done=5, total=10)
    assert state.stop_download is False


def test_cancel_esc_back_keeps_download():
    state = handle_key(_chooser(), "enter")
    state = handle_key(state, "esc")
    state = handle_key(state, "esc")  # Esc inside the confirm = keep downloading
    assert state.operation.tag == "download"


def test_download_ok_without_wired_limit_goes_to_start():
    state = handle_key(_chooser(), "enter")
    state = handle_event(state, ("op_done", "download", True, ""))
    assert state.operation == Operation("start")


def test_download_ok_with_wired_limit_asks_then_starts():
    state = handle_key(_chooser(plan=PLAN_WIRED), "enter")
    state = handle_event(state, ("op_done", "download", True, ""))
    assert state.operation.tag == "confirm_wired"
    state = handle_key(state, "y")
    assert state.operation == Operation("start")
    assert state.wired_answer is True
    state = handle_event(state, ("op_done", "download", True, ""))
    state = handle_key(state, "n")
    assert state.wired_answer is False
    assert state.operation == Operation("start")


def test_start_ok_completes_with_llamacpp_runtime():
    state = handle_key(_chooser(), "enter")
    state = handle_event(state, ("op_done", "download", True, ""))
    state = handle_event(state, ("op_done", "start", True, ""))
    assert state.phase == "closing"
    assert state.outcome == "completed"
    assert state.started_llamacpp is True
    assert outcome_of(state).runtime == "llamacpp"


def test_start_failure_offers_retry_or_choose():
    state = handle_key(_chooser(), "enter")
    state = handle_event(state, ("op_done", "download", True, ""))
    state = handle_event(state, ("op_done", "start", False, "boom"))
    assert state.operation is None
    assert state.retryable == "start"
    assert "r Retry" in state.notice.message
    state = handle_key(state, "r")
    assert state.operation == Operation("start")
    assert state.retryable is None
    state = handle_event(state, ("op_done", "start", False, "boom2"))
    state = handle_key(state, "c")
    assert state.retryable is None and state.operation is None


def test_download_failure_unlocks_chooser_with_notice():
    state = handle_key(_chooser(), "enter")
    state = handle_event(state, ("op_done", "download", False, "interrupted"))
    assert state.operation is None
    assert state.notice == Notice("interrupted")
    assert state.retryable is None


def test_keys_ignored_while_starting():
    state = handle_key(_chooser(), "enter")
    state = handle_event(state, ("op_done", "download", True, ""))
    assert state.operation == Operation("start")
    assert handle_key(state, "down").selected == 0
    assert handle_key(state, "esc").phase == "chooser"  # not even Esc


def test_prep_failed_lands_in_empty_chooser_with_notice():
    state = begin(first_run=True)
    state = handle_event(state, ("prep_failed", "scan blew up"))
    assert state.phase == "chooser"
    assert state.rows == ()
    assert "scan blew up" in state.notice.message
    assert handle_key(state, "esc").outcome == "skipped"


def test_prep_done_event_builds_rows_itself():
    state = begin(first_run=True)
    prep = Preparation(runtime="ollama", models=("m",), sizes={"m": 1}, plan=PLAN)
    state = handle_event(state, ("prep_done", prep, False))
    assert state.phase == "chooser"
    assert [r.kind for r in state.rows] == ["installed"]
