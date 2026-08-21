# Kultivait — State Analysis & Backlog (2026-08-21)

> **This file supersedes and consolidates `TODO.md`, `TODO-AGY.md`, and
> `TODO-LOCAL-BS.md`.** Those three describe the *same* unbuilt evaluation
> harness in overlapping language and have drifted a month out of date. Once
> this backlog is accepted, retire them (`git rm`). This is the single
> living to-do surface.

Prioritization follows the project's own ethos (CLAUDE.md / README):
**reduce → right-size → localize**, and the product's core promise —
*prove the savings*.

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
There is **no `.github/workflows/` and no `.pre-commit-config.yaml`.** Nothing
runs `pytest` on commit or push. The single failing test
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

### P0 — Stop the bleeding (small, high-leverage)
- [ ] **B1. Fix the red test + make it robust.** Add an ANSI-strip helper for
  asserting against rich console output; fix
  `test_first_run_routes_to_screen_and_skip_writes_marker`. → suite green.
- [ ] **B2. Gate the suite.** Add a minimal `.github/workflows/ci.yml` running
  `uv sync` + `uv run pytest` on push/PR. Optionally a pre-commit hook. This is
  what prevents F1 from recurring. *(reduce: cheap, permanent.)*

### P1 — Deliver the core promise (prove savings)
- [ ] **B3. Build `experiments/run_experiment.py`** — the harness from the
  retired TODO-AGY spec: drive a prompt through the running proxy, record
  tier / duration / tokens / cost to the ledger, across local vs agy vs cloud.
- [ ] **B4. Savings report from the ledger** — extend/verify `kultivait
  harvest` to emit a cost-vs-quality summary the README can point at. This is
  the artifact that makes the whole value prop legible.

### P2 — Finish the frontier & close gaps
- [ ] **B5. Complete the magnitude-parity setup screen** per
  `docs/plans/2026-08-21-magnitude-parity-setup.md` (it's the active thread;
  the red test is a symptom of it landing unguarded).
- [ ] **B6. Anthropic `/v1/messages` tool support** (F4) — lifts the
  local-force ceiling for Anthropic-SDK clients.

### P3 — Hygiene
- [ ] **B7. Retire `TODO.md`, `TODO-AGY.md`, `TODO-LOCAL-BS.md`** in favor of
  this file; reconcile `HANDOFF.md` with the Aug-21 reality (model names,
  setup-screen flow).

---

## 4. Recommended next step
Take **B1 + B2 together** (one small session: green the suite, then gate it) —
it's the reduce-first move and unblocks confident work on everything else. From
there, **B3/B4** is the highest-value push because it's the project's own
stated reason to exist. Each item can enter the idea→ship flow at
`/grill-with-docs` when picked up.
