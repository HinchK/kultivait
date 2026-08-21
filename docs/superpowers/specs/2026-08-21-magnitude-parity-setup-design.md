# Design: magnitude-parity setup screen for `kultivait init`

Date: 2026-08-21
Status: awaiting review
Reference: magnitude's onboarding model-setup flow, local clone at
`../../magnitude` (upstream: magnitudedev/magnitude). Authoritative upstream
docs: `magnitude/design/model-management/setup-flow.md`,
`magnitude/packages/client-common/src/local-models/setup-state.ts`.

## Goal

Rebuild kultivait's onboarding (`kultivait init`, plus the `install.sh`
handoff) so the experience matches magnitude's setup screen as closely as a
minimal-dependency Python CLI allows: a stateful, keyboard-driven screen with
a live Preparation checklist, a model chooser with a detail panel, download
with cancel-confirm, server start with retry, an Esc-skip path that still
completes onboarding, and a persisted completion marker with re-entry.

Non-goals (explicitly not ported — see last section): OpenTUI itself, the
daemon bootstrap screen, the pentagon radar chart, cloud API-key connect,
mouse support, light/dark probing.

## Alternatives considered

1. **Full interactive TUI on rich + stdlib raw-key input (chosen).** rich
   already renders kultivait's panels, tables, spinners, and progress bars;
   `termios` cbreak + ANSI parsing is ~100 lines of stdlib. No new
   dependency. Achieves the interaction model (j/k + Enter + Esc, live
   cards, locked list during operations).
2. **Flow parity with a linear UI.** Same phases and states, but numbered
   text prompts instead of key navigation. Easiest to test; works on pipes.
   Rejected as the primary mode — it is not "as close as possible" — but it
   survives as the non-TTY fallback, which we must keep anyway.
3. **Textual app.** The true Python analog of OpenTUI (same authors as
   rich). Rejected: heavyweight dependency for a setup screen, and
   full-app framework buy-in this tool doesn't otherwise need.

## What magnitude does (source of truth)

Phases, from `magnitude/design/model-management/setup-flow.md` and
`cli/src/features/model-setup/chooser.tsx`:

1. **Preparation** card — checklist with `○ pending / spinner running /
   ✓ done / ! failed`: Detecting hardware → Checking downloaded models →
   Assessing models → Preparing recommendations. Esc = "skip for now"
   (first run) or "close" (reopened).
2. **Chooser** card — "Choose a local model". Sections: AVAILABLE TO
   DOWNLOAD (catalog recommendations, labels like "Balanced / Fastest")
   and ON THIS COMPUTER (installed models, "Loaded"/"Load" markers). Right
   detail panel (terminal ≥ 105 cols): name, ctx, class, radar, "WHY THIS
   MODEL", memory warnings. Keys: up/down/j/k/Tab navigate, Enter selects,
   Esc exits. List locks during an operation.
3. **Download** — progress bar (█/░) with %, transfer rate, ETA; Esc opens
   a Yes/No cancel confirmation.
4. **Loading** — spinner "Loading model weights..."; on failure, error
   with "Retry loading" / "Choose another model".
5. **Closing** — "Finishing onboarding" while the completion RPC writes
   `~/.magnitude/state/onboarding.json` = `{completed: true}`.
6. Skip also completes onboarding (dismissed). Re-entry: `--setup` flag /
   `/setup` command; exit hint changes from "skip for now" to "close".

State machine (`setup-state.ts`):
`Closed | Open{ exitKind: Skip|Close, content: Preparation|Chooser|Closing }`,
with an operation (download/load) attached to Chooser and a `notice`
(failure) slot. No back-navigation; Esc and cancel are the only exits.

## User experience spec (kultivait)

ASCII mockups (final styling via rich `Panel`, rounded borders, max width
110, kultivait green accent; `○ ⠋ ✓ !` step states, `█░` bars — all rich
natives).

### Preparation card

```
╭──────────────────────────────────────────────────╮
│ Preparing your garden                            │
│ Apple Silicon · macOS arm64 · 48 GB unified      │
│                                                  │
│   ✓ Detecting hardware                           │
│   ✓ Checking for a local runtime                 │
│   ⠋ Surveying models · 3 found                   │
│   ○ Preparing recommendations                    │
│                                                  │
│ Esc skip for now                                 │
╰──────────────────────────────────────────────────╯
```

