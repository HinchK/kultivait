import argparse
import json
import pytest
from pathlib import Path

from kultivait.backends import Backend, Completion
from kultivait.capability_eval import (
    EvalArtifact,
    TaskCase,
    format_eval_summary,
    get_family,
    judge_transcript,
    load_corpus,
    run_capability_eval,
    run_task,
    select_cross_family_judge,
)
from kultivait.cli import cmd_eval
from kultivait.ledger import Ledger


class MockTargetBackend:
    def __init__(self, name: str, success_on_tools: bool = True):
        self.name = name
        self.success_on_tools = success_on_tools
        self.calls = []
        self.local = False
        self.supports_tools = True

    def complete(self, messages, tools=None, canonical_effort="balanced", **kwargs):
        self.calls.append({"messages": messages, "tools": tools, "effort": canonical_effort})
        last_msg = messages[-1]

        # First turn: model issues tool call
        if last_msg["role"] == "user":
            if self.success_on_tools:
                return Completion(
                    text="Searching code to locate bug.",
                    tokens_in=100,
                    tokens_out=25,
                    cost_usd=0.001,
                    local=False,
                    tool_calls=[
                        {
                            "id": "call_search_1",
                            "type": "function",
                            "function": {"name": "search_code", "arguments": '{"query": "calculate_tax"}'},
                        }
                    ],
                )
            else:
                return Completion(
                    text="I don't know how to use tools.",
                    tokens_in=50,
                    tokens_out=15,
                    cost_usd=0.0005,
                    local=False,
                    tool_calls=[],
                )

        # Second turn (tool response returned): model applies patch
        if last_msg["role"] == "tool":
            if "search_code" in last_msg.get("name", ""):
                return Completion(
                    text="Found the bug. Applying safe patch for tax calculation.",
                    tokens_in=150,
                    tokens_out=40,
                    cost_usd=0.0015,
                    local=False,
                    tool_calls=[
                        {
                            "id": "call_patch_1",
                            "type": "function",
                            "function": {"name": "apply_patch", "arguments": '{"path": "src/billing/tax.py", "replacement": "if not rates: return 0.0"}'},
                        }
                    ],
                )
            else:
                return Completion(
                    text="Patch applied and verified.",
                    tokens_in=180,
                    tokens_out=20,
                    cost_usd=0.0018,
                    local=False,
                    tool_calls=[],
                )


class MockJudgeBackend:
    def __init__(self, name: str = "openai_judge", score: float = 1.0, passed: bool = True):
        self.name = name
        self.score = score
        self.passed = passed
        self.calls = []
        self.local = False
        self.supports_tools = True

    def complete(self, messages, **kwargs):
        self.calls.append(messages)
        content = json.dumps({
            "score": self.score,
            "passed": self.passed,
            "reasoning": f"Judge {self.name} evaluated rubric: criteria satisfied.",
        })
        return Completion(
            text=content,
            tokens_in=300,
            tokens_out=50,
            cost_usd=0.002,
            local=False,
        )


def test_load_corpus():
    tasks = load_corpus()
    assert len(tasks) >= 3
    t0 = tasks[0]
    assert isinstance(t0, TaskCase)
    assert t0.id == "file_search_and_edit"
    assert len(t0.tools) >= 2
    assert "rubric" in t0.__dict__
    assert t0.rubric.get("version") == "v1"


def test_get_family():
    assert get_family("anthropic") == "anthropic"
    assert get_family("claude-3-7-sonnet") == "anthropic"
    assert get_family("openai") == "openai"
    assert get_family("gpt-4o") == "openai"
    assert get_family("codex") == "openai"
    assert get_family("openrouter") == "openrouter"
    assert get_family("qwen3.5:4b") == "local"
    assert get_family("llama3.1:8b") == "local"


def test_select_cross_family_judge_enforcement():
    backends = {
        "anthropic": MockTargetBackend("anthropic"),
        "openai": MockJudgeBackend("openai"),
        "local": MockTargetBackend("local"),
    }

    # 1. Target is anthropic -> judge MUST NOT be anthropic (should pick openai)
    j_name, j_backend = select_cross_family_judge("anthropic", backends)
    assert j_name == "openai"
    assert get_family(j_name) != get_family("anthropic")

    # 2. Target is openai -> judge MUST NOT be openai (should pick anthropic)
    j_name2, j_backend2 = select_cross_family_judge("openai", backends)
    assert j_name2 == "anthropic"
    assert get_family(j_name2) != get_family("openai")

    # 3. Violation when no cross-family judge exists
    single_family_backends = {
        "anthropic": MockTargetBackend("anthropic"),
        "claude-opus": MockJudgeBackend("claude-opus"),
    }
    with pytest.raises(ValueError, match="No cross-family judge available"):
        select_cross_family_judge("anthropic", single_family_backends)


