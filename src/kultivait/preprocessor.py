"""Local prompt preprocessor: single-call analyze, rewrite, and judge.

Analyzes the prompt, rewrites it per-target, extracts sub-task candidates
for compound or tool-bearing prompts, and derives routing verdicts structurally
from target fits.
"""

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

DEFAULT_PREPROCESS_MODEL = "qwen3.5:4b"
VERDICT_THRESHOLDS = (0.65, 0.85)

MARK_OK = "ok"
MARK_TIMEOUT = "preprocess_timeout"
MARK_FAIL = "preprocess_fail"
MARK_SKIPPED = "skipped"

PREPROCESSOR_PROMPT = """\
You are kultivait's prompt preprocessor. Analyze the user prompt below and \
respond with ONLY a JSON object (no prose, no code fences) with these keys:

{{
  "analysis": {{
    "task_type": "simple_edit|debugging|architecture|docs_lookup|compound|underspecified",
    "complexity": 1-9,
    "signals": ["short list of the concrete signals you used"],
    "subtask_candidates": ["list of short sub-task strings for compound or tool-bearing prompts, else empty list"]
  }},
  "rewrite": "the prompt rewritten to be self-contained, unambiguous, and \
stripped of filler; if context is missing, the rewrite makes the gap explicit",
  "judge": {{
    "local_sufficient": true|false,
    "confidence": 0.0-1.0,
    "targets": [
      {{"target": "claude|agy|gemini|codex|opencode", "fit": 0.0-1.0, "effort": "low|medium|high"}}
    ]
  }}
}}

USER PROMPT:
{prompt}
"""


@dataclass(frozen=True)
class TargetFit:
    target: str
    fit: float
    effort: str


@dataclass(frozen=True)
class AnalysisResult:
    task_type: str
    complexity: int
    signals: list[str] = field(default_factory=list)
    subtask_candidates: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PreprocessResult:
    analysis: AnalysisResult
    rewrite: str
    target_fits: list[TargetFit]
    max_fit: float
    derived_verdict: str | None
    confidence: float
    raw_output: dict | None
    latency_s: float
    mark: str


def derive_verdict(max_fit: float) -> str:
    """Derive routing verdict structurally from max target fit."""
    low, high = VERDICT_THRESHOLDS
    if max_fit < low:
        return "local"
    elif max_fit >= high:
        return "frontier"
    else:
        return "contested"


def _strip_noise(text: str) -> str:
    """Remove common non-JSON noise: chat template delimiters, markdown fences."""
    text = re.sub(r"<\|[^>]*\|>", "", text)  # <|im_end|>, <|im_start|> etc.
    # markdown code fences: ```json ... ``` or ``` ... ```
    text = re.sub(r"```(?:json)?\s*\n?", "", text)
    text = re.sub(r"```", "", text)
    return text.strip()


def _find_balanced_candidates(text: str) -> "list[str]":
    """Scan for ALL complete balanced-braces {...} substrings at depth 0,
    with string-escape awareness. Returns candidates in order of appearance."""
    results = []
    depth = 0
    start = -1
    in_string = False
    escaped = False

    for i, c in enumerate(text):
        if escaped:
            escaped = False
            continue
        if c == "\\" and in_string:
            escaped = True
            continue
        if c == '"' and not escaped:
            in_string = not in_string
            continue
        if in_string:
            continue
        if c == "{":
            if depth == 0:
                start = i
            depth += 1
        elif c == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start >= 0:
                    results.append(text[start : i + 1])
                    start = -1
            if depth < 0:
                break  # unbalanced close; stop scanning

    return results


def extract_json(text: str) -> tuple[dict | None, str | None]:
    """Extract the first complete JSON object from text, ignoring surrounding
    prose/fences/chat-template delimiters. Uses balanced-braces scanning (not
    a greedy regex) so trailing prose containing `}` doesn't corrupt the match.
    String-aware: braces inside quoted strings are not counted."""
    if not isinstance(text, str):
        return None, "non-string output"

    cleaned = _strip_noise(text)
    candidates = _find_balanced_candidates(cleaned)
    if not candidates:
        # retry on the original (noise stripping might have eaten something)
        candidates = _find_balanced_candidates(text)
    if not candidates:
        return None, "no braces found"

    for candidate in candidates:
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return data, None
        except json.JSONDecodeError:
            continue  # try the next balanced candidate (prose {braces} etc.)

    return None, f"json parse: no valid object among {len(candidates)} candidate(s)"


def _extract_last_user_message(messages: list[dict]) -> str:
    for m in reversed(messages):
        if isinstance(m, dict) and m.get("role") == "user":
            content = m.get("content", "")
            if isinstance(content, str):
                return content
            elif isinstance(content, list):
                return "".join(
                    part.get("text", "")
                    for part in content
                    if isinstance(part, dict) and part.get("type") == "text"
                )
    return ""


