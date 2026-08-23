# Kultivait — State Analysis & Backlog (2026-08-21, rev. 2)

> **This file supersedes and consolidates `TODO.md`, `TODO-AGY.md`, and
> `TODO-LOCAL-BS.md`.** Those three describe the *same* unbuilt evaluation
> harness in overlapping language and have drifted a month out of date. Once
> this backlog is accepted, retire them (`git rm`). This is the single
> living to-do surface.

Prioritization follows the project's own ethos (CLAUDE.md / README):
**reduce → right-size → localize**, and the product's core promise —
*prove the savings*.

---

## 0. Changed since first pass (same day, post-preprocessor-probe)

Rev. 1 was written at `9d3a959`. HEAD is now `55ef53d` (the preprocessor
probe). Verified deltas:

- **Suite is now 213 passed / 1 failed** (was 189/1). The original red test
  (`test_cli_init::…skip_writes_marker`) is **fixed** — verified by name
  (`tests/test_cli_init.py` → 7 passed). F1's *specific* failure is closed;
  F1's *root cause* (ungated suite) is not.
- **A different test is now red:**
  `test_setup_screen.py::test_real_driver_start_server_resolves_wired_answer`
  (`KeyError: 'wired'`). Diagnosed: not a product regression — the wired-limit
  confirm was **extracted out of the driver's `start_server` into the state
  machine** as a distinct `confirm_wired` operation (`setup_state.py:288-292,
  339-340`), so the test's `offer_wired_limit` mock never fires. Stale test
  from the pivot refactor; a one-file fix. **Proof, again, that the suite is
  ungated** — a second unguarded landing put it red.
