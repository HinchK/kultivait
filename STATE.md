# Looper State Checkpoint

## Long-Term Epic Direction (CTO / Orchestrator Internal)
1. **Epic 1 (Current Active)**: Ambient gates via agent-framework hooks (e.g., Claude Code hooks) for phase-boundary pruning without manual invocation.
2. **Epic 2**: Watt-hour / energy estimation in the ledger and harvest.
3. **Epic 3**: Learned centroids from routing history.
4. **Epic 4**: Distillation-quality eval harness (planted-fact recall scoring across transcripts).

*Note: The herd is fed strictly one epic at a time.*

## Active Milestone
- **Target Goal**: Ambient gates via agent-framework hooks
- **Status**: Chartering kickoff dispatched to `arch`

## Session Notes (2026-09-10)

**Landed — runtime consent card** (spec: `docs/superpowers/specs/2026-09-10-runtime-consent-design.md`):
`init --setup` no longer auto-starts idle ollama from the preparation
checklist. New `runtime` phase in `setup_state` (nothing serving + ollama
installed + no `KULTIVAIT_RUNTIME` force) shows a "Choose your runtime" card;
`RealDriver.use_ollama` is the consented start (start → survey →
`runtime_started`). Full suite green (786 passed).

**Open — terminal garbling during model download** (`init --setup`): user
reports the screen garbles as soon as a download starts (screenshots in the
2026-09-10 session). PTY feedback-loop harness built and parked at
`/tmp/kultivait-garble/repro.py` (drives `run_setup` under a pseudo-terminal,
simulates VT100, flags stacked-frames garble; variants: pure / external
brew-style writer / resize). Suspects: uncaptured subprocess output hitting
the tty inside the Rich `Live` window — note the removed auto-start ran
`brew services` exactly there, and `ensure_llamacpp` still runs `brew install`
uncaptured inside `download()` when `llama-server` is missing from PATH.
Next: run the harness's three variants; then check `ensure_llamacpp`'s
`run_cmd` capture and `Live` vs frame-height behavior.
