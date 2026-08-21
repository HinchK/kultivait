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


# --- RealDriver over the hardware/bootstrap seams -----------------------------

import threading
from io import StringIO

from rich.console import Console

import kultivait.setup_screen as setup_screen
from kultivait.hardware import HardwareProfile
from kultivait.setup_state import Preparation


PROFILE = HardwareProfile("darwin", "Apple M3", True, 48.0)


def _driver(monkeypatch, which=None, **kw):
    d = setup_screen.RealDriver(
        scan=lambda: PROFILE,
        plan=lambda p: kw.get("plan", PLAN),
        probe=lambda: kw.get("runtime"),
        survey=lambda r: kw.get("survey", ([], {})),
        clis=lambda: kw.get("clis", []),
        which=which or (lambda c: None),
    )
    return d


def test_real_driver_prepare_emits_steps_and_survey(monkeypatch):
    driver = _driver(
        monkeypatch,
        which=lambda c: "/bin/llama-server" if c == "llama-server" else "/bin/brew",
        survey=(["qwen3:14b"], {"qwen3:14b": 9_000_000_000}),
        runtime="ollama",
        clis=["claude"],
    )
    events = []
    prep = driver.prepare(lambda *ev: events.append(ev))
    assert ("hardware", "done", "Apple M3 · 48 GB") in events
    assert ("runtime", "done", "ollama") in events
    assert ("survey", "done", "1 found") in events
    assert prep.runtime == "ollama"
    assert prep.models == ("qwen3:14b",)
    assert prep.clis == ("claude",)
    assert prep.have_llamacpp is True and prep.have_brew is True


def test_real_driver_download_forwards_stop_and_throttles_progress(monkeypatch):
    seen = {}

    def fake_download_models(plan, dest, confirm=None, on_progress=None, log=None,
                             stop=None, **k):
        seen["plan"], seen["stop"], seen["confirm"] = plan, stop, confirm("x")
        seen["on_progress"] = on_progress
        on_progress(5, 10)
        return False  # "interrupted" -> op_done False

    monkeypatch.setattr(setup_screen.bootstrap, "download_models", fake_download_models)
    driver = _driver(
        monkeypatch,
        which=lambda c: "/bin/llama-server" if c == "llama-server" else None,
    )
    driver.prepare(lambda *ev: None)
    posts = []
    stop = threading.Event()
    driver.download(single=True, post=posts.append, stop=stop)
    assert seen["stop"] is stop
    assert seen["confirm"] is True  # screen is the consent layer: auto-yes
    assert [m.role for m in seen["plan"].models] == ["reasoning", "embed"]  # single
    assert posts == [
        ("progress", 5, 10),
        ("op_done", "download", False,
         "download stopped — .part files kept; Enter retries with resume"),
    ]
    seen["on_progress"](5, 10)  # within the throttle window: swallowed
    seen["on_progress"](6, 10)  # still within: swallowed
    assert len(posts) == 2
    seen["on_progress"](10, 10)  # completion always posts immediately
    assert posts[-1] == ("progress", 10, 10)


def test_real_driver_download_advisory_when_no_brew(monkeypatch):
    called = []

    def must_not_download(*a, **k):
        called.append("download")
        raise AssertionError("no install path, no download")

    monkeypatch.setattr(setup_screen.bootstrap, "download_models", must_not_download)
    driver = _driver(monkeypatch, which=lambda c: None)
    driver.prepare(lambda *ev: None)
    posts = []
    driver.download(single=False, post=posts.append, stop=threading.Event())
    assert posts == [("op_done", "download", False,
                      "llama.cpp install advisory — see manual steps above")]


def test_real_driver_start_server_resolves_wired_answer(monkeypatch):
    seen = {}

    monkeypatch.setattr(
        setup_screen.bootstrap, "write_artifacts",
        lambda plan, home, gguf: (home / "preset", home / "start.sh"),
    )
    monkeypatch.setattr(
        setup_screen.bootstrap, "offer_wired_limit",
        lambda plan, confirm=None, **k: seen.setdefault("wired", confirm("raise?")),
    )
    monkeypatch.setattr(
        setup_screen.bootstrap, "start_server",
        lambda script, **k: seen.setdefault("started", str(script)) or True,
    )
    driver = _driver(monkeypatch, which=lambda c: "/bin/llama-server" if c == "llama-server" else None)
    driver.prepare(lambda *ev: None)
    posts = []
    driver.start_server(wired=False, post=posts.append)
    assert seen["wired"] is False
    assert seen["started"].endswith("start.sh")
    assert posts == [("op_done", "start", True, "")]