Steps map to existing code: `hardware.scan()` → runtime probe
(`_running_runtime()` + `which` checks) → `_survey_local()` (only if a
runtime answers) → `hardware.plan()`.

### Chooser card (wide layout, ≥ 105 cols)

```
╭────────────────────────────────────────────────────────────────────────────╮
│ Choose your garden                                                          │
│ Apple Silicon · 48 GB unified · llama.cpp recommended                       │
│                                                                             │
│ AVAILABLE TO DOWNLOAD                                                       │
│   › Tuned garden for this Mac    reasoning + simple + embed · 11.4 GB       │
│     Qwen3-14B alone              reasoning only · 8.4 GB                    │
│                                                                             │
│ ON THIS COMPUTER                                                            │
│     qwen3:14b                    loaded · 9.0 GB                            │
│     llama3.1:8b                  load · 4.9 GB                              │
│                                                                             │
│ ┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈ │
│ Tuned garden for this Mac                                                   │
│   Qwen3-14B-Q4_K_M (reasoning) · llama3.1-8B (simple) · nomic-embed         │
│   fits: 18.1 GB weights+KV of 36 GB GPU cap · 32k ctx                       │
│   WHY THIS GARDEN  48 GB unified memory fits the 14B reasoning pick with    │
│   headroom for the KV cache at 32k context.                                 │
│                                                                             │
│ up/down choose · Enter to set up · Esc skip for now                         │
╰────────────────────────────────────────────────────────────────────────────╯
```

- **AVAILABLE TO DOWNLOAD** rows: (a) the plan bundle — "Tuned garden for
  this Mac" (all `SetupPlan.models`: reasoning + simple + embed), first and
  preselected; (b) a reasoning-only variant (the plan's largest single
  chat model) for users who want a smaller download. Only rendered when
  `SetupPlan.eligible` and no runtime is already serving.
