# Distillation-quality sweep — pre-registered bars (grown corpus v2)

Ticket: [#189](https://github.com/Standard-Pentest/kultivait/issues/189) · map: [#187](https://github.com/Standard-Pentest/kultivait/issues/187) · ADR 0022
Registered: 2026-09-09, **before any run against the 8-transcript corpus** (ADR 0015 discipline). `results.json` currently holds only legacy 3-doc rows; the #190 sweep starts fresh cells for the new docs and these bars govern.

## Subject

The full sweep: garden models × prompts (v1, v2) × **8 transcripts** (3 legacy + 5 new shapes), `--gen-loss 2`, on-machine against ollama. Every bar below is per-model, computed over that model's 16 cells (8 docs × 2 prompts).

## Pre-registered gates (pass/fail bars)

| Gate | Metric (per model) | Bar |
|---|---|---|
| **B1 incumbent recall** | `qwen3:14b` mean recall | **≥ 0.90** |
| **B2 any-model floor** | every model's mean recall | **≥ 0.85** |
| **B3 tokens-kept ceiling** | every model's mean `tokens_after / tokens_before` | **≤ 0.70** |
| **B4 generation-2 survival** | every model's mean `gen2_recall` | **≥ 0.80** |
| **B5 artifact parity** | README distiller table recomputes from `results.json` (model-free check) | **exact** |

## Measurement definitions (frozen)

- Mean recall per model = Σ cell recall / 16, unweighted across docs and prompts.
- Legacy rows (3-doc cells) do **not** enter these bars; only cells on the 8-doc corpus count.
- `gen2_recall` is the survival of the fact set in the brief *of the brief* (second generation).
- Missing `gen2_recall` fields count as not-measured, excluded from B4's denominator only if the entire sweep lacks them; a partial absence fails the sweep as incomplete.

## Pre-declared dispositions

- B1/B2 FAIL: that model is recorded ineligible as the recommended distiller; the README table's recommendation line (if any) must reflect it. No re-run without a cause hypothesis; a fix requires the **full sweep re-run**.
- B3 FAIL (over-retention, briefs too fat): recorded; the prompt-follow-up ticket (out of map scope) inherits the evidence.
- B4 FAIL (compounding loss): recorded as the harness's headline finding — that is the metric existing to be exposed; no disposition beyond honest reporting and the follow-up ticket.
- B5 FAIL: implementation bug in emission or parity test — fix, full re-run of the parity check (model-free).
- `uv run pytest -q` green throughout.
