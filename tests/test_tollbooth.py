import asyncio
import json
import time
from pathlib import Path
import pytest

from kultivait.effort import EffortPlan, resolve_effort
from kultivait.preprocessor import AnalysisResult, TargetFit
from kultivait.tollbooth import (
    RouteOption,
    TollTicket,
    TollboothQueue,
    build_route_menu,
    resolve_auto_policy,
)


def test_route_option_and_toll_ticket_dataclasses():
    effort = EffortPlan(canonical="balanced", cli_flags=["--effort", "medium"])
    option = RouteOption(
        target="claude",
        display_name="Claude",
        fit=0.80,
        effort=effort,
        estimated_cost_usd=0.015,
        prompt_to_send="rewritten prompt",
    )
    assert option.target == "claude"
    assert option.display_name == "Claude"
    assert option.fit == 0.80
    assert option.effort.canonical == "balanced"
    assert option.estimated_cost_usd == 0.015
    assert option.prompt_to_send == "rewritten prompt"

    ticket = TollTicket(
        ticket_id="toll-1234",
        fingerprint="fp-abcd",
        created_at=1000.0,
        timeout_s=60.0,
        options=[option],
        default_auto_choice="auto:local",
        original_prompt="original prompt",
        task_type="architecture",
    )
    assert ticket.ticket_id == "toll-1234"
    assert ticket.fingerprint == "fp-abcd"
    assert len(ticket.options) == 1
    assert ticket.default_auto_choice == "auto:local"


def test_build_route_menu_ranking_total_order():
    target_fits = [
        TargetFit(target="claude", fit=0.90, effort="high"),
        TargetFit(target="codex", fit=0.90, effort="high"),
        TargetFit(target="agy", fit=0.70, effort="medium"),
        TargetFit(target="gemini", fit=0.60, effort="low"),
    ]
    installed = ["claude", "codex", "opencode", "agy", "gemini"]
    analysis = AnalysisResult(
        task_type="architecture",
        complexity=8,
        signals=["multi-file"],
        subtask_candidates=["task1"],
    )
    pricing = {
        "claude": (3.0, 15.0),    # $18.00 / Mtok
        "codex": (1.25, 10.0),    # $11.25 / Mtok
        "opencode": (3.0, 15.0),  # $18.00 / Mtok
        "agy": (1.25, 10.0),      # $11.25 / Mtok
        "gemini": (1.25, 10.0),   # $11.25 / Mtok
    }

    options = build_route_menu(
        target_fits=target_fits,
        installed_clis=installed,
        analysis=analysis,
        rewrite="Rewritten for frontier",
        original_prompt="Original prompt",
        local_tier_name="qwen3.5:4b",
        pricing=pricing,
    )

    # Must produce top 3 installed frontier CLIs + 1 keep-it-local anchor
    assert len(options) == 4

    # Ranking check:
    # 1. codex vs claude: both fit=0.90, both architect role, but codex price ($11.25) < claude ($18.00) -> codex #1, claude #2
    # 2. agy (fit=0.70) vs opencode (fit=0.0) -> agy #3
    # 3. local anchor is #4
    targets = [opt.target for opt in options]
    assert targets == ["codex", "claude", "agy", "local"]

    assert options[0].target == "codex"
    assert options[0].fit == 0.90
    assert options[0].prompt_to_send == "Rewritten for frontier"

    assert options[1].target == "claude"
    assert options[1].fit == 0.90

    assert options[2].target == "agy"
    assert options[2].fit == 0.70

    local_opt = options[3]
    assert local_opt.target == "local"
    assert local_opt.display_name == "Local (qwen3.5:4b)"
    assert local_opt.fit == 0.0
    assert local_opt.estimated_cost_usd == 0.0
    assert local_opt.prompt_to_send == "Original prompt"


def test_build_route_menu_capability_match_tie_breaker():
    target_fits = [
        TargetFit(target="claude", fit=0.80, effort="medium"),
        TargetFit(target="agy", fit=0.80, effort="medium"),
    ]
    # For docs_lookup, docs role (agy) matches before architect role (claude)
    analysis = AnalysisResult(
        task_type="docs_lookup",
        complexity=3,
        signals=[],
    )
    pricing = {
        "claude": (1.0, 1.0),  # equal price
        "agy": (1.0, 1.0),
    }
    options = build_route_menu(
        target_fits=target_fits,
        installed_clis=["claude", "agy"],
        analysis=analysis,
        rewrite="Search docs",
        original_prompt="docs query",
        local_tier_name="qwen3.5:4b",
        pricing=pricing,
    )
    targets = [opt.target for opt in options]
    assert targets == ["agy", "claude", "local"]


