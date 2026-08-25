"""Capability Eval Harness: direct-to-backend tool-loop evaluation,
cross-family model judging, and accuracy-only reporting.

Per ADR 0009:
- Direct-to-backend dispatch per target x effort level (bypassing routing).
- Tool-loop tasks with real tool schemas and rubrics.
- Cross-family model judge rule structurally enforced (judge family != target family).
- Accuracy-only summary report (pass rates per target x effort; no cost/savings metrics).
- Ledger tagging (tag='benchmark') for spend segregation.
"""

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from kultivait.backends import Backend, Completion
from kultivait.ledger import Ledger

CORPUS_DEFAULT_PATH = Path(__file__).parent.parent.parent / "evals" / "capability_corpus" / "tasks.json"


@dataclass
class TaskCase:
    id: str
    name: str
    description: str
    messages: list[dict]
    tools: list[dict]
    mock_responses: dict[str, str] = field(default_factory=dict)
    max_turns: int = 4
    rubric: dict = field(default_factory=dict)


@dataclass
class EvalArtifact:
    task_id: str
    target: str
    effort: str
    transcript: list[dict]
    tool_calls_made: list[dict]
    tokens_in: int
    tokens_out: int
    cost_usd: float
    passed: bool
    score: float
    judge_name: str
    judge_family: str
    judge_reasoning: str
    rubric_version: str
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "target": self.target,
            "effort": self.effort,
            "transcript": self.transcript,
            "tool_calls_made": self.tool_calls_made,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "cost_usd": self.cost_usd,
            "passed": self.passed,
            "score": self.score,
            "judge_name": self.judge_name,
            "judge_family": self.judge_family,
            "judge_reasoning": self.judge_reasoning,
            "rubric_version": self.rubric_version,
            "ts": self.ts,
        }


def get_family(provider_or_tier: str) -> str:
    """Classifies backend target into its provider family for anti-circular judging."""
    p = provider_or_tier.lower()
    if "anthropic" in p or "claude" in p:
        return "anthropic"
    if "openai" in p or "gpt" in p or "codex" in p:
        return "openai"
    if "openrouter" in p:
        return "openrouter"
    if any(k in p for k in ("llama", "qwen", "local", "ollama", "mistral")):
        return "local"
    return p


def select_cross_family_judge(
    target_tier: str,
    available_backends: dict[str, Backend],
) -> tuple[str, Backend]:
    """Selects an API-kind judge backend whose provider family strictly differs
    from the target. CLI judges are excluded (#65: the auto-selected CLI judge
    timed out at 600s — judge candidates must be api-kind). Raises ValueError
    if no cross-family API judge is available."""
    target_family = get_family(target_tier)

    def is_api_kind(b: Backend) -> bool:
        # API backends: not local AND client-tools-capable; CLI backends run
        # their own agent loops (supports_tools=False) and time out as judges.
        return getattr(b, "supports_tools", False) is True and not getattr(b, "local", True)

    cross_candidates = [
        (name, b) for name, b in available_backends.items()
        if get_family(name) != target_family and is_api_kind(b)
    ]

    if not cross_candidates:
        raise ValueError(
            f"No cross-family API judge available for target '{target_tier}' "
            f"(family: {target_family}). Judge candidates must be api-kind backends "
            f"(CLI judges are excluded — they time out under judging loads). "
            f"Register an api tier from a different family, or pin judge_backend "
            f"explicitly when calling run_capability_eval."
        )
    return cross_candidates[0]


def load_corpus(corpus_path: Path | None = None) -> list[TaskCase]:
    """Load evaluation corpus of tool-loop tasks from JSON file."""
    path = Path(corpus_path) if corpus_path else CORPUS_DEFAULT_PATH
    if not path.exists():
        # Fallback relative search
        alt_path = Path("evals/capability_corpus/tasks.json")
        if alt_path.exists():
            path = alt_path
        else:
            raise FileNotFoundError(f"Capability corpus not found at {path}")

    data = json.loads(path.read_text(encoding="utf-8"))
    tasks = []
    for item in data:
        tasks.append(
            TaskCase(
                id=item["id"],
                name=item.get("name", item["id"]),
                description=item.get("description", ""),
                messages=item.get("messages", []),
                tools=item.get("tools", []),
                mock_responses=item.get("mock_responses", {}),
                max_turns=item.get("max_turns", 4),
                rubric=item.get("rubric", {}),
            )
        )
    return tasks