def run(
    messages: list[dict],
    *,
    generate: Callable[[str, str], Any],
    model: str = DEFAULT_PREPROCESS_MODEL,
    timeout_s: float = 15.0,
) -> PreprocessResult:
    """Run the preprocessor pass against the injected generate function.

    Returns a PreprocessResult with derived_verdict set to 'local', 'frontier',
    or 'contested' when successful. On timeout or parse failure, derived_verdict
    is None, indicating that the caller should fall back to the router verdict.
    """
    last_user_msg = _extract_last_user_message(messages)
    filled_prompt = PREPROCESSOR_PROMPT.format(prompt=last_user_msg)

    t0 = time.monotonic()
    try:
        gen_result = generate(model, filled_prompt)
        t1 = time.monotonic()
        latency_s = round(t1 - t0, 2)
        if latency_s > timeout_s:
            return PreprocessResult(
                analysis=AnalysisResult(
                    task_type="unknown", complexity=0, signals=[], subtask_candidates=[]
                ),
                rewrite=last_user_msg,
                target_fits=[],
                max_fit=0.0,
                derived_verdict=None,
                confidence=0.0,
                raw_output=None,
                latency_s=latency_s,
                mark=MARK_TIMEOUT,
            )
        if isinstance(gen_result, tuple):
            raw_text = gen_result[0]
        else:
            raw_text = str(gen_result)
    except TimeoutError:
        t1 = time.monotonic()
        latency_s = round(t1 - t0, 2)
        return PreprocessResult(
            analysis=AnalysisResult(
                task_type="unknown", complexity=0, signals=[], subtask_candidates=[]
            ),
            rewrite=last_user_msg,
            target_fits=[],
            max_fit=0.0,
            derived_verdict=None,
            confidence=0.0,
            raw_output=None,
            latency_s=latency_s,
            mark=MARK_TIMEOUT,
        )

    parsed_json, err = extract_json(raw_text)
    if parsed_json is None or not isinstance(parsed_json, dict):
        return PreprocessResult(
            analysis=AnalysisResult(
                task_type="unknown", complexity=0, signals=[], subtask_candidates=[]
            ),
            rewrite=last_user_msg,
            target_fits=[],
            max_fit=0.0,
            derived_verdict=None,
            confidence=0.0,
            raw_output=None,
            latency_s=latency_s,
            mark=MARK_FAIL,
        )

    try:
        analysis_dict = parsed_json.get("analysis", {})
        task_type = str(analysis_dict.get("task_type", "unknown"))
        try:
            complexity = int(analysis_dict.get("complexity", 0))
        except (ValueError, TypeError):
            complexity = 0
        signals = [str(s) for s in analysis_dict.get("signals", []) if s is not None]
        subtask_candidates = [
            str(st) for st in analysis_dict.get("subtask_candidates", []) if st is not None
        ]
        analysis = AnalysisResult(
            task_type=task_type,
            complexity=complexity,
            signals=signals,
            subtask_candidates=subtask_candidates,
        )

        rewrite = str(parsed_json.get("rewrite", last_user_msg))

        judge_dict = parsed_json.get("judge", {})
        try:
            confidence = float(judge_dict.get("confidence", 0.0))
        except (ValueError, TypeError):
            confidence = 0.0

        targets_raw = judge_dict.get("targets", [])
        target_fits = []
        if isinstance(targets_raw, list):
            for t in targets_raw:
                if isinstance(t, dict):
                    t_name = str(t.get("target", ""))
                    try:
                        t_fit = float(t.get("fit", 0.0))
                    except (ValueError, TypeError):
                        t_fit = 0.0
                    t_effort = str(t.get("effort", "medium"))
                    target_fits.append(TargetFit(target=t_name, fit=t_fit, effort=t_effort))

        max_fit = max((tf.fit for tf in target_fits), default=0.0)
        derived_verdict = derive_verdict(max_fit)

        return PreprocessResult(
            analysis=analysis,
            rewrite=rewrite,
            target_fits=target_fits,
            max_fit=max_fit,
            derived_verdict=derived_verdict,
            confidence=confidence,
            raw_output=parsed_json,
            latency_s=latency_s,
            mark=MARK_OK,
        )
    except Exception:
        return PreprocessResult(
            analysis=AnalysisResult(
                task_type="unknown", complexity=0, signals=[], subtask_candidates=[]
            ),
            rewrite=last_user_msg,
            target_fits=[],
            max_fit=0.0,
            derived_verdict=None,
            confidence=0.0,
            raw_output=None,
            latency_s=latency_s,
            mark=MARK_FAIL,
        )