def test_run_task_multi_turn_and_ledger_tagging(tmp_path):
    tasks = load_corpus()
    task = tasks[0]
    backend = MockTargetBackend("anthropic", success_on_tools=True)
    ledger_file = tmp_path / "ledger.jsonl"
    ledger = Ledger(ledger_file)

    transcript, tool_calls, tokens_in, tokens_out, cost_usd = run_task(
        backend=backend,
        task=task,
        effort_level="deep",
        ledger=ledger,
        target_name="anthropic",
    )

    # Multi-turn verification
    assert len(tool_calls) == 2  # search_code and apply_patch
    assert transcript[-1]["role"] == "assistant"
    assert "Patch applied" in transcript[-1]["content"]

    # Ledger tag verification (segregated spend)
    assert ledger_file.exists()
    lines = [json.loads(line) for line in ledger_file.read_text().splitlines() if line.strip()]
    assert len(lines) >= 2
    for line in lines:
        assert line.get("tag") == "benchmark"
        assert line.get("task_id") == task.id
        assert line.get("effort") == "deep"


def test_judge_transcript():
    judge = MockJudgeBackend("openai", score=0.95, passed=True)
    transcript = [
        {"role": "user", "content": "Fix tax bug"},
        {"role": "assistant", "content": "Calling search_code", "tool_calls": [{"function": {"name": "search_code"}}]},
        {"role": "tool", "content": "Tax calculation source code"},
        {"role": "assistant", "content": "Calling apply_patch", "tool_calls": [{"function": {"name": "apply_patch"}}]},
    ]
    rubric = {"version": "v1", "criteria": ["search", "patch"], "passing_score": 0.8}

    passed, score, reasoning = judge_transcript(judge, transcript, rubric, "Fix tax calculation")
    assert passed is True
    assert score == 0.95
    assert "criteria satisfied" in reasoning


def test_run_capability_eval_accuracy_only(tmp_path):
    tasks = load_corpus()[:2]
    backends = {
        "anthropic": MockTargetBackend("anthropic", success_on_tools=True),
        "openai": MockJudgeBackend("openai", score=1.0, passed=True),
    }

    artifacts_dir = tmp_path / "artifacts"
    summary = run_capability_eval(
        backends=backends,
        targets=["anthropic"],
        efforts=["fast", "deep"],
        corpus=tasks,
        artifacts_dir=artifacts_dir,
        judge_backend=backends["openai"],
        judge_name="openai",
    )

    # 1. Verification of accuracy-only summary
    assert summary["tasks_count"] == 2
    assert "anthropic" in summary["targets"]
    assert "fast" in summary["targets"]["anthropic"]
    assert "deep" in summary["targets"]["anthropic"]

    target_res = summary["targets"]["anthropic"]["deep"]
    assert target_res["pass_rate"] == 1.0
    assert target_res["avg_score"] == 1.0
    assert target_res["passed"] == 2
    assert target_res["total"] == 2

    # Accuracy-only invariant: NO cost or savings in summary root or targets
    assert "cost" not in summary
    assert "saved" not in summary
    assert "spent" not in summary
    assert "cost" not in target_res

    # 2. Artifacts verification
    art_files = list(artifacts_dir.glob("*.json"))
    assert len(art_files) == 4  # 1 target x 2 efforts x 2 tasks
    art_data = json.loads(art_files[0].read_text())
    assert "transcript" in art_data
    assert "tool_calls_made" in art_data
    assert art_data["judge_family"] == "openai"


def test_format_eval_summary():
    summary = {
        "rubric_version": "v1",
        "tasks_count": 3,
        "targets": {
            "anthropic": {
                "fast": {"pass_rate": 0.667, "avg_score": 0.75, "passed": 2, "total": 3, "judge_family": "openai"},
                "deep": {"pass_rate": 1.0, "avg_score": 0.98, "passed": 3, "total": 3, "judge_family": "openai"},
            }
        },
    }
    rendered = format_eval_summary(summary)
    assert "CAPABILITY EVALUATION" in rendered
    assert "anthropic" in rendered
    assert "66.7%" in rendered
    assert "100.0%" in rendered
    assert "openai" in rendered


def test_cli_cmd_eval_execution(tmp_path, capsys, monkeypatch):
    from kultivait.config import Config, TierSpec

    # Mock config and backends
    fake_config = Config(
        tiers=[
            TierSpec(name="anthropic", role="architect", kind="api", price_in=3.0, price_out=15.0),
            TierSpec(name="openai", role="architect", kind="api", price_in=2.5, price_out=10.0),
        ]
    )
    monkeypatch.setattr("kultivait.cli.get_config", lambda: fake_config)
    monkeypatch.setattr(
        "kultivait.cli.build_backends",
        lambda cfg: {
            "anthropic": MockTargetBackend("anthropic"),
            "openai": MockJudgeBackend("openai"),
        },
    )

    args = argparse.Namespace(
        target="anthropic",
        effort="balanced",
        corpus=None,
        artifacts_dir=str(tmp_path / "art"),
        json=True,
    )
    cmd_eval(args)

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "targets" in data
    assert "anthropic" in data["targets"]
