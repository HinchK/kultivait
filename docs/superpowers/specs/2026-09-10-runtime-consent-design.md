# Runtime consent card — design

**Date:** 2026-09-10
**Request:** `kultivait init --setup` must never start ollama on its own. When
the machine has both llama.cpp and ollama access (or ollama alone) and nothing
is serving, the screen asks which runtime to use *after* the hardware review.

## Problem

`RealDriver.prepare()` auto-starts idle ollama (`brew services start ollama`)
mid-checklist, before any consent, and its brew output lands inside the Rich
`Live` window (also a terminal-garbling suspect — see STATE.md open items).

## Design

A new **runtime phase** between preparation and chooser, decided purely in
`setup_state`:

- `needs_runtime_choice(prep, allow_downloads)` — true when nothing is serving,
  `have_ollama`, and no env-forced runtime (`KULTIVAIT_RUNTIME` counts as the
  user having already answered).
- `build_runtime_rows(prep)` — `use_llamacpp` row only when the plan is
  eligible (the garden path brew-installs llama.cpp under download consent);
  `use_ollama` row always when the card shows.
- Keys: up/down/Enter as usual; **Esc skips to the chooser having started
  nothing**; Enter on ollama locks a `use_ollama` operation; Enter on
  llama.cpp is a pure transition (the garden chooser *is* that path).
- Events: `runtime_started` (driver started ollama + re-surveyed → chooser
  with a fresh prep, mirroring `switch_done`); `op_done use_ollama` failure →
  notice, card unlocked, Enter retries.
- `RealDriver.prepare()` loses the auto-start entirely — the runtime step now
  reports `none running · ollama available` instead of acting.
- New seam `RealDriver.use_ollama(post)`: start → survey → post
  `runtime_started` (nothing to stop first: the card only appears when nothing
  is serving). Rendered as `render_runtime`, title "Choose your runtime".

## Out of scope

The llamacpp→ollama **switch** row (user-initiated pivot while serving) and
`ensure_llamacpp`'s brew install under download consent are unchanged — both
already sit behind an Enter.

## Verification

`pytest` — state machine routing/keys/events table tests; driver tests
inverted (`prepare` never calls `start_ollama`; `use_ollama` covers start,
survey, failure); render + end-to-end loop tests for the new card.
