"""Dual-teacher synthetic corpus generator (ADR 0016) — the Gate-clone.

Teachers are two roles over CLI channels (subscription-covered): the judge
teacher (GLM via the opencode CLI — a family with no fitted route target)
generates band-targeted variations and independently labels each variation's
tier in a second pass (the agreement filter: intended == labeled or the pair
drops); the rewriter teacher (claude CLI) writes the rewrite given prompt +
tier. Fit values are NEVER teacher-emitted — they regress from the confirmed
tier (distill.corpus.regress_fits). Surviving pairs pass the 3-stage filter:
dedup (exact normalized hash + embedding cosine > 0.92), schema (contract
JSON parses, tier-consistent fits, monotone descending order), quality
(planted-fact recall on rewrites). Provenance records teacher family,
channel, and seed for every pair; teacher dispatches are ledger-tagged.
"""

from __future__ import annotations

import json
import math
import random
import re
from dataclasses import dataclass, field
from typing import Callable

from kultivait.distill.corpus import (
    CONTRACT_ENUM,
    FIT_BANDS,
    TrainingPair,
    assemble_pair,
    _normalize_strata,
    _quota_split,
)
from kultivait.evals import score_brief

DEDUP_COSINE = 0.92
MIN_RECALL = 0.6
DEFAULT_JUDGE = "glm/opencode"
DEFAULT_REWRITER = "claude/cli"

GENERATION_PROMPT = (
    "You are generating training prompts for a routing judge. Given the seed "
    "prompt below, write ONE new prompt about similar work that a routing "
    "judge would rate as '{band}' difficulty (local = a small local model "
    "clearly suffices; contested = genuinely ambiguous between local and "
    "frontier; frontier = unmistakably frontier work — cross-service or multi-region scale, schema-level design, production risk — that a small local model cannot credibly attempt), framed as a "
    "{task_type} task. Vary phrasing and specifics; do not copy the seed. "
    "Output ONLY the new prompt, nothing else.\n\nSEED PROMPT:\n{seed}"
)

LABEL_PROMPT = (
    "You are a routing judge. Rate whether this prompt can be served by a "
    "small local model or needs a frontier model. Answer with exactly one "
    "word: local, contested, or frontier. A 'local' prompt is simple work a "
    "small model handles; a 'frontier' prompt clearly needs frontier "
    "capability; 'contested' is genuinely ambiguous between the two.\n\n"
    "PROMPT:\n{prompt}"
)

REWRITE_PROMPT = (
    "Rewrite the prompt below to be self-contained and unambiguous. The "
    "routing tier is '{tier}': a local-bound rewrite keeps the original's "
    "economy (short, no added ceremony); a frontier-bound rewrite makes the "
    "task fully self-contained with explicit context and success criteria. "
    "Preserve every load-bearing fact and term from the original. Output "
    "ONLY the rewritten prompt.\n\nPROMPT:\n{prompt}"
)

_VARY = Callable[[str, str, str], str]      # (seed, band, task_type) -> variation
_LABEL = Callable[[str], str]               # prompt -> tier word (independent pass)
_REWRITE = Callable[[str, str], str]        # (prompt, tier) -> rewrite
_EMBED = Callable[[str], list[float]]
_LEDGER = Callable[..., None]


def cosine(a: "list[float]", b: "list[float]") -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", text.lower()).split())


def _facts_of(prompt: str) -> list[dict]:
    """Planted facts: the prompt's distinctive terms must survive the rewrite."""
    terms = [w for w in re.findall(r"[a-zA-Z_]{4,}", prompt.lower())][:6]
    return [{"name": w, "groups": [[w]]} for w in terms] or [{"name": "prompt", "groups": [["prompt"]]}]


class BudgetStop(Exception):
    """Raised by a watchdog fn to stop synthesis cleanly; generate_corpus
    returns the partial corpus (the accepted pairs survive)."""


@dataclass(frozen=True)
class GenerationReport:
    pairs: list[TrainingPair]
    stats: dict = field(default_factory=dict)


def _assign_task_types(count: int, band: str, enum: list[str]) -> list[str]:
    """Round-robin per band so every contract enum value gets its share."""
    offset = {"contested": 0, "local": 2, "frontier": 4}.get(band, 0)
    return [enum[(i + offset) % len(enum)] for i in range(count)]


def _sort_targets_desc(contract_json: str) -> str:
    data = json.loads(contract_json)
    targets = data.get("judge", {}).get("targets", [])
    data["judge"]["targets"] = sorted(targets, key=lambda t: t.get("fit", 0), reverse=True)
    return json.dumps(data)


