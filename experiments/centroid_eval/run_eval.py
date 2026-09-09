"""Recalibration safety eval — runs the protocol in protocol.md.

Real harvest (live ledger + escalations), real nomic-embed-text embedder,
candidate from `centroids learn` vs the seeds-v0 baseline, evaluated at
role level on routing_trust's held-out prompts. Writes gates.json +
classifications.csv + printed verdicts.

Run: uv run python experiments/centroid_eval/run_eval.py
"""

import csv
import json
import sys
import time
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).parent
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import numpy as np  # noqa: E402

from kultivait import centroids as cent  # noqa: E402
from kultivait.cli import CONFIG_PATH, LEDGER_PATH, _embed_batch, get_config  # noqa: E402
from kultivait.router import Decision, Router  # noqa: E402
from kultivait.seeds import ROLE_SEEDS  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "experiments"))
from routing_trust import TIERS  # noqa: E402

ROLE_OF_TIER = {
    "llama3.1:8b": "simple", "qwen3:14b": "reasoning",
    "gemini:agy": "docs", "claude": "architect",
}
TIER_OF_ROLE = {v: k for k, v in ROLE_OF_TIER.items()}
CAPABILITY_ROLES = [ROLE_OF_TIER[t] for t in
                    ["llama3.1:8b", "qwen3:14b", "gemini:agy", "claude"]]
TABLE = HERE / "eval_centroids.json"
SHADOW_LOG = HERE / "eval_shadow.jsonl"


def embed(texts):
    return _embed_batch(get_config(), list(texts))


def build_router_from_role_vectors(vectors: dict) -> Router:
    centroids = {TIER_OF_ROLE[r]: vectors[r] for r in vectors}
    order = [TIER_OF_ROLE[r] for r in CAPABILITY_ROLES]
    return Router(centroids=centroids, capability_order=order)


def evaluate(router: Router, prompts: list[tuple[str, str]], vecs) -> list[dict]:
    rows = []
    for (expected_role, prompt), vec in zip(prompts, vecs):
        d = router.classify(vec)
        got_role = ROLE_OF_TIER[d.tier]
        er, gr = CAPABILITY_ROLES.index(expected_role), CAPABILITY_ROLES.index(got_role)
        rows.append({
            "expected": expected_role, "got": got_role, "prompt": prompt,
            "correct": expected_role == got_role,
            "dangerous": gr < er,
            "wasteful": gr > er,
            "margin": round(d.margin, 5), "escalated": d.escalated,
            "contested": d.escalated or d.margin < 0.02,
        })
    return rows


def main() -> None:
    config = get_config()
    tier_roles = {t.name: t.role for t in config.tiers}
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S")

    # 1. learn a candidate from the REAL harvest
    result = cent.learn(
        embed, tier_roles,
        ledger_path=LEDGER_PATH,
        escalations_dir=Path.home() / ".kultivait" / "escalations",
        path=TABLE,
    )
    version = result["version"]
    print(f"candidate: {version}")
    for role, info in result["roles"].items():
        p = info["provenance"]
        print(f"  {role:<10} {info['source']:<7} gold {p['gold']} "
              f"esc {p['escalation']} silver {p['silver']}")

    seed_vecs = cent.role_vectors("seeds-v0", embed, TABLE)
    cand_vecs = cent.role_vectors(version, embed, TABLE)
    seed_router = build_router_from_role_vectors(seed_vecs)
    cand_router = build_router_from_role_vectors(cand_vecs)

    prompts = [(ROLE_OF_TIER[t], p) for t, data in TIERS.items() for p in data["test"]]
    vecs = embed([p for _, p in prompts])

    seed_rows = evaluate(seed_router, prompts, vecs)
    cand_rows = evaluate(cand_router, prompts, vecs)

    with (HERE / "classifications.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(cand_rows[0].keys()))
        w.writeheader()
        for rows, who in ((seed_rows, "seed"), (cand_rows, "candidate")):
            for r in rows:
                w.writerow({"prompt": f"[{who}] {r['prompt'][:60]}", **{k: v for k, v in r.items() if k != "prompt"}})

    seed_correct = sum(r["correct"] for r in seed_rows)
    cand_correct = sum(r["correct"] for r in cand_rows)
    cand_danger = sum(r["dangerous"] for r in cand_rows)
    seed_contested = 100 * sum(r["contested"] for r in seed_rows) / len(seed_rows)
    cand_contested = 100 * sum(r["contested"] for r in cand_rows) / len(cand_rows)

    gates = {
        "R1 zero dangerous misroutes": (cand_danger, cand_danger == 0),
        "R2 accuracy >= seed baseline": (f"{cand_correct} vs {seed_correct}",
                                         cand_correct >= seed_correct),
        "R3 toll-band delta <= 10pp": (f"{cand_contested:.1f}% vs {seed_contested:.1f}%",
                                       abs(cand_contested - seed_contested) <= 10.0),
    }

    # R4: live shadow mechanism — real vector, real table, isolated log
    SHADOW_LOG.unlink(missing_ok=True)
    cent._shadow_cache.clear()
    cand_says = cand_router.classify(vecs[0]).tier
    incumbent = Decision(tier="claude" if cand_says != "claude" else "llama3.1:8b",
                         margin=0.5, escalated=False)
    with patch.object(cent, "seat", return_value={"active_version": "",
                                                  "shadow_version": version}), \
         patch.object(cent, "load_table", return_value=cent.load_table(TABLE)):
        cent.maybe_shadow_classify(vecs[0], incumbent, "eval-fp", config=config,
                                   embed_batch=embed, log_path=SHADOW_LOG)
    shadow_rows = []
    if SHADOW_LOG.is_file():
        shadow_rows = [json.loads(x) for x in SHADOW_LOG.read_text().splitlines() if x.strip()]
    gates["R4 live shadow mechanism"] = (
        f"{len(shadow_rows)} row(s), kind="
        f"{shadow_rows[0]['incumbent'].get('kind') if shadow_rows else '—'}",
        bool(shadow_rows) and shadow_rows[0]["incumbent"].get("kind") == "centroid",
    )

    # R5: provenance sanity
    table = cent.load_table(TABLE)
    prov_ok = (
        "seeds-v0" in table.get("versions", {})
        and version in table.get("versions", {})
        and all(
            all(v >= 0 for k, v in row["provenance"].items() if isinstance(v, int))
            for row in table["versions"][version]["roles"].values()
        )
    )
    gates["R5 provenance sanity"] = ("versions + non-negative counts", prov_ok)

    print(f"\nstamp {stamp} · {len(prompts)} held-out prompts · role-level")
    print("=== GATES ===")
    all_ok = True
    for name, (detail, ok) in gates.items():
        print(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}")
        all_ok = all_ok and ok
    print("\nALL GATES PASS" if all_ok else "\nGATE FAILURE(S) — disposition per protocol")
    (HERE / "gates.json").write_text(json.dumps(
        {"stamp": stamp, "candidate": version,
         **{k: {"detail": str(v[0]), "pass": bool(v[1])} for k, v in gates.items()}},
        indent=2))


if __name__ == "__main__":
    main()