def run_task(
    backend: Backend,
    task: TaskCase,
    effort_level: str = "balanced",
    ledger: Ledger | None = None,
    target_name: str = "target",
) -> tuple[list[dict], list[dict], int, int, float]:
    """Dispatches a multi-turn tool-loop task directly to a backend."""
    messages = [dict(m) for m in task.messages]
    tool_calls_made: list[dict] = []
    tot_in = 0
    tot_out = 0
    tot_cost = 0.0

    for _ in range(task.max_turns):
        kwargs = {}
        # Pass effort parameter if supported
        if hasattr(backend, "complete"):
            try:
                comp = backend.complete(
                    messages,
                    tools=task.tools,
                    canonical_effort=effort_level,
                )
            except TypeError:
                comp = backend.complete(messages, tools=task.tools)
        else:
            raise RuntimeError(f"Backend {backend} does not implement complete()")

        tot_in += comp.tokens_in
        tot_out += comp.tokens_out
        tot_cost += comp.cost_usd

        if ledger:
            ledger.record(
                tier=target_name,
                local=comp.local,
                tokens_in=comp.tokens_in,
                tokens_out=comp.tokens_out,
                cost_usd=comp.cost_usd,
                tag="benchmark",
                task_id=task.id,
                effort=effort_level,
            )

        if comp.tool_calls:
            assistant_msg: dict = {"role": "assistant", "content": comp.text or ""}
            assistant_msg["tool_calls"] = comp.tool_calls
            messages.append(assistant_msg)

            for tc in comp.tool_calls:
                tool_calls_made.append(tc)
                fn = tc.get("function", {})
                fn_name = fn.get("name", "")
                resp_content = task.mock_responses.get(fn_name, f"Mock tool {fn_name} executed successfully.")
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", "call_1"),
                    "name": fn_name,
                    "content": resp_content,
                })
        else:
            assistant_msg = {"role": "assistant", "content": comp.text or ""}
            messages.append(assistant_msg)
            break

    return messages, tool_calls_made, tot_in, tot_out, tot_cost


def judge_transcript(
    judge_backend: Backend,
    transcript: list[dict],
    rubric: dict,
    task_desc: str,
) -> tuple[bool, float, str]:
    """Evaluates task execution transcript against rubric using cross-family judge model."""
    rubric_version = rubric.get("version", "v1")
    criteria = rubric.get("criteria", [])
    expected_tools = rubric.get("expected_tools", [])
    passing_threshold = rubric.get("passing_score", 0.8)

    judge_prompt = f"""You are an expert AI Capability Judge evaluating an assistant's multi-turn tool interaction.

TASK DESCRIPTION:
{task_desc}

RUBRIC (Version: {rubric_version}):
Criteria:
{json.dumps(criteria, indent=2)}

Expected Tool Names: {expected_tools}

TRANSCRIPT:
{json.dumps(transcript, indent=2)}

INSTRUCTIONS:
Evaluate whether the assistant successfully used the tools to accomplish the task according to the rubric criteria.
Respond ONLY with a JSON object in this format:
{{
  "score": <float between 0.0 and 1.0>,
  "passed": <true or false>,
  "reasoning": "<brief explanation of score against criteria>"
}}
"""

    comp = judge_backend.complete([{"role": "user", "content": judge_prompt}])
    raw_text = comp.text.strip()

    try:
        # Extract JSON substring if wrapped in markdown
        start = raw_text.find("{")
        end = raw_text.rfind("}")
        if start != -1 and end != -1:
            data = json.loads(raw_text[start : end + 1])
            score = float(data.get("score", 0.0))
            passed = bool(data.get("passed", score >= passing_threshold))
            reasoning = str(data.get("reasoning", ""))
            return passed, score, reasoning
    except Exception:
        pass

    # Fallback heuristic check if JSON parsing failed
    has_expected_tools = all(
        any(
            tc.get("function", {}).get("name") == exp
            for m in transcript
            for tc in m.get("tool_calls", [])
        )
        for exp in expected_tools
    ) if expected_tools else True

    score = 1.0 if has_expected_tools else 0.0
    passed = score >= passing_threshold
    return passed, score, f"Heuristic fallback: expected tools present = {has_expected_tools}"