def test_auto_policy_resolution():
    effort = EffortPlan(canonical="balanced", cli_flags=[])
    frontier_opt = RouteOption(
        target="claude",
        display_name="Claude",
        fit=0.80,
        effort=effort,
        estimated_cost_usd=0.01,
        prompt_to_send="rewritten",
    )
    local_opt = RouteOption(
        target="local",
        display_name="Local (qwen3.5:4b)",
        fit=0.0,
        effort=effort,
        estimated_cost_usd=0.0,
        prompt_to_send="orig",
    )
    options = [frontier_opt, local_opt]

    # When local tier is capable -> auto:local
    assert resolve_auto_policy(options, local_serving_capable=True) == "auto:local"

    # When local tier cannot serve -> top frontier
    assert resolve_auto_policy(options, local_serving_capable=False) == "auto:frontier:claude"


def test_presence_tracking():
    queue = TollboothQueue(presence_timeout_s=10.0)
    assert queue.has_presence() is False

    queue.register_presence("tty")
    assert queue.has_presence() is True
    assert queue.has_presence(timeout_s=300.0) is True

    # After simulated time lapse beyond threshold
    queue._last_presence_ts = time.time() - 20.0
    assert queue.has_presence() is False
    assert queue.has_presence(timeout_s=30.0) is True


def test_hold_ticket_kill_switch():
    queue = TollboothQueue(enabled=False)
    ticket = TollTicket(
        ticket_id="toll-1",
        fingerprint="fp-1",
        created_at=time.time(),
        timeout_s=60.0,
        options=[],
        default_auto_choice="auto:local",
    )
    choice, mark, override = queue.hold_ticket(ticket)
    assert choice == "auto:local"
    assert mark == "skipped"
    assert override is None


def test_hold_ticket_no_presence_immediate_auto_policy(tmp_path):
    queue = TollboothQueue(enabled=True, queue_path=tmp_path / "pending_tolls.jsonl")
    assert queue.has_presence() is False

    ticket = TollTicket(
        ticket_id="toll-1",
        fingerprint="fp-1",
        created_at=time.time(),
        timeout_s=60.0,
        options=[],
        default_auto_choice="auto:local",
    )
    start = time.time()
    choice, mark, override = queue.hold_ticket(ticket)
    duration = time.time() - start

    assert duration < 0.1  # Immediate, zero wait
    assert choice == "auto:local"
    assert mark == "expired"
    assert override is None


def test_hold_ticket_answered_and_sticky_fingerprint(tmp_path):
    queue = TollboothQueue(
        enabled=True,
        queue_path=tmp_path / "pending_tolls.jsonl",
        sticky_ttl_s=3600.0,
    )
    queue.register_presence("tty")

    ticket = TollTicket(
        ticket_id="toll-100",
        fingerprint="fp-sticky",
        created_at=time.time(),
        timeout_s=5.0,
        options=[],
        default_auto_choice="auto:local",
    )

    # Background answering thread
    def answer_after_delay():
        time.sleep(0.05)
        queue.answer_ticket("toll-100", "claude")

    import threading
    t = threading.Thread(target=answer_after_delay)
    t.start()

    choice, mark, override = queue.hold_ticket(ticket)
    t.join()

    assert choice == "human:frontier:claude"
    assert mark == "answered"
    assert override is None

    # Second request with same fingerprint must be sticky
    ticket2 = TollTicket(
        ticket_id="toll-101",
        fingerprint="fp-sticky",
        created_at=time.time(),
        timeout_s=5.0,
        options=[],
        default_auto_choice="auto:local",
    )
    choice2, mark2, override2 = queue.hold_ticket(ticket2)
    assert choice2 == "human:frontier:claude"
    assert mark2 == "sticky"
    assert override2 is None


def test_hold_ticket_timeout_expires(tmp_path):
    queue = TollboothQueue(
        enabled=True,
        queue_path=tmp_path / "pending_tolls.jsonl",
    )
    queue.register_presence("tty")

    ticket = TollTicket(
        ticket_id="toll-timeout",
        fingerprint="fp-timeout",
        created_at=time.time(),
        timeout_s=0.05,  # short 50ms timeout for test
        options=[],
        default_auto_choice="auto:local",
    )

    choice, mark, override = queue.hold_ticket(ticket)
    assert choice == "auto:local"
    assert mark == "expired"
    assert override is None


