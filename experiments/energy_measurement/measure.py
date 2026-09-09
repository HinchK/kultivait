"""One-off energy coefficient measurement (map #166, ticket #168).

Sudo-free: zeus-apple-silicon IOReport energy windows around ollama
streaming requests. Prefill window = dispatch -> first token; decode
window = first token -> stream end. N=5 per model, 2 warmups, medians.
Procedure per docs/research/2026-09-09-local-inference-energy.md.
Run: uv run --with zeus-apple-silicon python experiments/energy_measurement/measure.py
"""

import csv
import json
import statistics as stats
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import zeus_apple_silicon as zeus

OLLAMA = "http://localhost:11434"
MODELS = [
    "qwen2.5-coder:1.5b",
    "kv-judge-llama32-3b-g3",
    "qwen3.5:4b",
    "llama3.1:8b",
    "qwen3:14b",
]
N_RUNS = 5
DECODE_TOKENS = 256
PREFILL_TEXT = ("The gardener walks the rows at dawn, noting what survived the night. "
                ) * 130  # ~1800 words -> ~2300 prompt tokens
DECODE_PROMPT = "Tell a story about a garden."
HERE = Path(__file__).parent
MON = zeus.AppleEnergyMonitor()


def ollama_version() -> str:
    try:
        return httpx.get(f"{OLLAMA}/api/version", timeout=5).json().get("version", "?")
    except Exception:
        return "?"


def domain_mj(m) -> dict:
    return {
        "e_cpu_mj": m.cpu_total_mj,
        "e_gpu_mj": m.gpu_mj,
        "e_gpu_sram_mj": m.gpu_sram_mj,
        "e_dram_mj": m.dram_mj,
        "e_ane_mj": m.ane_mj,
    }


def run_once_v2(model: str, prompt: str, num_predict: int, seed: int) -> dict:
    """Streaming request with correct window capture."""
    prefill_m = decode_m = None
    counts: dict = {}
    MON.begin_window("w")
    t0 = time.perf_counter()
    first_tok_at = None
    with httpx.stream(
        "POST",
        f"{OLLAMA}/api/generate",
        json={
            "model": model,
            "prompt": prompt,
            "stream": True,
            "seed": seed,
            "options": {"num_predict": num_predict, "temperature": 0},
        },
        timeout=600,
    ) as resp:
        for line in resp.iter_lines():
            if not line:
                continue
            chunk = json.loads(line)
            if prefill_m is None and (chunk.get("response") or chunk.get("thinking")):
                prefill_m = MON.end_window("w")
                MON.begin_window("w2")
                first_tok_at = time.perf_counter()
            if chunk.get("done"):
                counts = chunk
        if prefill_m is None:
            prefill_m = MON.end_window("w")
            MON.begin_window("w2")
        decode_m = MON.end_window("w2")
    total_s = time.perf_counter() - t0
    return {
        "domains_prefill": domain_mj(prefill_m),
        "domains_decode": domain_mj(decode_m),
        "total_s": total_s,
        "first_tok_s": (first_tok_at - t0) if first_tok_at else total_s,
        "decode_wall_s": (time.perf_counter() - first_tok_at) if first_tok_at else 0.0,
        "prompt_eval_count": counts.get("prompt_eval_count", 0),
        "eval_count": counts.get("eval_count", 0),
        "prompt_eval_duration_s": counts.get("prompt_eval_duration", 0) / 1e9,
        "eval_duration_s": counts.get("eval_duration", 0) / 1e9,
    }


def med(xs):
    return stats.median(xs) if xs else 0.0


def main() -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    runtime = ollama_version()
    rows: list[dict] = []
    print(f"runtime ollama {runtime}; zeus windows; N={N_RUNS} per cell")

    # global idle window (10 s): record idle domain rates
    MON.begin_window("idle")
    time.sleep(10)
    idle = MON.end_window("idle")
    idle_domains = domain_mj(idle)
    print("idle 10s domains:", {k: round(v, 1) for k, v in idle_domains.items()})

    for model in MODELS:
        print(f"\n== {model}")
        for warm in range(2):  # warmup
            run_once_v2(model, DECODE_PROMPT, 32, seed=7)
        for i in range(N_RUNS):
            pre = run_once_v2(model, PREFILL_TEXT + f" Variant {i}.", 1, seed=100 + i)
            dec = run_once_v2(model, DECODE_PROMPT, DECODE_TOKENS, seed=200 + i)
            for phase, r in (("prefill", pre), ("decode", dec)):
                e = dict(r["domains_prefill"] if phase == "prefill" else r["domains_decode"])
                n = r["prompt_eval_count"] if phase == "prefill" else r["eval_count"]
                wall = r["first_tok_s"] if phase == "prefill" else r["decode_wall_s"]
                for k in list(e):  # subtract idle rates measured over the global window
                    e[k] = max(0.0, e[k] - (idle_domains[k] / 10.0) * wall)
                dom_mj = e["e_cpu_mj"] + e["e_gpu_mj"] + e["e_gpu_sram_mj"] + e["e_dram_mj"]
                jpt = (dom_mj / 1000.0) / max(1, n)
                rows.append({
                    "model": model, "phase": phase, "run": i,
                    "n_tokens": n,
                    "phase_s": r["prompt_eval_duration_s"] if phase == "prefill"
                               else r["eval_duration_s"],
                    **{k: round(v, 2) for k, v in e.items()},
                    "e_domains_mj": round(dom_mj, 2),
                    "j_per_tok": round(jpt, 4),
                    "wh_per_1k_tok": round(jpt * 1000 / 3600, 5),
                    "timestamp": stamp,
                })
            print(f"  run{i}: prefill {rows[-2]['wh_per_1k_tok']} | "
                  f"decode {rows[-1]['wh_per_1k_tok']} Wh/1K")
        httpx.post(f"{OLLAMA}/api/generate",
                   json={"model": model, "keep_alive": 0}, timeout=30)

    with (HERE / "samples.csv").open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    # summary table (medians)
    summary = {}
    for model in MODELS:
        for phase in ("prefill", "decode"):
            vals = [r["wh_per_1k_tok"] for r in rows
                    if r["model"] == model and r["phase"] == phase]
            summary[f"{model}|{phase}"] = round(med(vals), 5)
    (HERE / "summary.json").write_text(json.dumps({
        "stamp": stamp, "ollama": runtime, "medians_wh_per_1k": summary,
        "idle_10s_domains_mj": idle_domains,
    }, indent=2))
    print("\nmedians (Wh/1K tokens):")
    for k, v in summary.items():
        print(f"  {k}: {v}")

    # inline sanity gates (bounds from the research register)
    gates = []
    for model in MODELS:
        d = summary.get(f"{model}|decode")
        p = summary.get(f"{model}|prefill")
        if d is None:
            continue
        gates.append((f"{model} decode in [0.003, 0.35] Wh/1K", 0.003 <= d <= 0.35))
        if p:
            gates.append((f"{model} prefill <= decode per token", p <= d * 1.5))
    print("\nsanity gates:")
    ok = True
    for name, passed in gates:
        print(f"{'PASS' if passed else 'FAIL'}  {name}")
        ok = ok and passed
    print("\nALL GATES PASS" if ok else "\nGATE FAILURE — see register bounds")


if __name__ == "__main__":
    main()
