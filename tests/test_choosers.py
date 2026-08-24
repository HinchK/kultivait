import argparse
import json
import threading
import time
from pathlib import Path
import pytest

from kultivait.cli import (
    _prompt_choice,
    _render_route_menu,
    _start_tty_watcher,
    cmd_choose,
)
from kultivait.effort import EffortPlan
from kultivait.preprocessor import AnalysisResult, TargetFit
from kultivait.tollbooth import (
    RouteOption,
    TollTicket,
    TollboothQueue,
    build_route_menu,
)


def test_presence_heartbeat_file(tmp_path):
    pres_file = tmp_path / "presence.json"
    queue = TollboothQueue(presence_path=pres_file, presence_timeout_s=5.0)

    # Missing file and no memory presence -> False
    assert queue.has_presence() is False

    # Fresh heartbeat file -> True
    pres_file.write_text(json.dumps({"ts": time.time(), "surface": "choose"}))
    assert queue.has_presence() is True

    # Stale heartbeat file -> False
    pres_file.write_text(json.dumps({"ts": time.time() - 10.0, "surface": "choose"}))
    assert queue.has_presence() is False

    # In-memory registration overrides stale file
    queue.register_presence("tty")
    assert queue.has_presence() is True


def test_choose_no_pending_tolls(tmp_path, capsys):
    q_file = tmp_path / "pending_tolls.jsonl"
    pres_file = tmp_path / "presence.json"
    ans_dir = tmp_path / "toll_answers"

    # 1. Non-existent file
    cmd_choose(queue_path=q_file, answers_dir=ans_dir, presence_path=pres_file)
    assert pres_file.exists()  # Touched heartbeat

    # 2. Empty file
    q_file.write_text("")
    cmd_choose(queue_path=q_file, answers_dir=ans_dir, presence_path=pres_file)


def test_render_route_menu():
    opt1 = RouteOption(
        target="claude",
        display_name="Claude",
        fit=0.85,
        effort=EffortPlan(canonical="deep", cli_flags=["--effort", "high"]),
        estimated_cost_usd=0.015,
        prompt_to_send="rewrite prompt",
    )
    opt2 = RouteOption(
        target="local",
        display_name="Local (qwen3.5:4b)",
        fit=0.0,
        effort=EffortPlan(canonical="balanced", cli_flags=[]),
        estimated_cost_usd=0.0,
        prompt_to_send="orig prompt",
    )
    ticket = TollTicket(
        ticket_id="toll-xyz",
        fingerprint="fp-123",
        created_at=time.time(),
        timeout_s=60.0,
        options=[opt1, opt2],
        default_auto_choice="auto:local",
        original_prompt="How do I refactor the compiler backend?",
        task_type="architecture",
    )

    rendered = _render_route_menu(ticket)
    assert "toll-xyz" in rendered
    assert "Claude" in rendered
    assert "0.85" in rendered
    assert "deep" in rendered
    assert "--effort high" in rendered
    assert "Local (qwen3.5:4b)" in rendered
    assert "keep-it-local" in rendered
    assert "How do I refactor the compiler backend?" in rendered


def test_prompt_choice_navigation():
    # Direct numerical choice
    assert _prompt_choice(3, input_fn=lambda _: "1") == (0, None)
    assert _prompt_choice(3, input_fn=lambda _: "2") == (1, None)

    # Quit choices
    assert _prompt_choice(3, input_fn=lambda _: "q") is None
    assert _prompt_choice(3, input_fn=lambda _: "quit") is None

    # Effort override flow
    inputs = iter(["e", "2", "3"])  # 'e' -> option 2 -> level 3 (deep)
    assert _prompt_choice(3, input_fn=lambda _: next(inputs)) == (1, "deep")

    # Garbage then valid
    inputs_garbage = iter(["garbage", "5", "3"])
    assert _prompt_choice(3, input_fn=lambda _: next(inputs_garbage)) == (2, None)


def test_choose_command_frontier_selection(tmp_path):
    q_file = tmp_path / "pending_tolls.jsonl"
    pres_file = tmp_path / "presence.json"
    ans_dir = tmp_path / "toll_answers"

    ticket_data = {
        "ticket_id": "toll-cli-1",
        "fingerprint": "fp-cli-1",
        "created_at": time.time(),
        "timeout_s": 60.0,
        "default_auto_choice": "auto:local",
        "original_prompt": "Fix race condition",
        "task_type": "debugging",
        "options": [
            {
                "target": "claude",
                "display_name": "Claude",
                "fit": 0.85,
                "effort": "balanced",
                "cli_flags": ["--effort", "medium"],
                "estimated_cost_usd": 0.02,
            },
            {
                "target": "local",
                "display_name": "Local",
                "fit": 0.0,
                "effort": "balanced",
                "cli_flags": [],
                "estimated_cost_usd": 0.0,
            },
        ],
    }
    q_file.write_text(json.dumps(ticket_data) + "\n")

    # User enters option 1 (Claude)
    cmd_choose(
        queue_path=q_file,
        answers_dir=ans_dir,
        presence_path=pres_file,
        input_fn=lambda _: "1",
    )

    ans_file = ans_dir / "toll-cli-1.json"
    assert ans_file.exists()
    ans = json.loads(ans_file.read_text())
    assert ans["choice"] == "human:frontier:claude"
    assert ans["effort_canonical"] is None


