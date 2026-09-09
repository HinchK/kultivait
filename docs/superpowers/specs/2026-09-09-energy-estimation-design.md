# Energy estimation in the ledger and harvest — design

Date: 2026-09-09
Branch: main (wayfinder map #166)
Status: approved via wayfinder map #166 (issues #167–#171); research register: `docs/research/2026-09-09-local-inference-energy.md`; measured table: `experiments/energy_measurement/` (energy-v1-20260909).

## Problem

The ledger records two currencies — metered cash and notional value (ADR 0005). The project's
ethos leads with energy ("the greenest token"), yet #139 had to *remove* fabricated
watt-hour claims from the landing because no real accounting existed. This design adds the
third currency honestly: **estimated local-compute energy**, computed from measured
coefficients, labeled as estimates everywhere, never fabricated.

## Locked decisions (map #166 grill)

Local-compute Wh only (no datacenter counterfactual); committed, versioned, cited coefficient
table measured sudo-free (zeus IOReport, #168); surfaces = ledger `est_wh` + energy-model tag
+ new `latency_s`, harvest block, dashboard panel, README + glossary; codified honesty
invariants, test-enforced; pre-registered sanity eval (#171); ADR 0020. Landing page out.

## Design

### Coefficient table — embedded, versioned, overridable

The measured table (`experiments/energy_measurement/coefficients.toml`, provenance in its
README) is **embedded as constants in `src/kultivait/energy.py`** — installed tools have no
`experiments/` tree, so runtime cannot read repo files. The embedded table carries the same
`version = "energy-v1-20260909"` string; `experiments/` remains the provenance record and
regeneration harness. Config overrides values, never provenance:

```toml
# ~/.kultivait/config.toml
[energy]
table_version_override = ""      # non-empty replaces the version tag (self-measured tables)
default_class = "8b"             # bucket for unresolvable models

[[energy.coefficient_overrides]] # per-class value overrides (Wh per 1K tokens)
class = "14b"
prefill = 0.0007
decode = 0.388
```

### Model → class resolution

Class buckets: `1.5b 3b 4b 8b 14b`. Resolution order: explicit `[[energy.class_overrides]]`
`tier = "name" → class`; else parse the tier's model name for a parameter count (`(\d+(?:\.\d+)?)\s*b`,
matched against bucket midpoints, nearest wins — `llama3.1:8b`→8b, `qwen3:14b`→14b,
`kv-judge-llama32-3b-g3`→3b, `qwen2.5-coder:1.5b`→1.5b); else `default_class`. Embedding
calls are **not** in v1 scope (different workload shape; fog item).

### Ledger fields (every dispatch record)

- `est_wh: float` — `(tokens_in × prefill_wh_per_1k + tokens_out × decode_wh_per_1k) / 1000`
  for **local** dispatches; `0.0` for cloud/CLI dispatches (their energy is not ours to claim).
- `energy_model: str` — the coefficient table version tag on every record (the data-layer
  labeling invariant; override string when a self-measured table is configured).
- `latency_s: float` — wall duration of the dispatch, all dispatches (forward-looking
  substrate for any future duration-based method; recorded now because it cannot be
  reconstructed retroactively).

### Harvest block

Rendered after cache economics, same discipline:

```
  energy (estimated · energy-v1-20260909)
    local dispatches     12
    est. energy          2.4 Wh
    per generation
      legacy/incumbent   2.4 Wh  (12 dsp)
```

Rules: header always carries the **est.** word and the table version; totals rounded to
**2 significant figures**; block computed over local dispatches only and says so; footnote
line in `--help`/README pointing at `experiments/energy_measurement/README.md`.

### Dashboard panel

A static "energy (est. · v1)" panel fed from `/api/dashboard/summary` + the dispatch SSE
payload (each event now carries `est_wh` and `energy_model`). Text and sparkline only —
**no animated/live-growing counters** (invariant, test-enforced by asserting the dashboard
template contains no energy-related timers).

### Honesty invariants (test-enforced in #170)

1. Every user-facing energy figure renders with `est.` and the table version adjacent.
2. All displayed values round to 2 significant figures.
3. No dashboard/CLI energy value updates on a timer or animation loop.
4. `est_wh` is 0.0 on non-local dispatches.
5. The version tag on records matches the active table (override-aware).

## Out of scope (v1)

Counterfactual avoided-Wh (datacenter energy for tokens never sent); live power measurement;
embedding/preprocessor/gate-call energy (the table models generation only — fog item when
real volumes justify it); the landing page; per-model (non-class) coefficients.

## Glossary terms crystallized

*Watt-hour estimate* (`est_wh`), *Coefficient table* — added to `CONTEXT.md`.