# --- run_setup: the loop, end-to-end with a fake driver and scripted keys -----


class FakeDriver:
    def __init__(self, plan=PLAN, runtime=None, fail_start=0):
        self.plan, self.runtime, self.fail_start = plan, runtime, fail_start
        self.calls = []
        self.stop = None

    def prepare(self, emit):
        emit("hardware", "done", "Apple M3 · 48 GB")
        emit("runtime", "done", self.runtime or "none running")
        return Preparation(
            runtime=self.runtime, plan=self.plan, have_llamacpp=True, have_brew=True,
            profile=PROFILE,
        )

    def download(self, single, post, stop):
        self.calls.append(("download", single))
        self.stop = stop
        post(("progress", 5, 10))
        post(("op_done", "download", True, ""))

    def start_server(self, wired, post):
        self.calls.append(("start", wired))
        if self.fail_start:
            self.fail_start -= 1
            post(("op_done", "start", False, "boom"))
            return
        post(("op_done", "start", True, ""))


def _run(driver, keys, first_run=True):
    console = Console(width=120, file=StringIO(), force_terminal=False)
    from kultivait.keys import ScriptedKeys

    return setup_screen.run_setup(
        driver=driver, keys=ScriptedKeys(keys), first_run=first_run,
        console=console, spawn=lambda fn: fn(), poll_s=0,
    )


def _run_threaded(driver, keys, first_run=True):
    """Real threads + a blocking driver: for flows that only make sense
    while an operation is genuinely in flight (Esc-cancel mid-download)."""
    from kultivait.keys import ScriptedKeys

    console = Console(width=120, file=StringIO(), force_terminal=False)
    return setup_screen.run_setup(
        driver=driver, keys=ScriptedKeys(keys), first_run=first_run,
        console=console, poll_s=0.01,
    )


class CancelableDriver(FakeDriver):
    def download(self, single, post, stop):
        self.calls.append(("download", single))
        self.stop = stop
        post(("progress", 3, 10))
        stop.wait(timeout=5)  # a real multi-GB fetch doesn't finish instantly
        post(("op_done", "download", False, "cancelled"))


def test_run_setup_happy_path_completes():
    driver = FakeDriver()
    outcome = _run(driver, ["enter"])
    assert outcome.exit == "completed"
    assert outcome.runtime == "llamacpp"
    assert driver.calls == [("download", False), ("start", False)]


def test_run_setup_skip_writes_nothing_but_reports_runtime():
    driver = FakeDriver(runtime="ollama")
    outcome = _run(driver, ["esc"])
    assert outcome.exit == "skipped"
    assert outcome.runtime == "ollama"
    assert driver.calls == []


def test_run_setup_re_run_esc_closes():
    outcome = _run(FakeDriver(), ["esc"], first_run=False)
    assert outcome.exit == "closed"


def test_run_setup_cancel_confirmed_stops_the_download():
    driver = CancelableDriver()
    outcome = _run_threaded(driver, ["enter", "esc", "right", "enter", "esc"])
    assert outcome.exit == "skipped"
    assert driver.stop is not None and driver.stop.is_set()
    assert driver.calls == [("download", False)]  # never started the server


def test_run_setup_start_failure_then_retry_completes():
    driver = FakeDriver(fail_start=1)
    # "wait" lets the start-failure event land before "r" is polled
    outcome = _run(driver, ["enter", "wait", "r"])
    assert outcome.exit == "completed"
    assert driver.calls == [("download", False), ("start", False), ("start", False)]


def test_run_setup_forced_runtime_hides_downloads(monkeypatch):
    monkeypatch.setenv("KULTIVAIT_RUNTIME", "ollama")
    driver = FakeDriver()
    outcome = _run(driver, ["esc"])
    assert outcome.exit == "skipped"
    assert driver.calls == []  # no download rows were offered to select


# --- runtime pivots: exclusivity in the driver --------------------------------


def _exclusive_env(monkeypatch, order, *, ollama_up=False, llama_up=False,
                   stop_ollama="down", stop_llama="down", start_ollama="up"):
    r = setup_screen.runtimes
    monkeypatch.setattr(r, "ollama_up", lambda **k: ollama_up)
    monkeypatch.setattr(r, "llama_up", lambda **k: llama_up)
    monkeypatch.setattr(r, "stop_ollama", lambda **k: order.append("stop_ollama") or stop_ollama)
    monkeypatch.setattr(r, "stop_llama", lambda **k: order.append("stop_llama") or stop_llama)
    monkeypatch.setattr(r, "start_ollama", lambda **k: order.append("start_ollama") or start_ollama)


