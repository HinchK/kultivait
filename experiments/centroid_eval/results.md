# Recalibration safety eval — results

Protocol: `protocol.md` (bars pre-registered 2026-09-09, commit `6a5090b`, before the run).
Harness: `run_eval.py` — real harvest (live ledger + escalations), real nomic-embed-text
embedder, candidate `learned-v1` vs `seeds-v0`, evaluated **role-level** on the
`routing_trust` 24-prompt held-out set under identical rules for both routers.

## Verdict: R2 FAIL — candidate recorded, NOT cut over (pre-declared protective outcome)

| Gate | Bar | Result | |
|---|---|---|---|
| R1 dangerous misroutes | exactly 0 | **0** (all candidate errors are cloud-ward) | PASS |
| R2 accuracy floor | ≥ live seed baseline | candidate **21** vs baseline **22** | **FAIL** |
| R3 toll-band delta | ≤ 10 pp | 12.5% vs 8.3% (Δ 4.2 pp) | PASS |
| R4 live shadow mechanism | row logged, kind=centroid, no raise | 1 row verified on a real vector | PASS |
| R5 provenance sanity | versions + non-negative counts | seeds-v0 + learned-v1 clean | PASS |

## What actually happened (honest analysis)

- **Candidate provenance**: only `architect` cleared the 10-signal minimum (17 escalation
  anchors + 7 silver); simple/reasoning/docs retained seed priors. The candidate is
  effectively "seed router + escalation-anchored architect centroid".
- **The R2 flip**: the seed baseline misroutes 2 simple prompts one step up (escalation
  margin → reasoning). The candidate's anchor-heavy architect centroid pulls those *same*
  prompts — plus one more — all the way to architect. 3 wrong vs 2 wrong: **21 vs 22**.
  Every candidate error is *wasteful-direction* (over-provisioning); **zero are dangerous**
  (R1 holds with margin). This is the prior + cloud anchors drifting cloud-ward — the safe
  direction — and exactly the trade the accuracy floor exists to catch.
- **Baseline note**: the live seed baseline scores 22/24 (not routing_trust's headline 24/24)
  because this harness classifies role-level *through* the production Router's escalation
  margin (thin margin ⇒ one tier up), which routing_trust's raw-centroid methodology does not
  apply. Both routers were measured under identical rules; the bar was pre-registered against
  the live-measured baseline.

## Disposition (per protocol, executed)

- **No cutover.** `learned-v1` stays a table entry; the active seat remains seeds.
- **#181 (dogfood) proceeds shadow-only**: the candidate shadows real traffic; the agreement
  volume and disagreement cases feed the next learn iteration (more silver signals will
  accumulate under the 512-char cap).
- The eval itself succeeded: bars were pre-registered, measured honestly, and the protective
  gate held. The FAIL belongs to the candidate, not the process.

Reproduce: `uv run python experiments/centroid_eval/run_eval.py` (raw per-prompt
classifications in `classifications.csv`; candidate table in `eval_centroids.json`).
Suite at results time: `uv run pytest -q` → **762 passed, 2 skipped**.
