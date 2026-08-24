"""PROBE (throwaway) — Wayfinder Map #44 ticket #52: minimal corpus-to-LoRA round-trip.

The full distillation pipeline at toy scale, per ADRs 0012-0017:

  Stage A  corpus: ~90 serving-shape chat-JSONL pairs — real escalation prompts as
           anchors + deterministic band-stratified synthetic variations (40/30/30
           contested/local-clear/frontier-clear), fits REGRESSED from tier labels
           (#46: never copied), stratum metadata per pair. Teacher stages are
           structurally stubbed at probe scale (noted in results): the probe
           exercises data SHAPE, not teacher quality.
  Stage B  training: real mlx_lm.lora QLoRA run on a 4-bit base (Llama-3.2-1B —
           the ADR-0014 'cheaper base first'), documented defaults (#48).
  Stage C  eval: verdict_eval-style gate shapes on a 12-case held-out set — the
           trained adapter vs the incumbent qwen3.5:4b via Ollama (#49 at toy scale).
  Stage D  export: real mlx_lm.fuse + Modelfile emission (the universal fused
           route, #48); `ollama create` printed, not executed (probe hygiene).

Run: uv run --with mlx-lm python experiments/distill_probe.py
Artifacts: experiments/distill_probe/ (corpora, adapter, fused model, Modelfile, results.json)
"""

from __future__ import annotations

import json
import random
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
ART = HERE / "distill_probe"
BASE = "mlx-community/Llama-3.2-1B-Instruct-4bit"
INCUMBENT = "qwen3.5:4b"
SEED = 42

sys.path.insert(0, str(HERE.parent / "src"))
from kultivait.preprocessor import PREPROCESSOR_PROMPT, extract_json  # noqa: E402

CONTRACT_ENUM = ["simple_edit", "debugging", "architecture", "docs_lookup", "compound", "underspecified"]


# ------------------------------------------------------------------ Stage A

LOCAL_FRAME = ["Summarize what {} does in two sentences.", "Explain the purpose of {} simply.",
               "What does this {} configuration flag mean?", "List the steps {} takes, briefly."]
CONTESTED_FRAME = ["Refactor {} to handle edge cases, but keep the public API — decide how deep to go.",
                   "Improve {}'s error handling; some callers may depend on current behavior.",
                   "{} behaves inconsistently under load — investigate and propose a fix.",
                   "Extend {} with caching, weighing complexity against the win."]
FRONTIER_FRAME = ["Design the full architecture to replace {} with a distributed system.",
                  "Overhaul {} for multi-tenant scale: schema, API, migration plan.",
                  "Root-cause the intermittent failure in {} and specify the production fix.",
                  "Draft the technical design doc for evolving {} into a platform."]


def _anchors() -> list[str]:
    """Real prompts: last user message of each escalation archive."""
    esc = Path.home() / ".kultivait" / "escalations"
    out = []
    for f in sorted(esc.glob("*.json")):
        try:
            msgs = json.loads(f.read_text()).get("messages", [])
            for m in reversed(msgs):
                if m.get("role") == "user":
                    t = m.get("content") or ""
                    if isinstance(t, str) and 20 < len(t) < 400:
                        out.append(" ".join(t.split()))
                        break
        except (json.JSONDecodeError, OSError):
            continue
    return out


def _topic(prompt: str) -> str:
    words = re.findall(r"[a-zA-Z_]{4,}", prompt)
    return " ".join(words[:6]) or "the module"


def _fits(tier: str, rng: random.Random) -> tuple[list[dict], float]:
    """Fits regressed from the verdict tier (#46) — never teacher-emitted."""
    if tier == "local":
        top = rng.uniform(0.20, 0.60)
    elif tier == "contested":
        top = rng.uniform(0.66, 0.84)
    else:
        top = rng.uniform(0.86, 0.98)
    others = sorted(rng.uniform(0.05, max(0.1, top - 0.1)) for _ in range(3))
    targets = ["claude", "codex", "gemini", "agy"]
    fits = [{"target": t, "fit": round(f, 3), "effort": "medium"} for t, f in zip(targets, [top, *others])]
    return fits, top


