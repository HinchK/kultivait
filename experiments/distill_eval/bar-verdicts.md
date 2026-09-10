# Distillation-quality sweep — bar verdicts (protocol.md, 2026-09-09)

Sweep: 5 models × 2 prompts × 8 transcripts, `--gen-loss 2`, uniform protocol-v2
artifact (`results.json`; the pre-protocol 3-doc rows preserved in
`results-legacy-3doc.json` — the frozen definitions demanded 16 uniform cells per
model, so the legacy docs were re-run under this protocol rather than mixed).
Runtime: on-machine ollama, M4 Pro; ~30 min across the five models.

## Verdicts — honest, per the committed bars

| Gate | Bar | Result | Verdict |
|---|---|---|---|
| B1 incumbent recall | qwen3:14b mean ≥ 0.90 | **0.870** | **FAIL** (marginal) |
| B2 any-model floor | every model ≥ 0.85 | gemma4 **0.940** ✓ · phi4 **0.915** ✓ · qwen3 0.870 ✓ · qwen2.5 **0.834** ✗ · llama3.1:8b **0.766** ✗ | **FAIL** (2 models) |
| B3 tokens-kept ceiling | every model ≤ 0.70 | phi4 **74.1%** ✗ (others ≤ 67.8%) | **FAIL** (1 model) |
| B4 gen-2 survival | every model ≥ 0.80 | gemma4 **0.917** ✓ · phi4 0.898 ✓ · qwen3 0.866 ✓ · qwen2.5 **0.781** ✗ · llama3.1:8b **0.690** ✗ | **FAIL** (2 models) |
| B5 table parity | README table == emission from results.json | parity test `tests/test_distill_table_parity.py` green | **PASS** |

## Dispositions executed (per protocol.md, pre-declared)

- **Ineligible as recommended distiller** (B2 FAIL): `llama3.1:8b`, `qwen2.5:14b`.
  `gemma4:latest` is the only model passing every bar — the README table's
  top row reflects that mechanically, and its recommendation prose is unchanged.
- **B3 over-retention** (phi4 keeps 74.1% — briefs too fat): recorded; the
  prompt-engineering follow-up (out of map scope) inherits the evidence.
- **B4 compounding loss** exposed as designed: llama3.1:8b loses 31% of
  planted facts by generation 2; qwen2.5 22%. This is the metric's headline
  finding — honest reporting, no disposition beyond the follow-up ticket.
- **A README claim falsified and corrected**: the old "hardened prompt variant
  tested and rejected" (a 3-doc-corpus result) no longer holds — on the
  8-doc corpus, v2 outperforms v1 for four of five models. Prose updated;
  the parity pin keeps the numbers honest from here.

## Headline finding

The grown corpus is *harder* than the legacy one (multi-turn shapes expose
retention small models don't have): every model's recall is lower on the
8-doc set than the legacy 3-doc artifact reported — the old table flattered
the fleet. gemma4:latest remains the standout (94% recall, 68% kept, 92%
gen-2 survival); the incumbent qwen3:14b misses its own bar by 3 points.

Reproduce: `uv run python experiments/distill_eval/run.py --gen-loss 2`
(resumable; per-model invocation supported). Table:
`uv run python experiments/distill_eval/run.py --emit-table`.
Suite at verdict time: **771 passed, 2 skipped**.
