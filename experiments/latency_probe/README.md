# Frontier-latency reference probe — provenance

The `time-v1-20260913-anthropic/claude-sonnet-5` table embedded in
`src/kultivait/time_reference.py` was measured here.

## Status (2026-09-13): harness validated, values pending credits

Two probe attempts were discarded — both `finish_reason: content_filter`
with the input tokens still billed ($1.58 total, kept as
`samples-*-discarded-*.json`): random word salad and template prose both
trip Anthropic's filter; real doc text passes (validated live). A third
run (real-doc corpus, paced) was blocked by OpenRouter credit exhaustion
($10.00 granted / $10.01 used — balance $0.00). Until credits land, the
committed table is empty and the harvest degrades honestly per the #215
pin: "no reference — local medians only."

**Finish command** (after topping up https://openrouter.ai/settings/credits):

    uv run python experiments/latency_probe/run_probe.py --out samples-<date>.json

then paste the printed medians into `REFERENCE_MEDIANS` in
`src/kultivait/time_reference.py` (values only; bump the version's date if
a new season). The script self-checks: it refuses ("DO NOT paste") when any
row is out-of-band or empty.

- **Target**: `anthropic/claude-sonnet-5` via OpenRouter (direct API key),
  one named stable target per the #215 pin — chosen for the pin's
  "claude-sonnet-5 class" wording; re-probe per season or on an explicit
  table bump, never by editing values in place.
- **Method**: `run_probe.py` — n=10 per band, streaming through
  `OpenRouterBackend` (the product's own buffered-relay path, not a bare
  HTTP client), `max_tokens=64`, paced 2 s between dispatches (OpenRouter's
  in-flight budget 402s a back-to-back run). First-token = first yielded
  text delta; total = stream open to Completion. Filler = the repo's own
  docs (README/CONTEXT/ADRs), offset- and seed-varied per run so provider
  prompt caching cannot deflate medians.
- **Bands** (prompt-token estimate, chars//4): 0–2k probed at ~1k, 2–8k at
  ~5k, 8k+ at ~10k; each row self-validates `in_band`.
- **Raw samples**: `samples-*.json` in this directory — the committed
  evidence; the src constants carry only the medians.
- **Cost**: printed at the end of each run (metered; ≈$0.50 at 2026-09-13
  prices for 30 paced dispatches).
- **Caveats**: measured from the dev machine's network path (residential
  uplink); first-token includes TLS + OpenRouter routing overhead, which is
  the honest number for "what the frontier costs this install". Values are
  config-overridable per band; provenance never is.