def generate_corpus(
    seeds: list,
    *,
    vary_fn: _VARY,
    label_fn: _LABEL,
    rewrite_fn: _REWRITE,
    target_pairs: int,
    rng: "random.Random | None" = None,
    strata: "dict | None" = None,
    embed_fn: "_EMBED | None" = None,
    min_recall: float = MIN_RECALL,
    ledger_record: "_LEDGER | None" = None,
    judge_name: str = DEFAULT_JUDGE,
    rewriter_name: str = DEFAULT_REWRITER,
    attempt_budget: "int | None" = None,
) -> GenerationReport:
    """Run the full D2 pipeline over seed anchors up to strata quotas.

    Every teacher call is counted and (when a ledger hook is given) tagged
    `origin=distill-generator` so corpus cost stays visible in the harvest's
    notional lens without touching toll/route analytics.
    """
    if not seeds:
        raise ValueError("no seed anchors: the generator needs the unlabeled pool")
    rng = rng or random.Random(0)
    strata = _normalize_strata(strata or {"contested": 0.4, "local": 0.3, "frontier": 0.3})
    quotas = _quota_split(target_pairs, strata)
    attempts_allowed = attempt_budget or max(target_pairs * 3, 12)

    stats = {"attempts": 0, "agreement_drops": 0, "recall_drops": 0,
             "dedup_drops": 0, "near_dup_drops": 0, "schema_drops": 0, "accepted": 0,
             "per_stratum": {k: 0 for k in quotas}, "per_task_type": {t: 0 for t in CONTRACT_ENUM}}

    def tagged(tier: str, prompt: str, out: str):
        if ledger_record is not None:
            ledger_record(
                tier=f"distill:{tier}", local=False,
                tokens_in=max(1, len(prompt) // 4),
                tokens_out=max(1, len(out) // 4),
                cost_usd=0.0,  # subscription dispatch: no metered cash (ADR 0005)
                origin="distill-generator", orchestrator="distill-teacher",
            )

    accepted: list[TrainingPair] = []
    seen_hashes: set[str] = set()
    seen_vecs: list[list[float]] = []
    band_plans = {band: _assign_task_types(n, band, CONTRACT_ENUM) for band, n in quotas.items()}
    band_idx = {band: 0 for band in quotas}

    attempts = 0
    while attempts < attempts_allowed and any(
        band_idx[b] < quotas[b] for b in quotas
    ):
        band = next(b for b in quotas if band_idx[b] < quotas[b])
        task_type = band_plans[band][band_idx[band] % len(band_plans[band])] \
            if band_plans[band] else CONTRACT_ENUM[0]
        seed = seeds[rng.randrange(len(seeds))]
        attempts += 1
        stats["attempts"] += 1

        # 1. judge teacher: band-targeted variation (BudgetStop breaks cleanly)
        try:
            variation = (vary_fn(seed.prompt, band, task_type) or "").strip()
        except BudgetStop:
            break
        tagged(f"judge:{judge_name}", seed.prompt, variation)
        if not variation or variation == "garbage output":
            stats["agreement_drops"] += 1
            continue

        # 2. agreement filter: independent second-pass tier label
        try:
            label_out = (label_fn(variation) or "").strip().lower()
        except BudgetStop:
            break
        tagged(f"judge:{judge_name}", variation, label_out)
        if label_out not in ("local", "contested", "frontier") or label_out != band:
            stats["agreement_drops"] += 1
            continue

        # 3. dedup: exact normalized hash, then embedding cosine
        norm = _norm(variation)
        if norm in seen_hashes:
            stats["dedup_drops"] += 1
            continue
        if embed_fn is not None:
            vec = embed_fn(variation)
            if any(cosine(vec, prev) > DEDUP_COSINE for prev in seen_vecs):
                stats["near_dup_drops"] += 1
                continue
            seen_vecs.append(vec)
        seen_hashes.add(norm)

        # 4. rewriter teacher — a CLI hiccup drops the PAIR, not the run (#95)
        try:
            rewrite = (rewrite_fn(variation, band) or "").strip()
        except Exception:  # noqa: BLE001 - one rewriter failure must not kill 20h of synthesis
            stats["rewrite_drops"] = stats.get("rewrite_drops", 0) + 1
            seen_hashes.discard(norm)
            continue
        tagged(f"rewriter:{rewriter_name}", variation, rewrite)

        # 5. quality: planted-fact recall on the rewrite
        recall = score_brief(rewrite, _facts_of(variation)).recall
        if recall < min_recall:
            stats["recall_drops"] += 1
            continue

        # 6. schema: serving-shape pair with tier-regressed fits, monotone order
        pair = assemble_pair(variation, band, rng, origin="synthetic-d2",
                             rewrite=rewrite, seed_id=seed.source_id)
        try:
            assistant = _sort_targets_desc(pair.messages[2]["content"])
            contract = json.loads(assistant)
            fits = [t["fit"] for t in contract["judge"]["targets"]]
            lo, hi = FIT_BANDS[band]
            assert fits == sorted(fits, reverse=True) and lo <= fits[0] < hi
            assert set(contract) == {"analysis", "rewrite", "judge"}
        except Exception:  # noqa: BLE001 - schema gate must never crash the run
            stats["schema_drops"] += 1
            continue
        final = TrainingPair(
            messages=[pair.messages[0], pair.messages[1], {"role": "assistant", "content": assistant}],
            stratum=band,
            provenance={**pair.provenance, "teachers": {"judge": judge_name, "rewriter": rewriter_name},
                        "band": band, "task_type": task_type, "agreement_pass": True,
                        "recall": round(recall, 2)},
        )
        accepted.append(final)
        band_idx[band] += 1
        stats["accepted"] += 1
        stats["per_stratum"][band] += 1
        stats["per_task_type"][task_type] = stats["per_task_type"].get(task_type, 0) + 1

    return GenerationReport(pairs=accepted, stats=stats)


# ------------------------------------------------------------- real teachers


def real_teacher_fns(
    judge_cli: str = "opencode",
    rewriter_cli: str = "claude",
    judge_command: "list[str] | None" = None,
    rewriter_command: "list[str] | None" = None,
    judge_model: "str | None" = None,
    vary_model: "str | None" = None,
) -> dict:
    """Real teacher callables (ADR 0016 as amended by the #69 anchor).

    Three-way split by judgment weight: VARIATIONS from a local model when
    ``vary_model`` is given (executor work — creative diversity, free);
    TIER LABELS from the neutral-family API judge when ``judge_model`` is
    given (the judgmental act; e.g. x-ai/grok-4.6 via OpenRouter — the
    only live-validated neutral family after the account's privacy
    guardrails excluded deepseek/mistral); REWRITES from the rewriter CLI
    (claude per ADR 0016). Falls back to CLI judge dispatch when no
    judge_model is given.
    """
    from kultivait.backends import CLIBackend, OllamaBackend
    from kultivait.config import CLI_PRICING

    def backend(cli: str, command) -> CLIBackend:
        cmd = command or [cli]
        p_in, p_out = CLI_PRICING.get(cli, (3.0, 15.0))
        return CLIBackend(command=cmd, price_in=p_in, price_out=p_out)

    rewriter = backend(rewriter_cli, rewriter_command)

    def _ask(be, instruction: str) -> str:
        completion = be.complete([{"role": "user", "content": instruction}])
        return completion.text.strip()

    # judge: neutral-family API dispatch when pinned, else the CLI channel
    if judge_model:
        from kultivait.api_backends import OpenRouterBackend
        from kultivait.credentials import resolve_provider_key

        key = resolve_provider_key("openrouter")
        if not key:
            raise ValueError("judge_model requires an OpenRouter key (none resolved)")
        judge_be = OpenRouterBackend(model=judge_model, api_key=key,
                                     price_in=2.0, price_out=6.0)

        def label_fn(prompt: str) -> str:
            completion = judge_be.complete(
                [{"role": "user", "content": LABEL_PROMPT.format(prompt=prompt)}])
            return completion.text.strip()
    else:
        judge = backend(judge_cli, judge_command)

        def label_fn(prompt: str) -> str:
            return _ask(judge, LABEL_PROMPT.format(prompt=prompt))

    # variations: local model when pinned (executor work), else the judge channel
    if vary_model:
        local = OllamaBackend(vary_model)

        def vary_fn(seed_prompt: str, band: str, task_type: str) -> str:
            completion = local.complete(
                [{"role": "user", "content": GENERATION_PROMPT.format(
                    band=band, task_type=task_type, seed=seed_prompt)}])
            return completion.text.strip()
    elif judge_model:
        from kultivait.api_backends import OpenRouterBackend
        from kultivait.credentials import resolve_provider_key
        key = resolve_provider_key("openrouter")
        judge_be = OpenRouterBackend(model=judge_model, api_key=key,
                                     price_in=2.0, price_out=6.0)

        def vary_fn(seed_prompt: str, band: str, task_type: str) -> str:
            completion = judge_be.complete(
                [{"role": "user", "content": GENERATION_PROMPT.format(
                    band=band, task_type=task_type, seed=seed_prompt)}])
            return completion.text.strip()
    else:
        judge = backend(judge_cli, judge_command)

        def vary_fn(seed_prompt: str, band: str, task_type: str) -> str:
            return _ask(judge, GENERATION_PROMPT.format(
                band=band, task_type=task_type, seed=seed_prompt))

    def rewrite_fn(prompt: str, tier: str) -> str:
        return _ask(rewriter, REWRITE_PROMPT.format(prompt=prompt, tier=tier))

    return {"vary_fn": vary_fn, "label_fn": label_fn, "rewrite_fn": rewrite_fn,
            "ledger_hook": None}
