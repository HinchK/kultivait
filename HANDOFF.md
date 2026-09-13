# HANDOFF — #216 Implement the time ledger + length rule (per #215 pin)

- **Ticket**: [#216](https://github.com/Standard-Pentest/kultivait/issues/216) (map #212/#221 cluster)
- **Branch**: `main` (3 unpushed commits beneath: 1947715 wip, d6e1ea7 #214, d60a7cb #215 CONTEXT)
- **Started**: 2026-09-13, arch seat (opencode)
- **Pin source**: #215 resolution comment (5655890600) — the authority for every choice below.

## Goal

Implement the pinned design: `first_token_ms` ledger field; frontier-latency reference
table (harvest-time yardstick, bands 0–2k/2–8k/8k+, probe-provenanced); length rule
(8192-token full-payload cap forcing frontier post-verdict); harvest time-vs-savings
section. Suite green; over-cap dispatch demonstrably routes frontier.

## Ordered tasks

- [x] 1. Claim #216, post plan comment.
- [x] 2. HANDOFF.md (this file).
- [x] 3. `time_reference.py`: versioned table module (bands, medians, overrides-never-provenance, `[time_reference]` config section).
- [x] 4. Ledger: `first_token_ms` param; `_time_section` in harvest (bands on local rows, ref medians, signed time-paid minutes, version named, "no reference" degrade).
- [x] 5. Server: first-token capture (stream + non-stream paths), length rule in `_resolve_route` (over-cap → force frontier, menu drops local anchor, `length_rule`/`length_rule_no_frontier` reasons, NO escalation archive — guarded).
- [x] 6. Config: `length_rule_max_tokens` default 8192 (TOML read + writer + cmd_serve wiring).
- [x] 7. Probe: harness + provenance committed; **values pending** — two filter-discarded runs ($1.58, kept as -discarded samples), third blocked by OpenRouter balance $0.00; table ships EMPTY with honest degrade; finish = one command after credit top-up (see experiments/latency_probe/README.md).
- [x] 8. Tests: 16 new (tests/test_time_ledger.py) — bands/overrides/version, ledger field, harvest section + invariants, force-frontier/no-escalation/tools-counted/config-override/local-only-degrade/first-token capture.
- [x] 9. `uv run pytest -q` green: 815 passed, 2 skipped.
- [x] 10. Commit `feat:`, close via agy-gh, ledger record, engrim, verdict.

## Current task

10 (close-out).

## Next action if interrupted

The only residue is the reference-table VALUES: after the human tops up
OpenRouter credits, run the README finish command and paste medians into
REFERENCE_MEDIANS (tests are hermetic — monkeypatched table — so the suite
stays green either way). Live :4114 proxy runs the installed uv tool, not
this repo — a restart from the repo is the human's call.
