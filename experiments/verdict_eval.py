#!/usr/bin/env python3
"""Wayfinder Ticket #14: Held-out eval validating provisional verdict thresholds.

Contract:
- Single-call analyze->rewrite->judge using PREPROCESSOR_PROMPT.
- Default tier (headline): qwen3.5:4b; Reference tier: qwen3:14b.
- Derived verdict: fit = max(t["fit"] for t in judge["targets"])
  verdict = "local" if fit < low else ("frontier" if fit >= high else "contested")
  Provisional thresholds: low = 0.65, high = 0.85.
- Latency budget: p50 <= 8.0s, cap <= 15.0s.

Outputs:
- Artifacts per case under experiments/verdict_eval/<model-slug>/<slug>.json
- Summary JSON under experiments/verdict_eval/summary.json
"""

import json
import re
import sys
import time
import urllib.request
from pathlib import Path

OLLAMA = "http://localhost:11434/api/chat"
HERE = Path(__file__).parent
ARTIFACTS_DIR = HERE / "verdict_eval"

PREPROCESSOR_PROMPT = """\
You are kultivait's prompt preprocessor. Analyze the user prompt below and \
respond with ONLY a JSON object (no prose, no code fences) with these keys:

{{
  "analysis": {{
    "task_type": "simple_edit|debugging|architecture|docs_lookup|compound|underspecified",
    "complexity": 1-9,
    "signals": ["short list of the concrete signals you used"]
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

CASES = [
    # 6 Probe Cases (verbatim from experiments/preprocessor_probe.py)
    (
        "01-simple-edit",
        "Rename the variable cfg to settings everywhere in src/kultivait/config.py "
        "and fix the imports.",
        "local",
        "Mechanical rename across a single config file and its imports",
    ),
    (
        "02-debug",
        "Why does kultivait route hang forever when ollama is slow to answer? "
        "Where is that timeout set?",
        "local",
        "In-repo diagnostic on known codebase timeout parameter",
    ),
    (
        "03-architecture",
        "Should the pending-tolls queue live inside the FastAPI server process "
        "or a separate worker? Compare against how escalations are archived today.",
        "frontier",
        "Cross-file design judgment comparing server lifecycle and archiving architectures",
    ),
    (
        "04-docs-lookup",
        "What values does the --effort flag accept in claude CLI 2.1.238?",
        "frontier",
        "Freshness-dependent lookup of specific external CLI version documentation",
    ),
    (
        "05-compound",
        "Add a kultivait choose subcommand that drains pending tolls: queue "
        "file, TTY chooser, heartbeat POST endpoint, and tests. Then update the "
        "README section about the tollbooth.",
        "frontier",
        "Orchestration-worthy compound multi-component feature and documentation update",
    ),
    (
        "06-adversarial-truncated",
        "Find the bug in this function, it returns None sometimes:\n\n"
        "def resolve_tier(tier, tools):\n"
        "    if tier.kind == 'cli' and tools:\n"
        "        local = [t for t in tiers if t.kind == 'l\n"
        "# (file continues, truncated by context limit)",
        "borderline",
        "Adversarially truncated context where missing information creates genuine ambiguity",
    ),
    # 6 Fresh Held-Out Cases
    (
        "h01-local-constant",
        "In tests/test_config.py replace the magic numbers 3.0 and 15.0 with named constants imported from kultivait.config.",
        "local",
        "Single-file mechanical refactoring of test constants",
    ),
    (
        "h02-inrepo-lookup",
        "List the tier names ROLES defines in config.py and explain the order detect() sorts tiers by.",
        "local",
        "Static code extraction and lookup within a single repository file",
    ),
    (
        "h03-flaky-debug",
        "This async test flakes about one run in five on CI but always passes locally, probably timing related. Where should I start looking? (no repro repo attached)",
        "borderline",
        "Open-ended concurrency debugging with incomplete context and no reproduction repository",
    ),
    (
        "h04-middleware-arch",
        "Evaluate whether kultivait's trolltoll hold should move from the FastAPI request handler into middleware so headless clients get consistent behavior; recommend with tradeoffs.",
        "frontier",
        "Deep architectural analysis of HTTP request lifecycle, holding semantics, and headless client tradeoffs",
    ),
    (
        "h05-freshness-cite",
        "Does ollama 0.7 still treat piped stdin prompts the same way current docs describe, or has that changed this year? Cite current docs.",
        "frontier",
        "External documentation verification requiring fresh citations on recent version changes",
    ),
    (
        "h06-small-feature",
        "Add a --json flag to kultivait route that prints the Decision object, then note the flag in the README route section.",
        "borderline",
        "Multi-step feature spanning CLI argument parsing, serialization, and documentation",
    ),
]

DEFAULT_MODELS = ["qwen3.5:4b", "qwen3:14b"]
SWEEP_CUTPOINTS = [
    (0.60, 0.80),
    (0.60, 0.85),
    (0.65, 0.80),
    (0.65, 0.85),  # Current provisional
    (0.65, 0.90),
    (0.70, 0.85),
    (0.70, 0.90),
]


def generate(model: str, prompt: str) -> tuple[str, float]:
    body = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"temperature": 0.2, "num_predict": 700},
            "think": False,
        }
    ).encode()
    req = urllib.request.Request(
        OLLAMA, data=body, headers={"Content-Type": "application/json"}
    )
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=300) as resp:
        data = json.load(resp)
    return data["message"]["content"], time.monotonic() - t0


def extract_json(text: str):
    """Local models blurt prose and fences; grab the outermost braces."""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None, "no braces found"
    try:
        return json.loads(m.group(0)), None
    except json.JSONDecodeError as e:
        return None, f"json parse: {e}"


def derive_verdict(fit: float, low: float = 0.65, high: float = 0.85) -> str:
    if fit < low:
        return "local"
    elif fit >= high:
        return "frontier"
    else:
        return "contested"


def evaluate_outcome(verdict: str, label: str) -> dict:
    if label == "borderline":
        agree = verdict == "contested"
        dangerous = False
        wasteful = False
        miss = not agree
    elif label == "frontier":
        agree = verdict == "frontier"
        dangerous = verdict == "local"
        wasteful = False
        miss = verdict != "frontier" and not dangerous
    elif label == "local":
        agree = verdict == "local"
        dangerous = False
        wasteful = verdict == "frontier"
        miss = verdict != "local" and not wasteful
    else:
        agree = verdict == label
        dangerous = False
        wasteful = False
        miss = not agree

    return {
        "agree": agree,
        "dangerous": dangerous,
        "wasteful": wasteful,
        "miss": miss,
    }


def compute_metrics(cases_data: list[dict], low: float = 0.65, high: float = 0.85) -> dict:
    total = len(cases_data)
    parse_oks = [c for c in cases_data if c["parse_ok"]]
    parse_failures = total - len(parse_oks)

    agreed = 0
    dangerous = 0
    wasteful = 0
    contested_count = 0
    latencies = [c["latency_s"] for c in cases_data if c["latency_s"] >= 0]

    for c in cases_data:
        if not c["parse_ok"]:
            continue
        fit = c["max_fit"]
        v = derive_verdict(fit, low, high)
        if v == "contested":
            contested_count += 1
        outcome = evaluate_outcome(v, c["label"])
        if outcome["agree"]:
            agreed += 1
        if outcome["dangerous"]:
            dangerous += 1
        if outcome["wasteful"]:
            wasteful += 1

    valid_count = max(1, len(parse_oks))
    latencies_sorted = sorted(latencies)
    if latencies_sorted:
        p50 = latencies_sorted[len(latencies_sorted) // 2]
        max_lat = latencies_sorted[-1]
    else:
        p50, max_lat = 0.0, 0.0

    return {
        "total_cases": total,
        "parse_ok_count": len(parse_oks),
        "parse_failure_count": parse_failures,
        "parse_ok_rate": round(len(parse_oks) / total, 3),
        "agreement_count": agreed,
        "agreement_rate": round(agreed / valid_count, 3),
        "dangerous_count": dangerous,
        "dangerous_rate": round(dangerous / valid_count, 3),
        "wasteful_count": wasteful,
        "wasteful_rate": round(wasteful / valid_count, 3),
        "toll_count": contested_count,
        "toll_rate": round(contested_count / valid_count, 3),
        "latency_p50_s": round(p50, 2),
        "latency_max_s": round(max_lat, 2),
        "low_threshold": low,
        "high_threshold": high,
    }


def run_eval(models: list[str]) -> dict:
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    all_results = {}

    for model in models:
        model_slug = model.replace(":", "-")
        outdir = ARTIFACTS_DIR / model_slug
        outdir.mkdir(parents=True, exist_ok=True)

        print(f"\n==================================================")
        print(f"Evaluating Model: {model}")
        print(f"==================================================")

        cases_data = []
        for slug, prompt, label, rationale in CASES:
            filled = PREPROCESSOR_PROMPT.format(prompt=prompt)
            try:
                raw_text, secs = generate(model, filled)
            except Exception as e:
                raw_text, secs = f"GENERATION_FAILED: {e}", -1.0

            parsed, parse_err = extract_json(raw_text) if secs >= 0 else (None, "generation failed")
            parse_ok = parsed is not None

            # Extract judge targets and compute max fit
            targets = []
            max_fit = 0.0
            local_sufficient_diag = None
            task_type_diag = None
            complexity_diag = None
            confidence_diag = None

            if parse_ok and isinstance(parsed, dict):
                judge_block = parsed.get("judge", {})
                if isinstance(judge_block, dict):
                    local_sufficient_diag = judge_block.get("local_sufficient")
                    confidence_diag = judge_block.get("confidence")
                    raw_targets = judge_block.get("targets", [])
                    if isinstance(raw_targets, list):
                        for t in raw_targets:
                            if isinstance(t, dict) and "fit" in t:
                                try:
                                    f_val = float(t["fit"])
                                    targets.append({"target": t.get("target"), "fit": f_val, "effort": t.get("effort")})
                                except (ValueError, TypeError):
                                    pass
                analysis_block = parsed.get("analysis", {})
                if isinstance(analysis_block, dict):
                    task_type_diag = analysis_block.get("task_type")
                    complexity_diag = analysis_block.get("complexity")

            if targets:
                max_fit = max(t["fit"] for t in targets)
            else:
                max_fit = 0.0

            verdict_default = derive_verdict(max_fit, 0.65, 0.85)
            outcome_default = evaluate_outcome(verdict_default, label) if parse_ok else {
                "agree": False, "dangerous": False, "wasteful": False, "miss": True
            }

            case_artifact = {
                "slug": slug,
                "label": label,
                "label_rationale": rationale,
                "prompt": prompt,
                "latency_s": round(secs, 2),
                "parse_ok": parse_ok,
                "parse_error": parse_err,
                "max_fit": round(max_fit, 3),
                "derived_verdict": verdict_default,
                "outcome": outcome_default,
                "diagnostics": {
                    "local_sufficient": local_sufficient_diag,
                    "confidence": confidence_diag,
                    "task_type": task_type_diag,
                    "complexity": complexity_diag,
                },
                "targets": targets,
                "raw_output": parsed if parse_ok else raw_text,
            }

            (outdir / f"{slug}.json").write_text(json.dumps(case_artifact, indent=2))
            cases_data.append(case_artifact)

            status_str = "OK " if parse_ok else "FAIL"
            outcome_tag = "AGREE" if outcome_default["agree"] else (
                "DANGER" if outcome_default["dangerous"] else (
                    "WASTE " if outcome_default["wasteful"] else "MISS  "
                )
            )
            print(f"  [{status_str}] {secs:5.1f}s | fit={max_fit:0.2f} -> {verdict_default:<9} (exp: {label:<10}) [{outcome_tag}] {slug}")

        # Baseline metrics at (0.65, 0.85)
        metrics_baseline = compute_metrics(cases_data, 0.65, 0.85)

        # Threshold sweep
        sweep_results = []
        for low, high in SWEEP_CUTPOINTS:
            res = compute_metrics(cases_data, low, high)
            sweep_results.append({
                "low": low,
                "high": high,
                "agreement_count": res["agreement_count"],
                "agreement_rate": res["agreement_rate"],
                "dangerous_count": res["dangerous_count"],
                "wasteful_count": res["wasteful_count"],
                "toll_count": res["toll_count"],
                "toll_rate": res["toll_rate"],
            })

        all_results[model] = {
            "model": model,
            "metrics": metrics_baseline,
            "sweep": sweep_results,
            "cases": cases_data,
        }

    summary_file = ARTIFACTS_DIR / "summary.json"
    summary_file.write_text(json.dumps(all_results, indent=2))
    print(f"\nSaved summary to {summary_file}")
    return all_results


def main():
    models = sys.argv[1:] or DEFAULT_MODELS
    results = run_eval(models)

    # Print summary table
    print("\n" + "=" * 80)
    print("HELD-OUT EVALUATION SUMMARY")
    print("=" * 80)
    for model, data in results.items():
        m = data["metrics"]
        print(f"\nModel: {model}")
        print(f"  Parse OK:      {m['parse_ok_count']}/{m['total_cases']} ({m['parse_ok_rate']*100:.1f}%)")
        print(f"  Agreement:     {m['agreement_count']}/{m['parse_ok_count']} ({m['agreement_rate']*100:.1f}%)")
        print(f"  Dangerous:     {m['dangerous_count']}/{m['parse_ok_count']}")
        print(f"  Wasteful:      {m['wasteful_count']}/{m['parse_ok_count']}")
        print(f"  Toll Rate:     {m['toll_count']}/{m['parse_ok_count']} ({m['toll_rate']*100:.1f}%)")
        print(f"  Latency p50:   {m['latency_p50_s']}s (budget <= 8.0s)")
        print(f"  Latency max:   {m['latency_max_s']}s (cap <= 15.0s)")

        print("  Threshold Sweep:")
        print("    (low, high) | Agreement | Dangerous | Wasteful | Toll Rate")
        print("    ------------+-----------+-----------+----------+----------")
        for s in data["sweep"]:
            mark = " (provisional)" if (s["low"], s["high"]) == (0.65, 0.85) else ""
            print(f"    ({s['low']:.2f}, {s['high']:.2f}) | {s['agreement_count']:>2}/12 ({s['agreement_rate']*100:4.1f}%) | {s['dangerous_count']:>9} | {s['wasteful_count']:>8} | {s['toll_rate']*100:5.1f}%{mark}")


if __name__ == "__main__":
    main()