def run_capability_eval(
    backends: dict[str, Backend],
    targets: list[str] | None = None,
    efforts: list[str] | None = None,
    corpus: list[TaskCase] | None = None,
    artifacts_dir: Path | None = None,
    judge_backend: Backend | None = None,
    judge_name: str | None = None,
    ledger: Ledger | None = None,
) -> dict:
    """Runs capability evaluation across targets x effort levels, saving per-case artifacts
    and generating an accuracy-only summary report (no cost/savings metrics)."""
    eval_corpus = corpus or load_corpus()
    target_names = targets or [name for name in backends.keys() if name != judge_name]
    effort_levels = efforts or ["fast", "balanced", "deep"]

    artifacts: list[EvalArtifact] = []
    summary_targets: dict[str, dict] = {}

    if artifacts_dir:
        artifacts_dir = Path(artifacts_dir)
        artifacts_dir.mkdir(parents=True, exist_ok=True)

    for target in target_names:
        if target not in backends:
            continue
        backend = backends[target]
        summary_targets[target] = {}

        # Resolve cross-family judge
        if judge_backend and judge_name:
            j_name, j_b = judge_name, judge_backend
            # Verify cross-family rule
            if get_family(j_name) == get_family(target):
                raise ValueError(
                    f"Cross-family violation: Judge '{j_name}' and Target '{target}' are both in family '{get_family(target)}'."
                )
        else:
            j_name, j_b = select_cross_family_judge(target, backends)

        j_family = get_family(j_name)

        for effort in effort_levels:
            passed_count = 0
            total_score = 0.0
            task_count = len(eval_corpus)

            for task in eval_corpus:
                transcript, tool_calls, tokens_in, tokens_out, cost_usd = run_task(
                    backend=backend,
                    task=task,
                    effort_level=effort,
                    ledger=ledger,
                    target_name=target,
                )

                passed, score, reasoning = judge_transcript(
                    judge_backend=j_b,
                    transcript=transcript,
                    rubric=task.rubric,
                    task_desc=task.description,
                )

                if passed:
                    passed_count += 1
                total_score += score

                artifact = EvalArtifact(
                    task_id=task.id,
                    target=target,
                    effort=effort,
                    transcript=transcript,
                    tool_calls_made=tool_calls,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    cost_usd=cost_usd,
                    passed=passed,
                    score=score,
                    judge_name=j_name,
                    judge_family=j_family,
                    judge_reasoning=reasoning,
                    rubric_version=task.rubric.get("version", "v1"),
                )
                artifacts.append(artifact)

                if artifacts_dir:
                    art_file = artifacts_dir / f"{target}_{effort}_{task.id}.json"
                    art_file.write_text(json.dumps(artifact.to_dict(), indent=2))

            pass_rate = passed_count / task_count if task_count else 0.0
            avg_score = total_score / task_count if task_count else 0.0
            summary_targets[target][effort] = {
                "pass_rate": pass_rate,
                "avg_score": avg_score,
                "passed": passed_count,
                "total": task_count,
                "judge_family": j_family,
            }

    rubric_v = eval_corpus[0].rubric.get("version", "v1") if eval_corpus else "v1"

    # Accuracy-only report: NO cost or savings metrics emitted per ADR 0009!
    return {
        "rubric_version": rubric_v,
        "tasks_count": len(eval_corpus),
        "targets": summary_targets,
    }


def format_eval_summary(summary: dict) -> str:
    """Format accuracy-only capability evaluation summary."""
    lines = [
        "=" * 76,
        "KULTIVAIT CAPABILITY EVALUATION (Accuracy-Only)",
        f"Corpus: {summary.get('tasks_count', 0)} tool-loop tasks | Rubric: {summary.get('rubric_version', 'v1')}",
        "=" * 76,
        f"{'TARGET':<16} {'EFFORT':<12} {'PASS RATE':<12} {'AVG SCORE':<12} {'PASSED/TOTAL':<12} {'JUDGE FAMILY':<12}",
        "-" * 76,
    ]

    targets = summary.get("targets", {})
    if not targets:
        lines.append("  No evaluation targets executed.")
    else:
        for target, efforts in targets.items():
            for effort, metrics in efforts.items():
                p_rate = f"{metrics['pass_rate'] * 100:.1f}%"
                avg_s = f"{metrics['avg_score']:.2f}"
                p_tot = f"{metrics['passed']}/{metrics['total']}"
                j_fam = metrics.get("judge_family", "")
                lines.append(
                    f"{target:<16} {effort:<12} {p_rate:<12} {avg_s:<12} {p_tot:<12} {j_fam:<12}"
                )

    lines.append("=" * 76)
    return "\n".join(lines)