- **ON THIS COMPUTER** rows: surveyed models from the running runtime
  ("loaded" for the current chat base if identifiable, else "load"). If
  llamacpp is installed but not running, an extra row "Start llama-server"
  (action = `start_server`). If ollama is installed but not running, an
  advisory line (not a row): "ollama is installed — start it (`ollama
  serve`) and re-run". Selecting an installed model skips download and
  goes straight to survey → config → Closing.
- Selecting any row is the consent that today's `[Y/n]` prompts provided:
  the detail panel states exactly what will be downloaded/started before
  Enter commits (bundle contents, total GB, RAM fit). The one exception is
  `sudo`: the wired-limit bump keeps an explicit in-screen confirm card
  ("Raise the GPU memory cap now? sudo will ask for your password · Y/n")
  because sudo's password prompt is external consent.
- Narrow terminals (< 105 cols): stack list above a compressed detail
  block (3 lines: name · size · why), list viewport clamped to 4 rows.

### Download (inside the chooser card, list locked)

```
│   Downloading tuned garden · 11.4 GB                                         │
│   ████████████░░░░░░░░░░░░░░░░░░░  41% · 8.2 MB/s · about 3 min              │
│   Esc cancel                                                                 │
```

Esc → inline confirm: `Cancel the download? › Yes   No` (←/→ or h/l,
Enter). Yes → cooperative cancel (stop between files; `.part` files stay
resumable — existing behavior), back to unlocked chooser. Rate and ETA are
new metadata derived from the existing `on_progress(done, total)` seam.

### Starting card (after download, or after choosing an installed model)

```
╭──────────────────────────────────────────────────╮
│ Starting your garden                             │
│   ⠋ waiting for llama-server on :8080            │
╰──────────────────────────────────────────────────╯
```

Failure (health poll timeout / download error) replaces the spinner with
the reason plus the last lines of `~/.kultivait/llamacpp.log` (existing
`_tail`) and two actions: `r Retry · c Choose another garden`. Retry
re-runs the failed operation; Choose returns to the unlocked chooser.

### Closing + summary

```
╭──────────────────────────────────────────────────╮
│ Finishing onboarding                             │
│   ⠋ writing config · surveying tiers             │
╰──────────────────────────────────────────────────╯
```

Then the screen exits and prints the existing `render_survey()` panel
("kultivait surveyed your garden") plus today's closing lines
(`✓ wrote ~/.kultivait/config.toml` / `kultivait serve` hint). The survey
panel remains the post-setup summary — it is kultivait's brand moment and
already parity-shaped.

### Skip

Esc at Preparation or Chooser on first run = "skip for now": writes a
virtual-tier `config.toml` (existing `detect()` on an empty survey) and
the completion marker with `skipped: true`, prints the survey panel with
the cloud-CLI/virtual rows and "re-run `kultivait init` anytime to grow a
local garden". Re-runs (marker present) show "Esc close" and do not
rewrite the marker.

## Architecture

New modules under `src/kultivait/` (each one purpose, each testable in
isolation):

| Module | Purpose | Depends on |
|---|---|---|
| `setup_state.py` | Pure state machine: `SetupState` (Closed / Preparation / Chooser / Closing), `PrepStep`, `Operation` (`Downloading`, `Starting`, `ConfirmCancel` — operations attach to Chooser, as in magnitude), `Notice`; pure transition functions mirroring magnitude's lifecycle (open, advance_prep, select, lock, cancel, fail, skip, close). No I/O. | stdlib only |
| `onboarding.py` | Completion marker: `ONBOARDING_PATH = ~/.kultivait/onboarding.json`, `is_complete()`, `complete(skipped)` writing `{completed, completed_at, skipped}`. | stdlib |
| `keys.py` | `KeyReader` — termios cbreak context manager; `read()` → normalized `Key` events (UP/DOWN/ENTER/ESC/LEFT/RIGHT/CHAR/CTRL_C) incl. ANSI CSI arrows. Restore guaranteed by `finally`. Fake reader for tests. | stdlib |
| `setup_screen.py` | Renderer + driver loop. Renders each state as rich cards into a `rich.live.Live` (no alt-screen; inline cards like magnitude). Loop: non-blocking key poll (`select`, 50 ms) + worker-thread operations. | rich, above three |
| `cli.py` (modified) | `cmd_init` routes: interactive screen vs today's linear path. | all above |

Driver seam — the screen never touches the machine directly:

```python
class SetupDriver(Protocol):
    def prepare(self, emit: Callable[[PrepEvent], None]) -> Preparation  # steps + survey + plan
    def download(self, picks, on_progress, cancel: threading.Event) -> "ok | failed(reason)"
    def start_server(self, confirm: Callable[[str], bool]) -> "ok | failed(reason)"  # artifacts + wired-limit; `confirm` renders the sudo card in-screen, never auto-yes
    def brew_install(self) -> "ok | advisory(reason)"        # llama.cpp if missing
```

The default driver composes existing functions (`hardware.scan/plan`,
`_running_runtime`, `_survey_local`, `bootstrap.ensure_llamacpp/
download_models/write_artifacts/offer_wired_limit/start_server`) with
auto-yes confirms — the screen is the consent layer, so bootstrap's
`confirm=` seams are fed a lambda returning True. Operations run on a
single-thread executor (magnitude also never runs two operations at once);
progress flows back through a queue the render loop drains at ~10 Hz.

`bootstrap.py` itself needs no behavioral change: its seams
(`confirm=`, `run_cmd=`, `client=`, `on_progress=`) are already exactly
where the screen plugs in. `_offer_setup()` in `cli.py` is absorbed into
the screen's Preparation + Chooser logic and deleted.

### State machine (port of magnitude's)

```
Closed --init/first-run--> Preparation{exit_kind=Skip}
Closed --init/--setup (marker complete)--> Preparation{exit_kind=Close}
Preparation done --> Chooser{operation=None}
Preparation failed(step) --> Chooser (with notice; ON THIS COMPUTER only, if any)
Chooser + Enter(download row) --> Chooser{operation=Downloading, locked}
Chooser + Enter(installed row) --> Chooser{operation=Starting, locked}
Downloading done --> Chooser{operation=Starting}
Downloading failed/cancelled --> Chooser{notice, unlocked}
Starting ok --> Closing
Starting failed --> notice + Retry/Choose actions --r--> retry op --c--> Chooser{unlocked}
Esc anywhere (no op) --> exit_kind=Skip: Closing(writes config + marker{skipped})
                                 =Close: Closed, no writes