def test_choose_command_effort_override_selection(tmp_path):
    q_file = tmp_path / "pending_tolls.jsonl"
    pres_file = tmp_path / "presence.json"
    ans_dir = tmp_path / "toll_answers"

    ticket_data = {
        "ticket_id": "toll-cli-2",
        "fingerprint": "fp-cli-2",
        "created_at": time.time(),
        "timeout_s": 60.0,
        "default_auto_choice": "auto:local",
        "original_prompt": "Refactor architecture",
        "task_type": "architecture",
        "options": [
            {
                "target": "codex",
                "display_name": "Codex",
                "fit": 0.90,
                "effort": "balanced",
                "cli_flags": ["-c", "model_reasoning_effort=medium"],
                "estimated_cost_usd": 0.01,
            },
            {
                "target": "local",
                "display_name": "Local",
                "fit": 0.0,
                "effort": "balanced",
                "cli_flags": [],
                "estimated_cost_usd": 0.0,
            },
        ],
    }
    q_file.write_text(json.dumps(ticket_data) + "\n")

    # User enters 'e', option '1', effort 'deep' (3)
    inputs = iter(["e", "1", "deep"])
    cmd_choose(
        queue_path=q_file,
        answers_dir=ans_dir,
        presence_path=pres_file,
        input_fn=lambda _: next(inputs),
    )

    ans_file = ans_dir / "toll-cli-2.json"
    assert ans_file.exists()
    ans = json.loads(ans_file.read_text())
    assert ans["choice"] == "human:frontier:codex"
    assert ans["effort_canonical"] == "deep"


def test_hold_ticket_woken_by_cross_process_answer_file(tmp_path):
    q_file = tmp_path / "pending_tolls.jsonl"
    pres_file = tmp_path / "presence.json"
    ans_dir = tmp_path / "toll_answers"

    queue = TollboothQueue(
        queue_path=q_file,
        presence_path=pres_file,
        answers_dir=ans_dir,
        default_timeout_s=5.0,
        enabled=True,
    )
    queue.register_presence("choose")

    ticket = TollTicket(
        ticket_id="toll-cross-1",
        fingerprint="fp-cross-1",
        created_at=time.time(),
        timeout_s=5.0,
        options=[],
        default_auto_choice="auto:local",
    )

    def write_answer_after_delay():
        time.sleep(0.05)
        ans_dir.mkdir(parents=True, exist_ok=True)
        (ans_dir / "toll-cross-1.json").write_text(
            json.dumps({"choice": "codex", "effort_canonical": "deep", "ts": time.time()})
        )

    t = threading.Thread(target=write_answer_after_delay)
    t.start()

    choice, mark, override = queue.hold_ticket(ticket)
    t.join()

    assert choice == "human:frontier:codex"
    assert mark == "answered"
    assert override == "deep"
    assert not (ans_dir / "toll-cross-1.json").exists()  # Answer file was consumed

    # Sticky check on second call
    ticket2 = TollTicket(
        ticket_id="toll-cross-2",
        fingerprint="fp-cross-1",
        created_at=time.time(),
        timeout_s=5.0,
        options=[],
        default_auto_choice="auto:local",
    )
    choice2, mark2, override2 = queue.hold_ticket(ticket2)
    assert choice2 == "human:frontier:codex"
    assert mark2 == "sticky"
    assert override2 == "deep"


def test_serve_tty_watcher_in_process_answering(tmp_path):
    q_file = tmp_path / "pending_tolls.jsonl"
    queue = TollboothQueue(
        queue_path=q_file,
        default_timeout_s=5.0,
        enabled=True,
    )
    queue.register_presence("tty")

    # Start watcher with mock input choosing option 1
    watcher = _start_tty_watcher(queue, poll_interval=0.01, input_fn=lambda _: "1")

    opt = RouteOption(
        target="claude",
        display_name="Claude",
        fit=0.80,
        effort=EffortPlan(canonical="balanced"),
        estimated_cost_usd=0.01,
        prompt_to_send="test",
    )
    ticket = TollTicket(
        ticket_id="toll-watch-1",
        fingerprint="fp-watch-1",
        created_at=time.time(),
        timeout_s=5.0,
        options=[opt],
        default_auto_choice="auto:local",
    )

    choice, mark, override = queue.hold_ticket(ticket)
    assert choice == "human:frontier:claude"
    assert mark == "answered"
    assert override is None


def test_serve_tty_watcher_disabled_kill_switch(tmp_path):
    queue = TollboothQueue(
        enabled=False,
    )
    watcher = _start_tty_watcher(queue, poll_interval=0.01, input_fn=lambda _: "1")

    ticket = TollTicket(
        ticket_id="toll-watch-disabled",
        fingerprint="fp-watch-disabled",
        created_at=time.time(),
        timeout_s=5.0,
        options=[],
        default_auto_choice="auto:local",
    )

    choice, mark, override = queue.hold_ticket(ticket)
    assert choice == "auto:local"
    assert mark == "skipped"
