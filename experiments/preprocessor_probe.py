#!/usr/bin/env python3
"""PROTOTYPE — throwaway probe for wayfinder ticket 'Preprocessor prototype on
live local models'. Not production code. Answers one question: what does a
single-call analyze->rewrite->judge preprocessor actually emit from the
configured local models, how good is it, and what does it cost in latency?

Run:  uv run python experiments/preprocessor_probe.py [model ...]
Artifacts land in experiments/preprocessor_probe/artifacts/<model>/ per case,
plus a summary.md comparing models. Git branch: prototype/preprocessor-probe.
"""

import json
import re
import sys
import time
import urllib.request
from pathlib import Path

OLLAMA = "http://localhost:11434/api/chat"
HERE = Path(__file__).parent
ARTIFACTS = HERE / "preprocessor_probe" / "artifacts"

# One candidate preprocessor prompt, single call, strict JSON out.
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

# Six representative cases (ticket spec): simple edit, debugging, cross-file
# architecture, docs lookup, orchestration-worthy compound, adversarial
# truncated-context.
CASES = [
    (
        "01-simple-edit",
        "Rename the variable cfg to settings everywhere in src/kultivait/config.py "
        "and fix the imports.",
    ),
    (
        "02-debug",
        "Why does kultivait route hang forever when ollama is slow to answer? "
        "Where is that timeout set?",
    ),
    (
        "03-architecture",
        "Should the pending-tolls queue live inside the FastAPI server process "
        "or a separate worker? Compare against how escalations are archived today.",
    ),
    (
        "04-docs-lookup",
        "What values does the --effort flag accept in claude CLI 2.1.238?",
    ),
    (
        "05-compound",
        "Add a kultivait choose subcommand that drains pending tolls: queue "
        "file, TTY chooser, heartbeat POST endpoint, and tests. Then update the "
        "README section about the tollbooth.",
    ),
    (
        "06-adversarial-truncated",
        "Find the bug in this function, it returns None sometimes:\n\n"
        "def resolve_tier(tier, tools):\n"
        "    if tier.kind == 'cli' and tools:\n"
        "        local = [t for t in tiers if t.kind == 'l\n"
        "# (file continues, truncated by context limit)",
    ),
]

DEFAULT_MODELS = ["qwen3.5:4b", "qwen3:14b"]


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
    """Local models blurt prose and fences; grab the outermost braces honestly."""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None, "no braces found"
    try:
        return json.loads(m.group(0)), None
    except json.JSONDecodeError as e:
        return None, f"json parse: {e}"


def main():
    models = sys.argv[1:] or DEFAULT_MODELS
    summary = {}
    for model in models:
        outdir = ARTIFACTS / model.replace(":", "-")
        outdir.mkdir(parents=True, exist_ok=True)
        rows = []
        print(f"\n=== {model} ===")
        for slug, prompt in CASES:
            filled = PREPROCESSOR_PROMPT.format(prompt=prompt)
            try:
                raw, secs = generate(model, filled)
            except Exception as e:
                raw, secs = f"GENERATION FAILED: {e}", -1.0
            parsed, err = extract_json(raw) if secs >= 0 else (None, "generation failed")
            art = {
                "case": slug,
                "prompt": prompt,
                "latency_s": round(secs, 2),
                "parse_ok": parsed is not None,
                "parse_error": err,
                "output": parsed if parsed is not None else raw,
            }
            (outdir / f"{slug}.json").write_text(json.dumps(art, indent=2))
            rows.append(art)
            ok = "OK " if parsed is not None else "FAIL"
            lat = f"{secs:5.1f}s" if secs >= 0 else "  n/a"
            tt = (parsed or {}).get("analysis", {}).get("task_type", "?") if parsed else "?"
            loc = (parsed or {}).get("judge", {}).get("local_sufficient", "?") if parsed else "?"
            print(f"  {ok} {lat}  {slug:<28} task_type={tt:<15} local_sufficient={loc}")
        good = [r for r in rows if r["parse_ok"]]
        summary[model] = {
            "parse_ok": f"{len(good)}/{len(rows)}",
            "mean_latency_s": round(sum(r["latency_s"] for r in good) / max(1, len(good)), 2),
        }

    lines = [
        "# Preprocessor probe summary",
        "",
        "Single-call analyze/rewrite/judge via candidate PREPROCESSOR_PROMPT.",
        "Full artifacts per case/model sit next to this file.",
        "",
        "| model | parse ok | mean latency |",
        "|---|---|---|",
    ]
    for model, s in summary.items():
        lines.append(f"| {model} | {s['parse_ok']} | {s['mean_latency_s']}s |")
    (ARTIFACTS / "summary.md").write_text("\n".join(lines) + "\n")
    print("\n" + "\n".join(lines))


if __name__ == "__main__":
    main()
