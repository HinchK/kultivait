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

**Landed — provider-error hardening (2026-09-10, same session)**: opencode
stream through kultivait crashed with an ASGI traceback when llama-server
answered 400 (prompt 20.3K tokens > running server's `-c 16384` ctx —
llama-server log names it exactly). Root causes fixed, tests-first
(`test_server.py` provider-error block, `test_backends.py` enrichment test;
791 passing):

1. `_dispatch_stream` primed its generators (generator laziness meant the
   fallback try/except never executed backend code). Ordinary routes stay
   single-tier by design; tollbooth human picks keep unbounded failover —
   now functional.
2. Both dialect endpoints' SSE generators catch and render in-band errors
   (`[DONE]`-terminated) instead of escaping into ASGI; non-stream twins
   return shaped 502s (`provider_error` / Anthropic `api_error`).
3. `_classify_or_degrade`: embed failures (oversized last message) degrade
   to a local fat-margin Decision instead of a raw 500.
4. `LlamaCppBackend.stream` reads the 400 body inside the stream context
   and raises `RuntimeError("llama-server 400: <provider message>")` —
   httpx `ResponseNotRead` makes the body unreachable anywhere else.

**Follow-ups (not bugs fixed here):**
- Environment: `config.toml` says `num_ctx = 32768` but the managed
  llama-server runs `-c 16384` (PID-level flags) — the crashed request
  would have fit 32K. Regenerate/restart the server or re-run init.
- Overflow-aware routing: pre-flight token count vs tier ctx (route or
  toll) — currently the clean in-band error is the contract.
- Anthropic-dialect SSE loop is dispatch-guarded only; mid-stream backend
  death there still truncates (chat dialect guards the full loop).
- The uv-tool-installed kultivait (0.2.0) predates this fix — reinstall
  the tool from the repo to pick it up.
