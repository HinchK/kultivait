"""Distillation-quality eval: models x prompts x corpus, scored by planted-fact recall.

Usage: uv run python experiments/distill_eval/run.py [model ...]
"""

import json
import re
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))
from facts import FACTS  # noqa: E402

from kultivait.evals import score_brief  # noqa: E402
from kultivait.gates import DISTILL_PROMPT  # noqa: E402

OLLAMA = "http://localhost:11434"
CORPUS_DIR = Path(__file__).parent / "corpus"
RESULTS = Path(__file__).parent / "results.json"

PROMPT_V2 = DISTILL_PROMPT.replace(
    "Be ruthless about omitting dead ends and process narration. Never omit a "
    "constraint, a file path, or a decision.",
    "",
).replace(
    "TRANSCRIPT:",
    """Be ruthless about omitting dead ends and process narration — but NEVER omit:
- exact numbers, rates, counts, and version pins (copy them verbatim)
- testing requirements and test-design constraints
- file paths and code identifiers (copy them verbatim)
- the implication or scope of a finding, not just the finding itself

Before finishing, re-scan the transcript once for numbers, versions, and testing
constraints, and add any your draft missed.

TRANSCRIPT:""",
)

assert PROMPT_V2 != DISTILL_PROMPT, "v2 replacements did not apply"
assert "re-scan" in PROMPT_V2

PROMPTS = {"v1": DISTILL_PROMPT, "v2": PROMPT_V2}
DEFAULT_MODELS = ["llama3.1:8b", "qwen2.5:14b", "qwen3:14b", "gemma4:latest"]


def make_generate(model: str, template: str):
    def generate(prompt: str) -> str:
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        }
        if model.startswith("qwen3"):
            payload["think"] = False
        r = httpx.post(f"{OLLAMA}/api/chat", json=payload, timeout=900)
        r.raise_for_status()
        text = r.json()["message"]["content"]
        return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

    return generate


def main() -> None:
    models = sys.argv[1:] or DEFAULT_MODELS
    results = []
    if RESULTS.exists():
        results = json.loads(RESULTS.read_text())
    done = {(r["model"], r["prompt"], r["doc"]) for r in results}

    for model in models:
        for pname, template in PROMPTS.items():
            for doc, facts in FACTS.items():
                if (model, pname, doc) in done:
                    continue
                transcript = (CORPUS_DIR / f"{doc}.txt").read_text()
                start = time.time()
                gen = make_generate(model, template)
                brief = gen(template.format(from_phase="explore", to_phase="plan", transcript=transcript))
                seconds = time.time() - start
                score = score_brief(brief, facts)
                row = {
                    "model": model,
                    "prompt": pname,
                    "doc": doc,
                    "recall": round(score.recall, 3),
                    "missing": score.missing,
                    "tokens_before": len(transcript) // 4,
                    "tokens_after": len(brief) // 4,
                    "seconds": round(seconds, 1),
                }
                results.append(row)
                RESULTS.write_text(json.dumps(results, indent=2))
                print(
                    f"{model:<14} {pname}  {doc:<12} recall={score.recall:.2f} "
                    f"({len(transcript) // 4}->{len(brief) // 4} tok, {seconds:.0f}s) "
                    f"missing={score.missing}"
                )

    # summary
    print("\n=== mean recall by model x prompt ===")
    for model in models:
        for pname in PROMPTS:
            rows = [r for r in results if r["model"] == model and r["prompt"] == pname]
            if rows:
                mean = sum(r["recall"] for r in rows) / len(rows)
                secs = sum(r["seconds"] for r in rows) / len(rows)
                comp = sum(r["tokens_after"] / r["tokens_before"] for r in rows) / len(rows)
                print(f"{model:<14} {pname}  recall={mean:.3f}  kept={comp:.0%}  avg={secs:.0f}s")


if __name__ == "__main__":
    main()