def test_answer_ticket_late_records_counterfactual(tmp_path):
    queue = TollboothQueue(
        enabled=True,
        queue_path=tmp_path / "pending_tolls.jsonl",
    )
    # Answering an unknown / expired ticket
    success = queue.answer_ticket("toll-nonexistent", "codex")
    assert success is False
    assert len(queue._counterfactuals) == 1
    assert queue._counterfactuals[0]["ticket_id"] == "toll-nonexistent"
    assert queue._counterfactuals[0]["choice"] == "human:frontier:codex"


def test_async_hold_ticket(tmp_path):
    async def run_test():
        queue = TollboothQueue(
            enabled=True,
            queue_path=tmp_path / "pending_tolls.jsonl",
        )
        queue.register_presence("tty")

        ticket = TollTicket(
            ticket_id="toll-async",
            fingerprint="fp-async",
            created_at=time.time(),
            timeout_s=5.0,
            options=[],
            default_auto_choice="auto:local",
        )

        async def delayed_answer():
            await asyncio.sleep(0.05)
            queue.answer_ticket("toll-async", "human:local")

        asyncio.create_task(delayed_answer())
        choice, mark, override = await queue.hold_ticket_async(ticket)

        assert choice == "human:local"
        assert mark == "answered"
        assert override is None

    asyncio.run(run_test())


def test_queue_file_stateless_cleanup(tmp_path):
    q_file = tmp_path / "pending_tolls.jsonl"
    q_file.write_text('{"ticket_id": "stale_from_previous_crash"}\n')

    # Initializing queue unlinks stale file
    queue = TollboothQueue(queue_path=q_file)
    assert not q_file.exists()


def test_mixed_menu_capability_filter_and_cash_annotations():
    target_fits = [
        TargetFit(target="claude", fit=0.90, effort="high"),
        TargetFit(target="openai", fit=0.0, effort="high"),
    ]
    candidate_targets = ["claude", "codex", "openai", "anthropic"]
    target_kinds = {
        "claude": "cli",
        "codex": "cli",
        "openai": "api",
        "anthropic": "api",
    }
    pricing = {
        "claude": (3.0, 15.0),
        "codex": (1.25, 10.0),
        "openai": (2.5, 10.0),
        "anthropic": (3.0, 15.0),
    }

    # Case 1: Non-tool request -> includes CLIs and APIs
    menu_no_tools = build_route_menu(
        target_fits=target_fits,
        candidate_targets=candidate_targets,
        target_kinds=target_kinds,
        has_tools=False,
        pricing=pricing,
        rewrite="Rewrite",
        original_prompt="Orig",
    )
    targets_no_tools = [opt.target for opt in menu_no_tools]
    assert "claude" in targets_no_tools
    assert "openai" in targets_no_tools
    claude_opt = next(opt for opt in menu_no_tools if opt.target == "claude")
    assert claude_opt.cash_annotation == "subscription: $0"
    assert claude_opt.kind == "cli"

    openai_opt = next(opt for opt in menu_no_tools if opt.target == "openai")
    assert "metered:" in openai_opt.cash_annotation
    assert openai_opt.kind == "api"

    # Case 2: Tool-bearing request -> capability filter drops CLIs
    menu_tools = build_route_menu(
        target_fits=target_fits,
        candidate_targets=candidate_targets,
        target_kinds=target_kinds,
        has_tools=True,
        pricing=pricing,
        rewrite="Rewrite",
        original_prompt="Orig",
    )
    targets_tools = [opt.target for opt in menu_tools]
    assert "claude" not in targets_tools
    assert "codex" not in targets_tools
    assert "openai" in targets_tools
    assert "anthropic" in targets_tools
    assert "local" in targets_tools


def test_presence_probe_filtering_in_menu():
    candidate_targets = ["openai", "anthropic", "openrouter"]
    target_kinds = {t: "api" for t in candidate_targets}
    probed_status = {
        "openai": True,
        "anthropic": False,  # failed probe
        "openrouter": True,
    }

    menu = build_route_menu(
        target_fits=[],
        candidate_targets=candidate_targets,
        target_kinds=target_kinds,
        probed_status=probed_status,
        rewrite="Rewrite",
        original_prompt="Orig",
    )
    targets = [opt.target for opt in menu]
    assert "anthropic" not in targets
    assert "openai" in targets
    assert "openrouter" in targets
    assert "local" in targets


def test_resolve_auto_policy_fail_fast_when_nothing_capable():
    # Only local in options, but local is not serving capable
    options = [
        RouteOption(
            target="local",
            display_name="Local",
            fit=0.0,
            effort=resolve_effort(5, "code", "local"),
            estimated_cost_usd=0.0,
            prompt_to_send="orig",
            kind="local",
        )
    ]
    with pytest.raises(RuntimeError, match="no capable backend"):
        resolve_auto_policy(options, local_serving_capable=False)

