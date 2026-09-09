# Learned centroids from routing history — design

Date: 2026-09-09
Branch: main (wayfinder map #176)
Status: approved via wayfinder map #176 (issues #177–#181); research register: `docs/research/2026-09-09-centroid-signals.md`.

## Problem

Routing centroids are the mean of six static seed prompts per role (`seeds.py`), recomputed at
every boot — the classifier never sees a real prompt distribution. The herd's own ledger now
holds 16,923 routing rows; the research census shows what learning can honestly draw from
today: **gold toll-picks are empty (0 answered)**, ledger snippets are truncated at 80 chars
(insufficient for silver learning), and the one full-text corpus is the **46 escalation
transcripts** (median 581 chars). Embedding cost is negligible (8–20 ms/prompt; sub-second for
all real text). The design must therefore learn from thin, skewed signals without drifting
toward cheap models — the failure this router exists to prevent.

## Locked decisions (map #176 grill)

Offline recalibration only (`centroids learn` → shadow → eval → human cutover); trust
hierarchy (gold = toll picks, silver = served outcomes, escalations = cloud anchors) with
static seeds as a regularizing prior; safety gate = zero dangerous misroutes + accuracy floor
+ toll ceiling + shadow agreement before any cutover; versioned `~/.kultivait/centroids.json`
with `seeds-v0` rollback; separate lane from distillate training; ADR 0021.

## Design

### The learn algorithm — trust-weighted blend, per role

Centroids are learned **per role** (simple/reasoning/docs/architect — the stable classification
space; tiers inherit their role's learned vector at load time, exactly as they inherit seed
means today):

```
c_role = normalize( 1.0 · c_seed  +  Σ_class w_class · mean(embed(texts_class)) )
         w_gold = 1.0 · w_silver = 0.5 · w_escalation = 0.75
```

- The seed prior carries fixed weight **1.0** — a role's learned centroid is never more than
  an equal partner to its prior; empirical weight can exceed 1.0 only in aggregate (many
  signals), never per-signal. Full replacement is structurally impossible.
- **Minimum signal threshold**: a role emits a learned vector only with **≥ 10 usable signals
  (any class, deduped by fingerprint)**; below that the role falls back to `seeds` in the
  candidate table and the provenance records the shortfall. (Gold is empty today; the
  threshold is reachable via escalations + snippet rows without pretending to confidence.)
- Signals label a role: gold → the toll pick's *chosen* role; silver → the serving tier's
  role; escalation → the role the escalations archive classified it under (escalations anchor
  their own role's real distribution — they are proof of cloud-worthiness, never evidence for
  cheapness).

### Signal extraction contract

| Class | Source | Text | Label | Weight |
|---|---|---|---|---|
| gold | tollbooth answered tickets | `original_prompt` | chosen target's role | 1.0 |
| silver | ledger served rows | snippet (usable ≥ 40 chars, non-empty, deduped) | serving tier's role | 0.5 |
| escalation | `~/.kultivait/escalations/` | first user message of the archived conversation | its classified role | 0.75 |

Dedup by conversation fingerprint across all classes; per-class and per-role counts land in
the table's provenance. **Substrate change riding this spec**: the ledger snippet cap rises
80 → **512 chars** (`_decision_meta`), so silver learning improves as history accrues —
retroactively impossible, forward-looking free.

### `centroids.json` + the `[centroids]` seat

```json
{
  "version": "learned-v1",
  "created": "2026-09-09T…",
  "roles": {
    "reasoning": {
      "source": "learned",
      "vector": [ /* float64, L2-normalized */ ],
      "provenance": {"gold": 0, "silver": 12, "escalation": 3, "prior_weight": 1.0}
    },
    "docs": {"source": "seeds", "provenance": {"gold": 0, "silver": 4, "escalation": 0, "prior_weight": 1.0}}
  }
}
```

`seeds-v0` materializes on first `centroids learn` run (the embedded seed means, `source:
"seeds"`, so rollback and baseline comparison are table-to-table). Config seat:

```toml
[centroids]
active_version = "seeds-v0"   # what boot loads; "" or absent = current seed-embed behavior
shadow_version = ""           # candidate under shadow validation; "" = off
```

`build_router` consults the seat: active vectors load from the file (no re-embedding at
boot); missing file / missing role → seed behavior. The candidate never touches `active`
until cutover.

### Shadow instrumentation

Per the research hook: a fire-and-forget job beside the ADR 0017 shadow block in
`_resolve_route` — when `shadow_version` is set, the **already-computed** user-text vector is
classified by a candidate `Router` built once at boot; the disagreement row (incumbent vs
candidate tier, margins, fingerprint) appends to `~/.kultivait/shadow.jsonl` with
`kind: "centroid"`, never the ledger, zero latency impact.

### CLI surface

```
kultivait centroids learn [--min-signal N]   # mine harvest -> learned-vN candidate + provenance
kultivait centroids status                  # versions, per-role provenance, shadow disagreement stats
kultivait centroids cutover --version learned-v1 [--yes]   # [y/N]; flips active_version
                                             # rollback: cutover --version seeds-v0 (instant, boot-level)
```

## Eval handoff (bars pre-registered in #180)

Measured: (1) zero dangerous misroutes on the `routing_trust` held-out set, (2) accuracy ≥
the seed baseline, (3) contested-band toll-rate delta vs seed baseline within a ceiling,
(4) shadow agreement on real traffic (dogfood stream, #181). Bars written before the run;
FAIL honest + dispositioned.

## Out of scope

Online/incremental drift; auto-cutover; distillate-training coupling; embedding-model or
seed-set changes; multi-machine sharing.

## Glossary terms crystallized

*Learned centroid*, *Centroid table*, *Seed prior* — added to `CONTEXT.md`.
