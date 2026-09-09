# Energy sanity eval — pre-registered protocol

Ticket: [#171](https://github.com/Standard-Pentest/kultivait/issues/171) · map: [#166](https://github.com/Standard-Pentest/kultivait/issues/166) · ADR 0020
Registered: 2026-09-09, **before any run** (ADR 0015 discipline). Bars are final; results land in `results.md`; FAIL branches are reported honestly and dispositioned (ADR 0017).

## Subject

The shipped energy estimation end-to-end: the embedded coefficient table (`src/kultivait/energy.py`, `energy-v1-20260909`, mirroring `experiments/energy_measurement/`), the ledger fields (`est_wh`, `energy_model`, `latency_s`), harvest aggregation + rendering, the dashboard payload, and one live rehearsal dispatch through a real proxy.

## Pre-registered gates (pass/fail bars)

| Gate | Metric | Bar |
|---|---|---|
| **E1 coefficient bounds** | decode Wh/1K per class, vs register bounds | classes 1.5b–8b each in **[0.003, 0.35]**; class 14b in **[0.10, 0.50]** (pre-declared #168 disposition: extrapolated 0.35 does not bound a domain-sum on a busy machine; the register's own misalignment threshold is 0.5) |
| **E2 monotonicity** | decode coefficient strictly increasing with class size | **1.5b < 3b < 4b < 8b < 14b**, all strict |
| **E3 sum consistency** | harvest `energy.est_wh` vs direct sum over local rows | **equal within 1e-9**; dispatch count exact; non-local rows contribute exactly 0 |
| **E4 live path** | one rehearsal dispatch (isolated HOME, real proxy, real local model) | ledger row carries `est_wh > 0`, `energy_model = energy-v1-20260909`, `latency_s > 0`; harvest block renders |
| **E5 render invariants** | harvest output of the live ledger | literal `energy (estimated · energy-v1-20260909)`; Wh value at 2 significant figures |
| **E6 dashboard** | template + summary payload | energy panel ids present; `est.` labeling; zero `setInterval`/`setTimeout` in template |

## Pre-declared dispositions

- E1 14b FAIL (> 0.50): measurement misalignment — full re-measure required, feature stays landed but harvest block ships hidden? No: block stays (invariants hold), coefficient flagged in-code.
- E1 14b in (0.35, 0.50]: **quiet-machine cell re-measure authorized** (the #168 harness, 14b decode cell only, herd idle) — recorded as a cell re-measure per #168's pre-declared exception, not partial re-scoring; the table updates only if the re-measured value lands in [0.10, 0.35].
- E2 FAIL: table error — regenerate table, no display change ships until monotone.
- E3/E4 FAIL: implementation bug — fix then **full re-run** of all gates.
- E5/E6 FAIL: invariant breach — fix then full re-run.
- `uv run pytest -q` must remain green throughout.