def test_real_driver_prepare_starts_idle_ollama(monkeypatch):
    state = {"up": False}
    monkeypatch.setattr(
        setup_screen.runtimes, "start_ollama",
        lambda **k: state.__setitem__("up", True) or "up",
    )

    def probe():
        return "ollama" if state["up"] else None

    driver = _driver(
        monkeypatch,
        probe=probe,
        which=lambda c: "/bin/ollama" if c == "ollama" else None,
        survey=(["llama3.1:8b"], {"llama3.1:8b": 4_900_000_000}),
    )
    events = []
    prep = driver.prepare(lambda *ev: events.append(ev))
    assert prep.runtime == "ollama"
    assert ("runtime", "done", "ollama (started)") in events
    assert prep.models == ("llama3.1:8b",)


def test_real_driver_prepare_reports_ollama_that_wont_start(monkeypatch):
    monkeypatch.setattr(setup_screen.runtimes, "start_ollama", lambda **k: "failed")
    driver = _driver(
        monkeypatch, probe=lambda: None,
        which=lambda c: "/bin/ollama" if c == "ollama" else None,
    )
    events = []
    prep = driver.prepare(lambda *ev: events.append(ev))
    assert ("runtime", "failed", "ollama installed but would not start") in events
    assert prep.runtime is None


def test_real_driver_start_stops_ollama_before_llama_starts(monkeypatch):
    order = []
    _exclusive_env(monkeypatch, order, ollama_up=True)
    monkeypatch.setattr(
        setup_screen.bootstrap, "write_artifacts",
        lambda plan, home, gguf: (home / "p", home / "s.sh"),
    )
    monkeypatch.setattr(
        setup_screen.bootstrap, "offer_wired_limit", lambda plan, confirm=None, **k: True
    )
    monkeypatch.setattr(
        setup_screen.bootstrap, "start_server",
        lambda script, **k: order.append("start") or True,
    )
    driver = _driver(
        monkeypatch,
        which=lambda c: "/bin/llama-server" if c == "llama-server" else None,
    )
    driver.prepare(lambda *ev: None)
    posts = []
    driver.start_server(wired=False, post=posts.append)
    assert order == ["stop_ollama", "start"]  # verified down BEFORE llama starts
    assert posts == [("op_done", "start", True, "")]


def test_real_driver_start_refuses_when_ollama_wont_stop(monkeypatch):
    order = []
    _exclusive_env(monkeypatch, order, ollama_up=True, stop_ollama="failed")
    monkeypatch.setattr(
        setup_screen.bootstrap, "start_server",
        lambda script, **k: order.append("start") or True,
    )
    driver = _driver(
        monkeypatch,
        which=lambda c: "/bin/llama-server" if c == "llama-server" else None,
    )
    driver.prepare(lambda *ev: None)
    posts = []
    driver.start_server(wired=False, post=posts.append)
    assert "start" not in order  # llama never launched alongside ollama
    assert posts[0][:3] == ("op_done", "start", False)
    assert "ollama" in posts[0][3]


def test_real_driver_switch_stops_llama_then_surveys_ollama(monkeypatch):
    order = []
    _exclusive_env(monkeypatch, order, llama_up=True)
    driver = _driver(
        monkeypatch,
        runtime="llamacpp",  # llama is serving — prepare must not auto-start ollama
        which=lambda c: "/bin/ollama" if c == "ollama" else None,
        survey=(["llama3.1:8b"], {"llama3.1:8b": 4_900_000_000}),
    )
    driver.prepare(lambda *ev: None)
    posts = []
    driver.switch_to_ollama(post=posts.append)
    assert order == ["stop_llama", "start_ollama"]  # llama verified down first
    assert posts[0][0] == "switch_done"
    prep = posts[0][1]
    assert prep.runtime == "ollama"
    assert prep.models == ("llama3.1:8b",)


def test_real_driver_switch_refuses_when_llama_wont_stop(monkeypatch):
    order = []
    _exclusive_env(monkeypatch, order, llama_up=True, stop_llama="failed")
    driver = _driver(
        monkeypatch,
        runtime="llamacpp",  # llama is serving — prepare must not auto-start ollama
        which=lambda c: "/bin/ollama" if c == "ollama" else None,
    )
    driver.prepare(lambda *ev: None)
    posts = []
    driver.switch_to_ollama(post=posts.append)
    assert "start_ollama" not in order  # never both up: ollama never launched
    assert posts == [("op_done", "switch", False,
                      "could not stop llama-server — refusing to start ollama alongside it")]
