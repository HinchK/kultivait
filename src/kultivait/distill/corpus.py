"""Corpus builder foundations (ADR 0013): anchors with tiered trust from the
harvest, the permanent held-out split, tier-regressed fits, and serving-shape
training-pair emission.

Label discipline is absolute here: verdict-bearing outcomes (toll picks,
counterfactuals, policy results, eval outcomes) are gold/silver/bronze labels
and NEVER enter training — they are the permanent held-out eval set. Only
unlabeled prompts (the escalation pool) seed synthetic generation. Fit values
are regressed from verdict-tier labels (band placement + spread); the
incumbent judge's own fits are never read (the #14 calibration bug would
clone).
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path

from kultivait.preprocessor import PREPROCESSOR_PROMPT

TRUST_GOLD = "gold"
TRUST_SILVER = "silver"
TRUST_BRONZE = "bronze"
TRUST_UNLABELED = "unlabeled"

# tier -> (low, high) exclusive band for the top fit (ADR 0013; the verdict bands)
FIT_BANDS = {"local": (0.0, 0.65), "contested": (0.65, 0.85), "frontier": (0.85, 1.0)}
JUDGE_TARGETS = ["claude", "codex", "gemini", "agy"]

DEFAULT_STRATA = {"contested": 0.4, "local": 0.3, "frontier": 0.3}  # ADR 0016
CONTRACT_ENUM = ["simple_edit", "debugging", "architecture", "docs_lookup", "compound", "underspecified"]
_COMPLEXITY_BANDS = {"local": (1, 4), "contested": (4, 7), "frontier": (6, 9)}


@dataclass(frozen=True)
class Anchor:
    prompt: str
    tier: str  # "local" | "contested" | "frontier" | "" (unlabeled)
    trust: str  # TRUST_*
    origin: str  # toll_pick | counterfactual | auto_policy | capability_eval | escalation
    source_id: str
    route_target: str = ""  # the route_choice string that produced the label


@dataclass(frozen=True)
class TrainingPair:
    messages: list[dict]  # serving shape: system=contract, user=prompt, assistant=contract JSON
    stratum: str
    provenance: dict = field(default_factory=dict)


def _tier_from_route(route_choice: str) -> str:
    if not route_choice:
        return ""
    if "frontier" in route_choice:
        return "frontier"
    if route_choice.endswith(":local") or route_choice == "local":
        return "local"
    return ""


def _last_user_text(messages: list[dict]) -> str:
    for m in reversed(messages):
        if isinstance(m, dict) and m.get("role") == "user":
            content = m.get("content", "")
            if isinstance(content, str):
                return " ".join(content.split())
            if isinstance(content, list):
                text = "".join(
                    part.get("text", "")
                    for part in content
                    if isinstance(part, dict) and part.get("type") == "text"
                )
                return " ".join(text.split())
    return ""


def extract_anchors(
    ledger_entries: "list[dict]",
    escalation_cases: "list[dict]",
    eval_cases: "list[dict] | None" = None,
) -> list[Anchor]:
    """Harvest rows -> Anchors with tiered trust (ADR 0013).

    gold: human toll picks. silver: expired counterfactuals + auto-policy
    outcomes. bronze: capability-eval outcomes. unlabeled: escalation prompts
    (the generation seed pool). Incumbent-derived verdicts without a routing
    OUTCOME never label anything; downgrades (fallback_reason) belong to the
    escalation store, not here.
    """
    anchors: list[Anchor] = []
    for i, e in enumerate(ledger_entries):
        if not isinstance(e, dict) or e.get("fallback_reason"):
            continue
        snippet = (e.get("snippet") or "").strip()
        if not snippet:
            continue
        toll = e.get("toll")
        route = e.get("route_choice") or ""
        if toll == "answered" and route.startswith("human:"):
            anchors.append(Anchor(snippet, _tier_from_route(route), TRUST_GOLD,
                                  "toll_pick", f"ledger:{i}", route))
        elif toll == "expired" and route:
            anchors.append(Anchor(snippet, _tier_from_route(route), TRUST_SILVER,
                                  "counterfactual", f"ledger:{i}", route))
        elif route.startswith("auto:"):
            anchors.append(Anchor(snippet, _tier_from_route(route), TRUST_SILVER,
                                  "auto_policy", f"ledger:{i}", route))
    for esc in escalation_cases:
        prompt = _last_user_text(esc.get("messages", []))
        if not prompt:
            continue
        anchors.append(Anchor(prompt, "", TRUST_UNLABELED, "escalation",
                              f"escalation:{esc.get('id', id(esc))}"))
    for case in eval_cases or []:
        prompt = (case.get("prompt") or "").strip()
        if not prompt:
            continue
        anchors.append(Anchor(prompt, case.get("tier", ""), TRUST_BRONZE,
                              "capability_eval", str(case.get("case_id", id(case)))))
    return anchors


def split_heldout(anchors: "list[Anchor]") -> "tuple[list[Anchor], list[Anchor]]":
    """Partition into (train-seed anchors, held-out eval anchors).

    Every verdict-bearing (labeled) anchor is permanently held out — real
    labeled cases are never trained on (ADR 0013). Unlabeled anchors seed
    synthetic generation. Disjointness is proven: a source id appearing on
    both sides is a bug, not a judgment call.
    """
    seeds = [a for a in anchors if a.tier == ""]
    heldout = [a for a in anchors if a.tier != ""]
    seed_ids = {a.source_id for a in seeds}
    held_ids = {a.source_id for a in heldout}
    overlap = seed_ids & held_ids
    if overlap:
        raise ValueError(f"held-out split is not disjoint: {sorted(overlap)}")
    return seeds, heldout


def regress_fits(tier: str, rng: random.Random) -> "tuple[list[dict], float]":
    """Regress judge fits FROM a verdict tier (band placement + spread).

    Pure function of (tier, rng): the incumbent judge's fits are never read.
    Top fit lands in the tier's band; the remaining targets scatter below it.
    """
    low, high = FIT_BANDS[tier]
    top = rng.uniform(low + 0.02, high - 0.01)
    others = sorted(round(top * rng.uniform(0.1, 0.8), 3) for _ in range(len(JUDGE_TARGETS) - 1))
    fits = [
        {"target": t, "fit": round(f, 3), "effort": "medium"}
        for t, f in zip(JUDGE_TARGETS, [top, *others])
    ]
    return fits, top


def assemble_pair(
    prompt: str,
    tier: str,
    rng: random.Random,
    *,
    origin: str = "synthetic",
    rewrite: "str | None" = None,
    seed_id: str = "",
) -> TrainingPair:
    """One serving-shape training pair: system = the live contract, user =
    the prompt, assistant = the complete contract JSON (ADR 0013)."""
    fits, _ = regress_fits(tier, rng)
    contract = {
        "analysis": {
            "task_type": rng.choice(CONTRACT_ENUM),
            "complexity": rng.randint(*_COMPLEXITY_BANDS[tier]),
            "signals": [f"distill-corpus {origin}"],
            "subtask_candidates": [],
        },
        "rewrite": rewrite if rewrite is not None else prompt,
        "judge": {
            "local_sufficient": tier == "local",
            "confidence": round(rng.uniform(0.6, 0.95), 2),
            "targets": fits,
        },
    }
    return TrainingPair(
        messages=[
            {"role": "system", "content": PREPROCESSOR_PROMPT},
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": json.dumps(contract)},
        ],
        stratum=tier,
        provenance={"origin": origin, "seed": seed_id},
    )


_FRAMES = {
    "local": ["Summarize: {}", "Explain briefly: {}", "What does {} do, in short?"],
    "contested": ["Refactor {} carefully, weighing depth against risk.",
                  "Improve {}'s error handling with judgment calls.",
                  "Investigate the inconsistency in {} and propose a fix."],
    "frontier": ["Design the full architecture to replace {}.",
                 "Overhaul {} for production scale: schema, API, migration.",
                 "Root-cause {} and specify the complete fix."],
}


def _normalize_strata(strata) -> dict:
    """Accept (contested, local, frontier) tuples or full dicts."""
    if isinstance(strata, dict):
        return dict(strata)
    contested, local, frontier = strata
    return {"contested": contested, "local": local, "frontier": frontier}


def _quota_split(total: int, strata: dict) -> dict:
    """Exact integer quotas per stratum (largest-remainder)."""
    raw = {k: total * v for k, v in strata.items()}
    counts = {k: int(v) for k, v in raw.items()}
    remainder = total - sum(counts.values())
    for k in sorted(raw, key=lambda k: raw[k] - int(raw[k]), reverse=True):
        if remainder <= 0:
            break
        counts[k] += 1
        remainder -= 1
    return counts


def build_corpus(
    seeds: "list[Anchor]",
    *,
    target_pairs: int,
    strata: "dict | None" = None,
    rng: random.Random | None = None,
    valid_frac: float = 0.2,
    pair_fn=assemble_pair,
) -> "tuple[list[TrainingPair], list[TrainingPair]]":
    """Synthesize the toy corpus: framed variations of seed prompts, labeled
    per stratum quotas. D2's generator replaces this labeling with the
    teacher + agreement filter; the pair shape and quotas are the contract.
    """
    rng = rng or random.Random(0)
    strata = _normalize_strata(strata or DEFAULT_STRATA)
    if not seeds:
        raise ValueError("no seed anchors: the corpus needs the unlabeled prompt pool")
    quotas = _quota_split(target_pairs, strata)
    pairs: list[TrainingPair] = []
    seen_prompts: set[str] = set()
    for tier, n in quotas.items():
        frames = _FRAMES[tier]
        for i in range(n):
            seed = seeds[(i * 7 + 1) % len(seeds)]
            base = seed.prompt[:120]
            candidates = [f.format(base) for f in frames] + [
                f"{f.format(base)} (case {i})" for f in frames
            ]
            prompt = next((c for c in candidates if c not in seen_prompts), None)
            if prompt is None:
                prompt = f"{frames[i % len(frames)].format(base)} (variant {i}-{tier})"
            seen_prompts.add(prompt)
            pairs.append(pair_fn(prompt, tier, rng, origin="synthetic-v1",
                                 seed_id=seed.source_id))
    rng.shuffle(pairs)
    n_valid = max(1, int(len(pairs) * valid_frac)) if len(pairs) > 1 else 0
    return pairs[: len(pairs) - n_valid], pairs[len(pairs) - n_valid :] if n_valid else pairs[len(pairs):]


def write_corpus(
    train: "list[TrainingPair]",
    valid: "list[TrainingPair]",
    out_dir: Path,
    heldout: "list[Anchor] | None" = None,
) -> None:
    """Emit mlx-lm chat JSONL (messages only) + aligned metadata sidecar +
    the held-out roster. The roster is the audit artifact proving no real
    verdict-bearing case was trained on."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, rows in (("train", train), ("valid", valid)):
        with (out_dir / f"{name}.jsonl").open("w") as f:
            for p in rows:
                f.write(json.dumps({"messages": p.messages}) + "\n")
    with (out_dir / "metadata.jsonl").open("w") as f:
        for p in train + valid:
            f.write(json.dumps({"stratum": p.stratum, "provenance": p.provenance}) + "\n")
    if heldout is not None:
        with (out_dir / "heldout.jsonl").open("w") as f:
            for a in heldout:
                f.write(json.dumps({
                    "source_id": a.source_id, "tier": a.tier,
                    "trust": a.trust, "origin": a.origin,
                }) + "\n")


