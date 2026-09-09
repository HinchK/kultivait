# Recalibration safety eval — pre-registered protocol

Ticket: [#180](https://github.com/Standard-Pentest/kultivait/issues/180) · map: [#176](https://github.com/Standard-Pentest/kultivait/issues/176) · ADR 0021
Registered: 2026-09-09, **before any run** (ADR 0015 discipline). Bars are final; results land in `results.md`; FAIL branches reported honestly and dispositioned (ADR 0017).

## Subject

A learned-centroid candidate (`centroids learn` on the **real** harvest — live ledger + escalations, real nomic-embed-text embedder) versus the seed baseline (`seeds-v0`), evaluated **at role level** (the stable classification space, `seeds.py`) on the `experiments/routing_trust.py` held-out set (24 prompts, 4 roles), with the danger direction taken from that experiment's capability order (misrouting *down* is dangerous; up is wasteful).

## Pre-registered gates (pass/fail bars)

| Gate | Metric | Bar |
|---|---|---|
| **R1 dangerous misroutes** | held-out prompts the candidate routes *down* the capability order (expected role → weaker role) | **exactly 0** |
| **R2 accuracy floor** | candidate correct-role count on held-out | **≥ seed baseline's live-measured count** (expected 24) |
| **R3 toll-band delta** | \|contested% (candidate) − contested% (seed)\| on held-out, contested = escalated or margin < 0.02 | **≤ 10 percentage points** |
| **R4 shadow mechanism (live)** | a real-vector forced disagreement logs a `kind: "centroid"` row to an isolated shadow log and never raises | **row present, zero exceptions** |
| **R5 provenance sanity** | every role's provenance counts non-negative and match the extraction census; `seeds-v0` materialized; learned roles carry real counts | **all hold** |

## Pre-declared dispositions

- R1/R2/R3 FAIL: the candidate is **recorded and NOT cut over** — this is a valid protective
  outcome, not an eval failure; #181 (dogfood) proceeds shadow-only or declines, per its ticket.
- R4/R5 FAIL: implementation bug — fix, then **full re-run** of all gates.
- The shadow *agreement-rate* bar on real traffic belongs to #181's dogfood stream (pre-declared
  here so the handoff is explicit: this eval proves the mechanism, #181 measures the volume).
- `uv run pytest -q` must remain green throughout; no partial re-scoring; the harness commits
  raw per-prompt classifications for reproduction.