def _pair(prompt: str, tier: str, rng: random.Random) -> dict:
    fits, _ = _fits(tier, rng)
    tt = rng.choice(CONTRACT_ENUM)
    cx = {"local": (1, 4), "contested": (4, 7), "frontier": (6, 9)}[tier]
    contract = {
        "analysis": {"task_type": tt, "complexity": rng.randint(*cx),
                     "signals": ["probe-scale synthetic"], "subtask_candidates": []},
        "rewrite": prompt,  # teacher-rewrite stubbed: toy rewrite = the prompt (noted)
        "judge": {"local_sufficient": tier == "local", "confidence": round(rng.uniform(0.6, 0.95), 2),
                  "targets": fits},
    }
    return {
        "messages": [
            {"role": "system", "content": PREPROCESSOR_PROMPT},
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": json.dumps(contract)},
        ],
        "stratum": tier, "task_type": tt, "origin": "synthetic-probe",
    }


def stage_a() -> dict:
    rng = random.Random(SEED)
    anchors = _anchors()
    pairs, heldout = [], []
    frames = {"local": LOCAL_FRAME, "contested": CONTESTED_FRAME, "frontier": FRONTIER_FRAME}
    quotas = {"contested": 36, "local": 27, "frontier": 27}  # 40/30/30 of 90
    for tier, n in quotas.items():
        for i in range(n):
            seed_prompt = anchors[(i * 7 + len(anchors)) % max(1, len(anchors))] if anchors else "the pipeline"
            prompt = rng.choice(frames[tier]).format(_topic(seed_prompt))
            pairs.append(_pair(prompt, tier, rng))
    # held-out eval set: 4 per band, real anchors where available (never trained on)
    for tier in ("local", "contested", "frontier"):
        for i in range(4):
            seed_prompt = anchors[(i * 11 + 5) % max(1, len(anchors))] if anchors else "the service"
            heldout.append({"prompt": rng.choice(frames[tier]).format(_topic(seed_prompt)), "label": tier})
    ART.mkdir(exist_ok=True)
    rng.shuffle(pairs)
    train, valid = pairs[:72], pairs[72:]
    for name, rows in (("train", train), ("valid", valid)):
        with (ART / f"{name}.jsonl").open("w") as f:
            for r in rows:
                f.write(json.dumps({k: v for k, v in r.items() if k == "messages"}) + "\n")
    (ART / "heldout.json").write_text(json.dumps(heldout, indent=1))
    strata = {t: sum(1 for p in pairs if p["stratum"] == t) for t in quotas}
    return {"anchors_found": len(anchors), "pairs": len(pairs), "strata": strata, "heldout": len(heldout)}


# ------------------------------------------------------------------ Stage B

def stage_b() -> dict:
    t0 = time.monotonic()
    cmd = [sys.executable, "-m", "mlx_lm.lora", "--model", BASE, "--train",
           "--data", str(ART), "--iters", "120", "--batch-size", "4",
           "--num-layers", "8", "--adapter-path", str(ART / "adapters")]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=1500)
    ok = r.returncode == 0
    return {"ok": ok, "minutes": round((time.monotonic() - t0) / 60, 1),
            "tail": (r.stdout + r.stderr).strip().splitlines()[-6:] if ok else (r.stderr or r.stdout)[-600:]}


# ------------------------------------------------------------------ Stage C

def _mlx_eval(cases: list[dict]) -> list[dict]:
    from mlx_lm import load
    from transformers import AutoTokenizer
    model, tokenizer = load(BASE, adapter_path=str(ART / "adapters"))
    hf_tok = AutoTokenizer.from_pretrained(BASE)
    out = []
    for c in cases:
        msgs = [{"role": "system", "content": PREPROCESSOR_PROMPT}, {"role": "user", "content": c["prompt"]}]
        text = hf_tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
        t0 = time.monotonic()
        resp = generate_compat(model, tokenizer, text)
        out.append(_score(resp, c, time.monotonic() - t0))
    return out


def generate_compat(model, tokenizer, prompt: str):
    try:
        from mlx_lm import generate as mlx_generate
        try:
            out = mlx_generate(model, tokenizer, prompt=prompt, max_tokens=512, verbose=False)
        except TypeError:
            out = mlx_generate(model, tokenizer, prompt, max_tokens=512, verbose=False)
    except ImportError:
        from mlx_lm.utils import generate as mlx_generate
        out = mlx_generate(model, tokenizer, prompt=prompt, max_tokens=512, verbose=False)
    if isinstance(out, tuple):
        return out[0]
    return out


