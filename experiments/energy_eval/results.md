# Energy sanity eval — results

Protocol: `protocol.md` (bars pre-registered 2026-09-09, commit `09e53d3`, before the run).
Harness: `run_eval.py`; machine: M4 Pro, dev herd active (same condition as the #168 measurement).

## Verdict: ALL GATES PASS

| Gate | Bar | Result | |
|---|---|---|---|
| E1 coefficient bounds | 1.5b–8b ∈ [0.003, 0.35]; 14b ∈ [0.10, 0.50] | 0.0378 / 0.0721 / 0.1304 / 0.1924 / 0.3876 | PASS |
| E2 monotonicity | decode strictly increasing | 0.038 < 0.072 < 0.130 < 0.192 < 0.388 | PASS |
| E3 sum consistency | harvest == Σ local est_wh, ±1e-9, non-local excluded | 0.569100 vs 0.569100, 3 dsp (non-local row contributed 0) | PASS |
| E4 live path | real proxy dispatch carries est_wh>0, tag, latency_s>0 | est_wh=0.01531, energy_model=energy-v1-20260909, latency_s=5.303 | PASS |
| E5 render invariants | literal `energy (estimated · energy-v1-20260909)` + Wh | header present on the live ledger's harvest | PASS |
| E6 dashboard | panel ids + est. labeling + zero timers | present; template has no setInterval/setTimeout | PASS |

## Honest observations + dispositions

- **The 14B cell passed inside its dispositioned band** (0.388 ∈ [0.10, 0.50]) but remains above
  the extrapolated 0.35. The protocol's quiet-machine cell re-measure stays **authorized, not
  exercised**: the only machine with the garden is the one running the herd, and quiescing it
  from inside a herd seat isn't possible. The flag stays on the table row's provenance; a future
  quiet re-measure may tighten the cell in place only if it lands in [0.10, 0.35].
- E4's live number self-checks: a ~4K-token prompt through the 4b prefill coefficient
  (0.00341/1K) plus a short decode ≈ 0.0153 Wh — exactly what the ledger recorded.
- E3's synthetic ledger included a legacy-tagged row (`energy-v0-legacy`) proving mixed-version
  ledgers sum correctly while the header keeps the latest tag (the ADR 0020 read rule).
- The eval ran under the same busy-machine condition as the measurement; bounds held anyway.

Reproduce: `uv run python experiments/energy_eval/run_eval.py`
Suite at results time: `uv run pytest -q` → **750 passed, 2 skipped**.
