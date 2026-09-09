# Energy coefficient measurement — v1 (2026-09-09)

Ticket: [#168](https://github.com/Standard-Pentest/kultivait/issues/168) · map: [#166](https://github.com/Standard-Pentest/kultivait/issues/166)
Procedure: `docs/research/2026-09-09-local-inference-energy.md` (research #167).

## Provenance

- **Chip**: Apple M4 Pro, 24 GB unified · **Runtime**: ollama 0.32.15 (GGUF Q4_K_M defaults)
- **Tool**: `zeus-apple-silicon` IOReport "Energy Model" windows — **sudo-free**; per-domain
  cumulative mJ (CPU clusters, GPU, GPU SRAM, DRAM, ANE). Windows ≥10 ms, 1 mJ resolution.
- **Method**: streaming `/api/generate`; prefill window = dispatch → first generated token
  (first chunk with `response` **or** `thinking` — thinking models stream reasoning in a
  separate field; caught on the first run); decode window = first token → stream end;
  N=5 per cell, 2 warmups, medians; prompts varied per run to defeat ollama prompt caching
  for prefill cells; idle domain rates (10 s window) subtracted per window by wall time;
  `keep_alive:0` between models.
- **Noise condition, honestly stated**: measured while the dev herd was active on this
  machine (ambient CPU ~7 W during the idle probe). Idle-rate subtraction discounts the
  ambient, but residual inflation is expected, worst for the longest windows (14B decode).
- **Domain-sum caveat**: IOReport domain counters (CPU+GPU+GPU-SRAM+DRAM) are a compute+DRAM
  estimate, not wall power — expected to read *below* system-level figures (register F11/F12).

## Measured medians (Wh per 1K tokens, net of idle)

| Class | Representative | Prefill | Decode |
|---|---|---|---|
| 1.5b | qwen2.5-coder:1.5b | 0.00010 | **0.038** |
| 3b | llama-3.2-3b class | 0.00007 | **0.072** |
| 4b | qwen3.5:4b | 0.0034 | **0.130** |
| 8b | llama3.1:8b | 0.0006 | **0.192** |
| 14b | qwen3:14b | 0.0007 | **0.388** ⚑ |

## Sanity gates (bounds from the research register)

9 of 10 **PASS**: decode monotone with model size (0.038 → 0.072 → 0.130 → 0.192), all within
the hard [0.003, 0.35] band except 14B; prefill ≪ decode per token everywhere (consistent
with F7/F18's "prefill is far cheaper per token", amplified locally by parallel prefill).

**One honest FAIL**: the 14B decode cell (0.388) sits 11% above the extrapolated 0.35 bound.
Disposition (per ADR 0017, pre-declared): this is not a misalignment signature — the
register defines those as ≥0.5 Wh/1K or non-monotone behavior, and the family trend is
cleanly monotone with plausible physics (14B decode is the longest window → most exposed to
the active-herd ambient that idle subtraction only partially discounts). **Flag carried in
`coefficients.toml`; the sanity eval (#171) pre-registers its own final bars and may re-measure
this one cell on a quiet machine.** No silent re-runs, no partial re-scoring.

## Files

- `coefficients.toml` — the committed, versioned table (`energy-v1-20260909`)
- `samples.csv` — one row per request: per-domain mJ, phase durations, token counts, J/tok, Wh/1K
- `summary.json` — medians, idle window, runtime versions
- `measure.py` — the harness (rerun: `uv run --with zeus-apple-silicon python experiments/energy_measurement/measure.py`)

## Two measurement bugs found and fixed during the run (recorded for reproduction)

1. Thinking models stream reasoning in `thinking`, not `response` — first-token detection
   must accept both, else prefill windows swallow all of thinking.
2. Ollama caches prompt KV across identical prompts — prefill cells need per-run prompt
   variants or `prompt_eval_count` reads 0.