def load_harvest(harvest_dir: Path) -> "tuple[list[dict], list[dict]]":
    """Read the live harvest: ledger rows + parsed escalation cases."""
    harvest_dir = Path(harvest_dir)
    entries: list[dict] = []
    ledger = harvest_dir / "ledger.jsonl"
    if ledger.exists():
        with ledger.open() as f:
            entries = [json.loads(line) for line in f if line.strip()]
    escalations: list[dict] = []
    esc_dir = harvest_dir / "escalations"
    if esc_dir.is_dir():
        for p in sorted(esc_dir.glob("*.json")):
            try:
                escalations.append(json.loads(p.read_text()))
            except json.JSONDecodeError:
                continue
    return entries, escalations


def dry_run_report(harvest_dir: Path, eval_cases: "list[dict] | None" = None) -> dict:
    """The D1 demo: anchors, tiered trust counts, and the held-out roster,
    materialized from a real (or fixture) harvest directory."""
    entries, escalations = load_harvest(Path(harvest_dir))
    anchors = extract_anchors(entries, escalations, eval_cases or [])
    seeds, heldout = split_heldout(anchors)
    by_trust: dict[str, int] = {}
    by_origin: dict[str, int] = {}
    for a in anchors:
        by_trust[a.trust] = by_trust.get(a.trust, 0) + 1
        by_origin[a.origin] = by_origin.get(a.origin, 0) + 1
    return {
        "harvest_dir": str(harvest_dir),
        "anchors": {"total": len(anchors)},
        "by_trust": by_trust,
        "by_origin": by_origin,
        "train_seed_count": len(seeds),
        "heldout_roster": [
            {"source_id": a.source_id, "tier": a.tier, "trust": a.trust,
             "origin": a.origin, "route_target": a.route_target}
            for a in heldout
        ],
        "strata": dict(DEFAULT_STRATA),
    }