Esc during op --> cancel-confirm --> back to Chooser unlocked
All ops ok --> Closing --> writes config.toml + onboarding.json --> Closed
```

No back navigation (magnitude parity): Esc/cancel/retry are the only
exits.

### Entry points & fallbacks

| Entry | Behavior |
|---|---|
| `kultivait init` (TTY, no marker) | Screen, first-run semantics (Esc = skip) |
| `kultivait init` (TTY, marker complete) | Screen, re-run semantics (Esc = close); `--setup` flag is the explicit "reopen setup" analog of magnitude's `--setup` |
| `kultivait init --no-setup` | Today's non-interactive survey path, unchanged |
| non-TTY stdin | Today's linear path, unchanged (tests and pipes depend on it) |
| `KULTIVAIT_RUNTIME` set | Screen still opens if TTY (first-run vs re-run semantics per the marker, as usual), but download/brew rows are hidden — a forced runtime means a setup already exists; matches today's "offer skipped" rule |
| Ineligible machine (non-mac, < 24 GB) | Preparation shows the plan's reason as a failed recommendation step with `!`; Chooser offers only ON THIS COMPUTER / skip — same outcomes as today's printed messages, in-card |

### install.sh

Simplified to magnitude's installer shape — install the binary, then hand
off to in-app setup:

1. uv (unchanged)
2. `uv tool install` (unchanged)
3. `exec`-style final line: `kultivait init </dev/tty` — the `</dev/tty`
   fix matters: `curl | sh` leaves stdin as the pipe, which is why the
   interactive offer can never fire from the scripted install today.

The hard ollama requirement and the `ollama pull nomic-embed-text` step
are removed — runtime choice, model download, and the embed model all
belong to the setup screen now (and the zero-to-local path is llama.cpp,
not ollama, so the old script actively fought the tool's own bootstrap).

## Error handling

- Preparation step failure: step shows `!` + reason; flow continues into
  Chooser with a notice row; skip always available.
- Download failure/interrupt: notice in chooser, `.part` files resume on
  retry (existing behavior, unchanged).
- Server start failure: log tail + Retry / Choose another.
- Terminal hygiene: termios restored in `finally`; SIGINT behaves as Esc
  (cancel-confirm during downloads, skip/close elsewhere); no alt-screen,
  so scrollback is never destroyed.
- Crash safety: `config.toml` and `onboarding.json` are only written in
  Closing — a killed screen leaves nothing half-written (`.part` files
  excepted, by design).

## Testing

- `setup_state`: table-driven transition tests covering every edge in the
  diagram above (including lock-during-operation and skip-vs-close
  semantics).
- `onboarding`: marker round-trip; `is_complete()` on missing/corrupt file
  (treated as incomplete).
- `keys`: ANSI byte sequences (CSI arrows, plain chars, lone ESC, Ctrl-C)
  → events; KeyReader restores termios even when the body raises.
- `setup_screen`: FakeDriver + scripted key events + recorded rich console
  → assert phase titles, section headers, detail-panel content, hint line
  changes (skip vs close; idle vs locked), cancel-confirm flow,
  retry/choose flow, closing writes.
- Existing suites stay green: `test_cli_init`, `test_bootstrap`, `test_tui`
  exercise the unchanged linear path and bootstrap seams; the auto-yes
  confirm injection is itself covered by a screen-mode test.

## Explicitly not ported (and why)

- **OpenTUI / React** — kultivait is Python; rich Live reproduces the card
  aesthetic at a fraction of the machinery.
- **Daemon bootstrap screen** — kultivait has no daemon; `install.sh` +
  `uv tool install` are its analog and stay non-interactive.
- **Pentagon radar chart** — pretty, but kultivait's decision data
  (params, GB, RAM fit, role) is 4 scalars; the detail panel states them
  more honestly than an invented 5-axis shape.
- **Cloud API-key connect screen** — kultivait's cloud tiers are CLIs
  that own their auth; nothing to collect.
- **Mouse support / hover** — v1 is keys-only (j/k ↑/↓ Enter Esc h/l r c);
  magnitude's mouse layer has no cheap rich equivalent.
- **Light/dark theme probing** — one palette (green accent, dim support,
  red failure) that rich renders sanely everywhere.
