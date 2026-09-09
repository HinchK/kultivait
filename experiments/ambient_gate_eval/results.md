# Ambient-gates brief-quality eval — results

Protocol: `protocol.md` (bars pre-registered 2026-09-08, commit `b12a174`, before the run).
Run: 2026-09-08, real standalone gate (`build_gate(get_config())`, distill model `qwen3:14b`
via ollama per live config), 10 synthetic Claude-JSONL transcripts (6 planted facts each,
~1,240 source tokens each), SubagentStop payloads, isolated `$HOME`. Harness: `run_eval.py`;
raw outputs: `gates.json`, `planted.json`, `transcripts/`, `briefs/`.

## Verdict: ALL SIX GATES PASS

| Gate | Bar | Result | |
|---|---|---|---|
| G1 brief recall (mean) | ≥ 80% | **96.7%** (58/60 facts) | PASS |
| G1b worst-case recall | ≥ 60% | **83.3%** (t03, t06: 5/6 each) | PASS |
| G2 tokens-kept (mean) | ≤ 60% | **18.4%** (range 11.1–26.4%) | PASS |
| G3 kill durability | ≥ 3/3 | **3/3** (kill -9 at 2.0 s mid-distill; compost intact) | PASS |
| G4 injection latency p95 | ≤ 50 ms | **0.05 ms** | PASS |
| G5 sync-prefix budget p95 | ≤ 1000 ms | **0.37 ms** | PASS |

## Honest observations

- Distill wall-clock ran 10.2–19.9 s per transcript on `qwen3:14b` — exactly the stall
  `async: true` exists to prevent; the sync-prefix measurement (0.37 ms) confirms the
  pre-model work the host could ever see is negligible even if async semantics failed.
- Missed facts (t03, t06) were one constraint and one decision respectively; the two
  path-facts were retained in all 10 briefs. No systematic miss pattern.
- G2's margin is large because the synthetic transcripts are narration-heavy (the planted
  payloads are sparse by design); production transcripts will sit higher. The bar held.
- Kill trials at 2.0 s land inside model loading/generation; compost contained the full
  quadrupled transcript each time — the `Gate.distill` ordering is the load-bearing
  mechanism, as pinned in `tests/test_ambient.py`.

Reproduce: `uv run python experiments/ambient_gate_eval/run_eval.py`
