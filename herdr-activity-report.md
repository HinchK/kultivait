# Herdr Activity Report

## Cycle 1: Issue #9 — Route menu content & frontier target registration

- **Timestamp**: 2026-08-23T14:42:00-07:00
- **Status**: Completed & Closed
- **Orchestration Flow**:
  1. **Discovery (`agy-gh`)**: Identified open issues (#4, #9, #11, #14). Prioritization placed Issue #9 first as the core design dependency for the Wayfinder map.
  2. **Resolution (`arch` - opencode / GLM-5.3)**:
     - Followed `ask-matt` flow and wayfinder grilling discipline.
     - Resolved total-order ranking for the route menu: judge fit descending → task_type capability match → price ascending, with keep-it-local as the fourth anchor.
     - Defined fitted model and effort projection per CLI using `resolve_effort()`.
     - Bound keep-it-local to existing tier resolution with escalation-style archiving (`route_choice: "local"`).
     - Defined headless auto-policy to prioritize local serving, routing to top frontier only on `no_backend` or `tools_unsupported`.
     - Registered `codex` and `opencode` as `architect` CLI tiers in `src/kultivait/config.py` and `CLI_PRICING` with tests in `tests/test_config.py`.
     - Penned ADR `docs/adr/0003-route-menu-and-frontier-targets.md` and updated `CONTEXT.md`.
     - Verified with `uv run pytest -q` (217 tests passed).
     - Commented and closed Issue #9 on GitHub, updated Map #4.
  3. **Documentation Review (`agy-docs` - agy / Gemini 3.7 Flash)**:
     - Audited ADR 0003, `CONTEXT.md` (canonized `Route menu`, `Auto-policy`), and `docs/agents/issue-tracker.md`.
     - Conducted domain vocabulary and avoid-term scan (clean pass, 0 violations).
     - Confirmed full test suite integrity (217 passed).

---

## Cycle 2: Issue #14 — Validate verdict thresholds with a held-out eval

- **Timestamp**: 2026-08-23T14:53:00-07:00
- **Status**: Completed & Closed
- **Orchestration Flow**:
  1. **Discovery (`agy-gh`)**: Identified remaining open issues (#4, #11, #14). Prioritization placed Issue #14 first to validate empirical numbers before final spec assembly in #11.
  2. **Resolution (`arch` - opencode / GLM-5.3)**:
     - Followed `ask-matt` flow for research/eval tasks against primary sources.
     - Executed held-out evaluation across 12 test prompts (6 probe + 6 fresh held-out) against local Ollama models (`qwen3.5:4b` and `qwen3:14b`).
     - Measured key metrics:
       - Dangerous misroutes: 0/12 on both tiers.
       - Parse-failure rate: 0/12 on both tiers.
       - Latency budget: `qwen3.5:4b` met request path budget (p50 = 6.89s <= 8.0s, max = 8.94s <= 15.0s); `qwen3:14b` breached budget (p50 = 15.43s), validating the `preprocess_model` simple-tier choice.
       - Threshold sweep: verified that keeping `[0.65, 0.85)` is optimal under the decision rule (no alternative cutpoint improves agreement without excessive toll rate).
     - Produced `experiments/verdict_eval.py`, `experiments/verdict-eval-report.md`, and 24 case JSON artifacts under `experiments/verdict_eval/`.
     - Verified test suite (`uv run pytest -q` -> 217 passed).
     - Commented findings on GitHub Issue #14, closed Issue #14, and updated Map #4.
  3. **Documentation Review (`agy-docs` - agy / Gemini 3.7 Flash)**:
     - Audited all evaluation artifacts and markdown documents.
     - Confirmed vocabulary adherence against `CONTEXT.md` (0 avoid-term violations).
     - Verified test suite and cross-links.

---

## Cycle 3: Issue #11 — Assemble the preprocessor-routing spec & Map #4 Closure

- **Timestamp**: 2026-08-23T14:59:00-07:00
- **Status**: Completed & Closed (All Wayfinder Map #4 Issues Resolved)
- **Orchestration Flow**:
  1. **Discovery (`agy-gh`)**: Identified final open specification issue #11 and parent Wayfinder Map #4.
  2. **Resolution (`arch` - opencode / GLM-5.3)**:
     - Followed `ask-matt` flow transitioning to the `/to-spec` destination.
     - Assembled the full design specification at `docs/superpowers/specs/2026-08-21-preprocessor-routing-design.md` (271 lines, 10 canonical sections) matching the superpowers spec convention.
     - Consolidated all 8 closed decisions (#5, #6, #7, #8, #9, #10, #13, #14).
     - Defined module architectures and dataclasses for `preprocessor.py`, `effort.py`, and `tollbooth.py`.
     - Specified the complete ledger and harvest schema extensions (`preprocess_mark`, `verdict`, `max_fit`/`target_fits`, `canonical_effort`/`cli_effort_flags`, `toll`, `route_choice`, `subtask_candidates`, `orchestrator`/`worker`, `ts`+`fingerprint` identity pair).
     - Verified test suite (`uv run pytest -q` -> 217 passed).
     - Commented and closed GitHub Issue #11; closed parent Wayfinder Map #4.
  3. **Documentation Review (`agy-docs` - agy / Gemini 3.7 Flash)**:
     - Audited `docs/superpowers/specs/2026-08-21-preprocessor-routing-design.md`, `CONTEXT.md`, and `docs/agents/issue-tracker.md`.
     - Verified clean repo-relative ADR links and cross-references.
     - Executed full repository avoid-term sweep with 100% clean pass (0 violations).
     - Verified test suite integrity (217 passed).

---

## Cycle 4: Spec Decomposition & MVP Build Slices (P1–P4)

- **Timestamp**: 2026-08-23T15:27:00-07:00
- **Status**: Completed & MVP Delivered
- **Orchestration Flow**:
  1. **Decomposition (`arch` - opencode / GLM-5.3)**:
     - Executed `/to-tickets` from the completed preprocessor-routing spec.
     - Decomposed architecture into 7 tracer-bullet build tickets with native blocking edges:
       - **P1 (#16)**: Effort mapping core & CLI adapters (`effort.py`)
       - **P2 (#17)**: Preprocessor core (`preprocessor.py`, single-call analyze/rewrite/judge)
       - **P3 (#18)**: Ledger & harvest schema extensions (`ledger.py`, `cli.py`)
       - **P4 (#19)**: Server pipeline integration & metadata wiring (`server.py`, `backends.py`)
       - **P5 (#20)**: Per-CLI dispatch templates & command adapters
       - **P6 (#21)**: Tollbooth queue & hold mechanics
       - **P7 (#22)**: Interactive tollbooth chooser surfaces
     - Defined the **MVP Boundary** as P1–P4 (live preprocessor routing, derived verdicts, fitted effort, enriched ledger/harvest; toll holds deferred safely to P6/P7).
  2. **Worker Delegation (`agy-gh` & `agy-docs`)**:
     - `agy-gh`: Published 7 tracked GitHub issues (#16–#22) with `ready-for-agent` labels and blocking dependency links.
     - `agy-docs`: Built and tested slices P1–P4 test-first across 5 prompt rounds with review fixes.
  3. **Architect Verification & Hardening (`arch`)**:
     - Caught and corrected shell quote bug in `codex` reasoning effort flags.
     - Caught real runtime backend attribute deficiency (`AttributeError: 'OllamaBackend' object has no attribute 'local'`) during independent live curl smoke tests; patched backends directly.
     - Full test suite passed: **289 passed** (72 new tests across effort, preprocessor, ledger, and server wiring).
     - Executed live end-to-end proxy verification: simple prompts routed local; contested architecture prompts preprocessed (qwen3.5:4b), classified with 3 subtask candidates, fitted to `--effort high`, rewritten and dispatched to Claude.
  4. **MVP Readiness & Session Conclusion**:
     - The functional MVP is live, verified, and ready for human end-to-end traffic testing.
     - Future frontier build slices (#20 / P5, #21 / P6, #22 / P7) remain cleanly ticketed for subsequent agent sessions.

---