def _incumbent_eval(cases: list[dict]) -> list[dict]:
    out = []
    for c in cases:
        body = json.dumps({"model": INCUMBENT, "stream": False, "options": {"num_ctx": 8192},
                           "messages": [{"role": "system", "content": PREPROCESSOR_PROMPT},
                                        {"role": "user", "content": c["prompt"]}]}).encode()
        req = urllib.request.Request("http://localhost:11434/api/chat", data=body,
                                     headers={"content-type": "application/json"})
        t0 = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                msg = json.loads(r.read()).get("message", {}).get("content", "")
        except Exception as e:  # noqa: BLE001
            msg = f"__error__ {e}"
        out.append(_score(msg, c, time.monotonic() - t0))
    return out


def _score(raw: str, case: dict, latency: float) -> dict:
    parsed, err = extract_json(raw)
    verdict, parse_ok = None, bool(parsed)
    if parsed:
        fits = [t.get("fit", 0.0) for t in parsed.get("judge", {}).get("targets", [])
                if isinstance(t, dict)]
        mf = max(fits, default=0.0)
        verdict = "local" if mf < 0.65 else ("frontier" if mf >= 0.85 else "contested")
    dangerous = parse_ok and verdict == "local" and case["label"] == "frontier"
    agree = parse_ok and verdict == case["label"]
    return {"label": case["label"], "parse_ok": parse_ok, "verdict": verdict,
            "dangerous": dangerous, "agree": agree, "latency_s": round(latency, 1)}


def _summary(rows: list[dict]) -> dict:
    n = len(rows)
    return {"n": n, "parse_rate": round(sum(r["parse_ok"] for r in rows) / n, 3),
            "agreement": round(sum(r["agree"] for r in rows) / n, 3),
            "dangerous": sum(r["dangerous"] for r in rows),
            "band_pop": round(sum(1 for r in rows if r["verdict"] == "contested") / n, 3),
            "latency_avg_s": round(sum(r["latency_s"] for r in rows) / n, 1)}


def stage_c() -> dict:
    cases = json.loads((ART / "heldout.json").read_text())
    distilled = _mlx_eval(cases)
    incumbent = _incumbent_eval(cases)
    return {"distilled_llama32_1b": _summary(distilled), f"incumbent_{INCUMBENT}": _summary(incumbent),
            "rows": {"distilled": distilled, "incumbent": incumbent}}


# ------------------------------------------------------------------ Stage D

def stage_d() -> dict:
    t0 = time.monotonic()
    r = subprocess.run([sys.executable, "-m", "mlx_lm.fuse", "--model", BASE,
                        "--adapter-path", str(ART / "adapters"),
                        "--save-path", str(ART / "fused")],
                       capture_output=True, text=True, timeout=900)
    fused_ok = r.returncode == 0 and (ART / "fused").exists()
    modelfile = None
    if fused_ok:
        modelfile = f"""FROM {ART / 'fused'}
TEMPLATE """ + "«contract template: llama-3.2 chat; system = preprocessor contract»" + """
SYSTEM \"\"\"the preprocessor contract (docs/superpowers/specs distillation section)\"\"\"
# ollama create kv-judge-llama32-1b-g0-probe -f Modelfile   (printed, not executed — probe hygiene)
"""
        (ART / "Modelfile").write_text(modelfile)
    return {"fuse_ok": fused_ok, "minutes": round((time.monotonic() - t0) / 60, 1),
            "modelfile_written": modelfile is not None,
            "fuse_tail": (r.stderr or r.stdout).strip().splitlines()[-3:] if not fused_ok else ""}


def main() -> int:
    results: dict = {"probe": "distill round-trip (toy)", "seed": SEED}
    print("== Stage A: corpus assembly (real anchors + synthetic strata)")
    results["corpus"] = stage_a()
    print(json.dumps(results["corpus"]))
    print("== Stage B: mlx_lm.lora QLoRA training (Llama-3.2-1B-4bit, 120 iters)")
    results["training"] = stage_b()
    print(json.dumps({k: v for k, v in results["training"].items() if k != "tail"}))
    if not results["training"]["ok"]:
        (ART / "results.json").write_text(json.dumps(results, indent=2))
        print("PROBE FAIL at training"); return 1
    print("== Stage C: eval — distilled adapter vs incumbent on held-out")
    results["eval"] = stage_c()
    print(json.dumps({k: v for k, v in results["eval"].items() if k != "rows"}))
    print("== Stage D: fuse + Modelfile export")
    results["export"] = stage_d()
    print(json.dumps(results["export"]))
    (ART / "results.json").write_text(json.dumps(results, indent=2))
    ok = results["training"]["ok"] and results["export"]["fuse_ok"]
    print(f"\n{'PROBE PASS' if ok else 'PROBE PARTIAL'} — artifacts: {ART}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