- **NEW F5 — unit tests make live network calls to PostHog.** Every `pytest`
  run emits `urllib3` connection-pool warnings to `us.i.posthog.com`. This
  violates the CLAUDE.md convention ("network/subprocess pushed to the edges
  and mocked or skipped in tests") and it **changes B2's cost**: a CI runner
  would be slow, flaky, and would fire telemetry from every PR. Telemetry must
  be gated behind an env check in tests *before* the suite is gated in CI.
- **NEW F6 — a whole design frontier landed that Rev. 1 missed.** `CONTEXT.md`
  + `docs/adr/0001-trolltoll-holds-requests.md` + the HEAD prototype introduce
  two unbuilt mechanisms: **trolltoll/tollbooth** (hold the HTTP request open
  up to 60s while a human picks the route) and the **preprocessor** (a gated
  local analyze/rewrite/judge pass before routing). This is the real active
  frontier now — bigger than "finish the setup screen."
- **End-to-end works (Rev. 1 was unit-only).** `kultivait route` classifies
  correctly (qwen3:14b, margin 0.20, no escalation); `kultivait harvest`
  reports real ledger data — **37 prompts, 100% local, $1.09 kept, 16
  cloud-worthy served locally.** So the *savings-tally* half of "prove the
  savings" is already live and legible; what's missing (F2/B3) is the
  *comparative quality* half — proof the local answer was good enough.
- **Preprocessor probe gaps (from its own artifacts):**
  - `summary.md` reports only the 14b row (10.38s). The **4b latency —
    5.83s, 6/6 parse-ok — is the number that decides request-path viability**
    and it's missing from the summary.
  - Artifacts write to `experiments/preprocessor_probe/artifacts/artifacts/`
    (doubled segment) — a path bug in the probe script.
  - **The unanswered decision:** preprocessor latency **+** trolltoll hold
    **+** frontier dispatch must fit inside *one* client HTTP-timeout budget.
    ADR 0001 pins the hold at 60s "under typical client timeouts"; nobody has
    added up the three terms. This is a decision for `/grill-with-docs`, not a
    ticket for a queue.

---

## 1. Current state

- **Size:** ~3,230 LOC across 18 source modules; 19 test files, **189
  passing / 1 failing** (`uv run pytest`, no network needed).
- **In flight:** a ~9-commit thread (Aug 21) building the *magnitude-parity
  setup screen* — `setup_screen.py`, `setup_state.py`, `tui.py`, rich card
  renderers, a raw-key reader, and a committed 569-line implementation plan
  (`docs/plans/2026-08-21-magnitude-parity-setup.md`). This is the active
  frontier of work.
- **Architecture is sound and matches CLAUDE.md:** pure-function core
  (`config.detect`, `router.classify`, `ledger`, `escalations`) with
  network/subprocess pushed to the edges (`cli.py`, `backends.py`) and
  mocked in tests. Clean seams.
- **Positive worth noting:** a `TODO/FIXME/XXX/HACK` sweep over `src/` came
  back essentially empty (2 false positives, both descriptive comments). The
  *code* carries almost no inline debt — the debt lives in the **docs** and a
  **missing test gate**.

### Verification scope of this analysis
Ran the full unit suite (189/1). **Did not** smoke-test anything requiring a
live `ollama` / `llama-server`: `serve`, `route`, `init` (real download),
`prune`, `escalations --brief`. Health claims below are unit-level only.

---

## 2. Findings (root causes, not symptoms)

### F1 — The suite is ungated; it has been red since Aug 21
> **Rev. 2 correction:** this finding was **wrong about the gate**.
> `.github/workflows/ci.yml` *does* exist (committed `91d4b85`) and runs
> `uv sync` + `pytest` on push/PR to `main`. The real defect was a
> **non-hermetic test** that is red only on a machine with a live ollama and
> green on a clean CI runner — so the gate ran green while the dev's machine
> showed red. Fixed in B1. There is still **no `.pre-commit-config.yaml`**
> (optional). The paragraph below is preserved for the record but superseded.

~~There is **no `.github/workflows/` and no `.pre-commit-config.yaml`.** Nothing
runs `pytest` on commit or push.~~ The single failing test
(`test_cli_init.py::test_first_run_routes_to_screen_and_skip_writes_marker`)
went red at commit `d8db653` (init routed through the setup screen) and no gate
caught it. "One broken test" is really "**the suite is ungated**."

*Root cause of the failure itself:* `cli.py:324` prints
`"re-run [bold]kultivait init[/bold] anytime …"` via rich; rich renders
`[bold]` as `\x1b[1m…\x1b[0m` around "kultivait init", so the test's plain
substring `"re-run kultivait init anytime"` spans the markup boundary and no
longer matches. Because `tui.console = Console()` doesn't force color, this is
a *fragile-assertion* class: **any** substring assertion against rich-rendered
init output is at risk. Fix is a seam (an ANSI-strip / plain-render test
helper), not a one-string patch.

### F2 — The project's own #1 priority is unbuilt
All three retired TODO files describe one thing: an **evaluation harness to
prove worth** across the local / agy / cloud tiers. It does not exist —
`experiments/run_experiment.py` is specced in detail in `TODO-AGY.md` and was
never written; only `experiments/distill_eval/` (fact-recall scoring) exists.
A month of effort went into the setup screen while the thing that
substantiates the README's headline claim ("watch the savings grow") sits
undone.

### F3 — Doc/reality drift (specific)
- `TODO-AGY.md` names the agy worker as **Gemini 3.5 Flash**; the live
  `~/.gemini/antigravity-cli/settings.json` defaults to **Gemini 3.7 Flash
  (High)**.
- `experiments/run_experiment.py` is specced but absent.
- `TODO*.md` / `HANDOFF.md` are dated Jul 14–17; the setup-screen thread is
  Aug 21 — over a month of drift.

### F4 — Known feature gap
`/v1/messages` (Anthropic-compatible) has no tool support (per CLAUDE.md);
tools-bearing requests are always force-served by a local tool-capable tier.
Documented and intentional, but a real ceiling for Anthropic-SDK clients.

---

## 3. Backlog (prioritized)

### P0 — Stop the bleeding — DONE (rev. 2)
- [x] **B1. Fix the red test. ✅** Root cause was sharper than "stale test":
  `test_real_driver_start_server_resolves_wired_answer` was **non-hermetic** —
  it never stubbed the runtime probes, so `start_server`'s exclusivity check
  made a *real* localhost call, found the dev machine's live ollama up, and
  early-returned before `offer_wired_limit` (→ `KeyError: 'wired'`). Red only
  when ollama is running; green on a clean CI runner. Fixed by calling the
  sibling helper `_exclusive_env(monkeypatch, [])` (tests/test_setup_screen.py).
  Now deterministic everywhere.
- [x] **B1.5. Gate telemetry in tests (F5). ✅** Added `tests/conftest.py`
  (session-scoped autouse fixture) that strips `POSTHOG_PROJECT_TOKEN` /
  `POSTHOG_HOST` after collection, so `build_app` builds no client and the suite
  makes zero outbound calls. **Side effect: local suite went 21.3s → 0.3s** —
  telemetry was ~99% of runtime. (`.env` is gitignored and CI carries no token,
  so this was a local-only leak; the fix is still correct defense-in-depth.)
- [x] **B2. Gate the suite. ✅ (already existed)** F1 was **wrong** —
  `.github/workflows/ci.yml` was committed at `91d4b85` (uv sync + pytest on
  push/PR to main). It never caught B1 because the test was non-hermetic (green
  on a runner with no ollama). B1's fix is what makes the existing gate
  *meaningful*: CI-green now genuinely implies suite-green. **Suite: 214/214.**

### P1 — Deliver the core promise (prove savings)
- [ ] **B3. Build `experiments/run_experiment.py`** — the harness from the
  retired TODO-AGY spec: drive a prompt through the running proxy, record
  tier / duration / tokens / cost to the ledger, across local vs agy vs cloud.
- [ ] **B4. Savings report from the ledger** — extend/verify `kultivait
  harvest` to emit a cost-vs-quality summary the README can point at. This is
  the artifact that makes the whole value prop legible.

### P1.5 — The trolltoll/preprocessor frontier (NEW, F6) — decide before building
- [ ] **B4a. Compute the latency budget** (decision, `/grill-with-docs`). Add
  the three terms — preprocessor pass (4b: 5.83s; 14b: 10.38s) + trolltoll hold
  (≤60s) + frontier dispatch — and confirm they fit one client HTTP timeout.
  This gates everything else in the frontier. Cheapest first move; may kill the
  request-path preprocessor outright (→ move it off the hot path).
- [ ] **B4b. Land the probe honestly.** Add the 4b row to `summary.md`; fix the
  doubled `artifacts/artifacts/` path in the probe script. *(hygiene on the
  primary source that the frontier decision rests on.)*
- [ ] **B4c. Trolltoll/tollbooth implementation** — only after B4a says the
  hold shape is viable. Pending-tolls queue, two faces (serve TTY + `kultivait
  choose`), timeout drain to auto-policy, late answers as ledger
  counterfactuals (per ADR 0001's Consequences).

### P2 — Finish the frontier & close gaps
- [ ] **B5. Complete the magnitude-parity setup screen** per
  `docs/superpowers/plans/2026-08-21-magnitude-parity-setup.md` (it's the active
  thread; both red tests were symptoms of it landing unguarded).
- [ ] **B6. Anthropic `/v1/messages` tool support** (F4) — lifts the
  local-force ceiling for Anthropic-SDK clients.

### P3 — Hygiene
- [ ] **B7. Retire `TODO.md`, `TODO-AGY.md`, `TODO-LOCAL-BS.md`** in favor of
  this file; reconcile `HANDOFF.md` with the Aug-21 reality (model names,
  setup-screen flow).

---

## 4. Recommended next step (rev. 2)
Take **B1 → B1.5 → B2 in one small session** (green the red test, no-op
telemetry under pytest, then gate in CI). That's the reduce-first move and it
unblocks confident work on everything else — and B1.5 must precede B2 or the
gate is built on a network-flaky suite.

Then the fork:
- If the goal is **"prove the savings" (the stated reason to exist)** →
  **B3/B4**. Note the savings *tally* is already live ($1.09 kept in the
  ledger); the gap is the *quality-parity* harness.
- If the goal is **the new frontier** → **B4a first** (the latency-budget
  decision). Do not build B4c (trolltoll) until B4a says the hold fits a client
  timeout.

Each substantive item enters the idea→ship flow at `/grill-with-docs` when
picked up; **B4a specifically is a `/grill-with-docs` decision, not an
`/implement` ticket.**
