"""Frontier-latency reference probe (ADR 0024 / the #215 pin).

Measures first-token and total latency of ONE named stable reference target
(``anthropic/claude-sonnet-5`` via OpenRouter) per prompt-token band, n runs
each, prompts varied per run so provider prompt-caching cannot deflate the
medians. Raw samples land next to this script; the medians are pasted into
``src/kultivait/time_reference.py`` (values only — provenance lives here).

Usage:
    uv run python experiments/latency_probe/run_probe.py [--runs 10] [--out samples-YYYYMMDD.json]
"""

import argparse
import json
import random
import statistics
import time
from pathlib import Path

from kultivait.api_backends import OpenRouterBackend

TARGET = "anthropic/claude-sonnet-5"
# probe the middle of each band; sizes are CHARS (est. tokens x 4) so rows
# land in-band — the first attempt sized by word count and overshot 2x
BAND_TARGET_CHARS = {"0-2k": 4_000, "2-8k": 20_000, "8k+": 40_000}
BAND_EDGES = {"0-2k": (0, 2048), "2-8k": (2048, 8192), "8k+": (8192, None)}
WORDS = (
    "harvest ledger tollbooth verdict preprocessor centroid escalation "
    "compost distillate fingerprint trolltoll capability effort dialect "
    "notional metered reference baseline anchor cache breakpoint shadow"
).split()
TEMPLATES = (
    "the {a} holds a {b} verdict for every {c} it weighs",
    "a {a} dispatch lands in the {b} ledger with its {c} intact",
    "when the {a} fires, the {b} archives the {c} for later review",
    "each {a} carries its {b} from the {c} it was distilled on",
    "the {a} ranks a {b} by fit before any {c} is served",
    "a contested {a} waits at the {b} until the {c} expires",
)


def _corpus() -> str:
    """Real English filler: the repo's own docs. Synthetic filler trips the
    provider's content filter (two discarded attempts: random word salad and
    template prose — both finish_reason=content_filter with input billed),
    so the probe measures against natural text, offset-varied per run."""
    root = Path(__file__).resolve().parent.parent.parent
    parts = []
    for rel in ("README.md", "CONTEXT.md", "docs/adr/README.md",
                "docs/adr/0005-cost-model-duality.md",
                "docs/adr/0020-energy-estimation.md",
                "docs/adr/0023-llamacpp-viable-local-runtime.md"):
        p = root / rel
        if p.is_file():
            parts.append(p.read_text())
    corpus = "\n\n".join(parts)
    return corpus * 2  # tile so the 8k+ band always has a fresh window


def make_prompt(band: str, seed: int) -> str:
    """Filler = real doc text sized in CHARS for the band; the offset and
    seed line vary per run so provider prompt caching cannot deflate
    medians (different prefix from the first line on)."""
    rng = random.Random(seed)
    target = BAND_TARGET_CHARS[band]
    corpus = _corpus()
    start = rng.randrange(0, max(1, len(corpus) - target))
    body = corpus[start : start + target]
    return (
        f"Reply with the single word OK and nothing else. Context seed {seed}:\n\n{body}"
    )


def _in_band(est_tokens: int, band: str) -> bool:
    lo, hi = BAND_EDGES[band]
    return est_tokens >= lo and (hi is None or est_tokens < hi)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--pace-s", type=float, default=2.0,
                        help="sleep between dispatches: OpenRouter's in-flight "
                             "budget 402s a back-to-back run")
    parser.add_argument("--out", default="samples-latest.json")
    args = parser.parse_args()

    backend = OpenRouterBackend(model=TARGET, timeout_s=120)
    samples: list[dict] = []
    for band in BAND_TARGET_CHARS:
        for run in range(args.runs):
            prompt = make_prompt(band, seed=hash((band, run)) & 0xFFFF)
            messages = [{"role": "user", "content": prompt}]
            t0 = time.time()
            t_first = None
            comp = None
            for item in backend.stream(messages, max_tokens=64):
                if not isinstance(item, str):
                    comp = item
                elif t_first is None:
                    t_first = time.time()
            total_ms = int((time.time() - t0) * 1000)
            first_ms = int(((t_first or time.time()) - t0) * 1000)
            row = {
                "band": band,
                "run": run,
                "prompt_chars": len(prompt),
                "est_tokens": len(prompt) // 4,
                "in_band": _in_band(len(prompt) // 4, band),
                "first_token_ms": first_ms,
                "total_ms": total_ms,
                "tokens_in": comp.tokens_in if comp else None,
                "tokens_out": comp.tokens_out if comp else None,
                "text_len": len(comp.text) if comp else 0,
                "cost_usd": comp.cost_usd if comp else None,
            }
            samples.append(row)
            print(json.dumps(row))
            time.sleep(args.pace_s)

    bad = [s for s in samples if not s["in_band"] or s["tokens_out"] == 0]
    if bad:
        print(f"\n!! {len(bad)} rows out-of-band or empty — DO NOT paste these medians")

    out = Path(__file__).parent / args.out
    out.write_text(json.dumps({"target": TARGET, "samples": samples}, indent=1))
    print(f"\nraw samples -> {out}")
    print("\nmedians (paste into src/kultivait/time_reference.py):")
    for band in BAND_TARGET_CHARS:
        rows = [s for s in samples if s["band"] == band]
        print(
            f'    "{band}": {{"first_token_ms": {int(statistics.median(r["first_token_ms"] for r in rows))}, '
            f'"total_ms": {int(statistics.median(r["total_ms"] for r in rows))}}},'
        )
    total_cost = sum(s["cost_usd"] or 0 for s in samples)
    print(f"\nprobe metered cost: ${total_cost:.4f}")


if __name__ == "__main__":
    main()
