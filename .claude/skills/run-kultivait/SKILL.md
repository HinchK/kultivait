---
name: run-kultivait
description: Build, run, screenshot, and drive the kultivait routing proxy locally — start the server, hit /v1/chat/completions and /v1/messages, capture the dashboard UI, run the smoke test and the test suite. Use when asked to run, start, launch, serve, test, debug, or screenshot kultivait, or to check that a change actually works in the running app.
---

# Run kultivait

kultivait is a local-first LLM routing proxy: a FastAPI server (`/v1/chat/completions`,
`/v1/messages`, `/gate`, `/harvest`, `/dashboard`) in front of a local model runtime
(ollama or llama.cpp), plus a `kultivait` CLI. Paths below are relative to the repo root.

**The app normally needs a local model runtime. The driver removes that requirement:**
it ships a fake ollama (the three endpoints kultivait actually calls) and runs a
kultivait instance against it under an isolated `HOME`. No models, no network, and
**nothing touches `~/.kultivait`** — your real config, ledger, escalations, and any
live proxy are untouched.

```bash
uv sync                                                          # once
uv run python .claude/skills/run-kultivait/driver.py smoke        # build + drive + assert
```

Expected tail (~40 s, 12 checks). Exit code 0; non-zero if any check FAILs:

```
  PASS      /v1/chat/completions (non-stream) — tier=fake-small:1b text='FAKE-OK[fake-small:1b]'
  PASS      /v1/chat/completions (stream/SSE) — 4 events, text='FAKE-OK[fake-big:14b]'
  PASS      /v1/messages (non-stream) — stop=end_turn text='FAKE-OK[fake-small:1b]'
  PASS      /v1/messages (stream/SSE) — message_start -> content_block_start -> content_block_delta ... message_stop
  PASS      tool calls round-trip (OpenAI format) — tool_calls[0].name=read
  PASS      GET /harvest — {"cache": {"dispatches": 0, ...
  PASS      GET /api/dashboard/summary — baseline_usd,by_generation,cache,counterfactuals,energy,escalations
  PASS      ledger written in sandbox HOME — 5 rows, last tier=fake-big:14b local=True
  PASS      kultivait route (CLI) — tier=fake-small:1b margin=0.024 escalated=False
  PASS      kultivait harvest (CLI) —     preprocessor marks  ok: 0, skipped: 4, timeout: 0, fail: 1
  PASS      no ASGI exceptions in serve log — clean
  PASS      dashboard UI screenshot — .../kultivait-driver-home/dashboard.png (79553 bytes)

12/12 checks passed
```

## Prerequisites

`uv` and Python 3.12+ (`.python-version` pins it; `uv sync` fetches the interpreter).
No system packages needed — the driver's fake runtime is pure stdlib. For the dashboard
screenshot only, any of: Playwright's chromium cache, Google Chrome, or a system
`chromium` (the driver finds one; see `find_chrome()`).

```bash
uv sync            # installs deps + the dev group (pytest)
uv run pytest -q   # 791 passed, 2 skipped, 1 warning in ~5 s
```

## Run: the driver (agent path)

```bash
# one-shot: start everything, assert 12 behaviours, tear down
uv run python .claude/skills/run-kultivait/driver.py smoke

# leave it running to poke by hand (prints the proxy URL and log path)
uv run python .claude/skills/run-kultivait/driver.py up
uv run python .claude/skills/run-kultivait/driver.py shot    # re-screenshot the dashboard
uv run python .claude/skills/run-kultivait/driver.py down

# flags
--keep          # smoke: leave the stack up afterwards
--home DIR      # use/reuse a specific sandbox HOME (default: $TMPDIR/kultivait-driver-home)
--real          # skip the fake; use the runtime already on this machine.
                # Do NOT use while a live kultivait or agent herd is serving.
```

The sandbox lives at `$TMPDIR/kultivait-driver-home`: `.kultivait/config.toml` (points
at the fake), `.kultivait/ledger.jsonl`, `serve.log`, `dashboard.png`, `driver-state.json`.
Delete the directory for a clean run; `down` kills the processes.

Once `up`, drive it with plain curl — the proxy is OpenAI- and Anthropic-compatible:

```bash
curl -s localhost:<proxy>/v1/chat/completions -H 'content-type: application/json' \
  -d '{"model":"auto","messages":[{"role":"user","content":"rename this variable"}]}'
curl -s localhost:<proxy>/harvest
open http://localhost:<proxy>/dashboard/     # the live harvest UI
```

## Direct invocation (no server)

Config detection, routing, ledger, escalations, and gates are pure functions — most
changes can be exercised without starting anything:

```bash
uv run python -c "
import numpy as np
from kultivait.config import detect
from kultivait.router import Router
cfg = detect(['llama3.1:8b','qwen3:14b'], ['claude'],
             sizes={'llama3.1:8b':4_700_000_000,'qwen3:14b':9_000_000_000})
print([(t.name,t.role,t.kind) for t in cfg.tiers])
r = Router(centroids={'a':np.array([1.,0.]),'b':np.array([0.,1.])}, capability_order=['a','b'])
print(r.classify(np.array([0.9,0.1])))"
# [('llama3.1:8b','simple','ollama'), ('qwen3:14b','reasoning','ollama'),
#  ('frontier:docs','docs','virtual'), ('claude','architect','cli')]
# Decision(tier='a', margin=0.883..., escalated=False)
```

## Run: human path

Needs a real runtime (`ollama serve`, or `llama-server` on :8080) and writes to the
real `~/.kultivait`:

```bash
uv run kultivait serve            # :4114 by default
uv run kultivait route "some prompt"   # dry-run a classification, no request sent
uv run kultivait harvest               # cumulative savings from the ledger
uv run kultivait run --port 9999 -- env | grep -E '^(ANTHROPIC|OPENAI)_'
# ANTHROPIC_API_KEY=kultivait
# ANTHROPIC_BASE_URL=http://127.0.0.1:9999
# OPENAI_API_KEY=kultivait
# OPENAI_BASE_URL=http://127.0.0.1:9999/v1
```

## Gotchas

- **A one-tier config crashes the router.** `Router.classify` indexes `ranked[-2]`
  unconditionally (`src/kultivait/router.py:33`), so a hand-written `config.toml` with a
  single tier raises `IndexError`. Normal configs are saved by `detect()` emitting
  virtual frontier tiers. The driver's config always defines two tiers.
- **The preprocessor ignores your config and always posts to `http://localhost:11434`**
  (`server.py:96-99`; `cmd_serve` passes no `preprocess_generate`, `cli.py:632`). On a
  machine with no ollama, every *contested* prompt raises `ConnectError`, and
  `run_preprocessor` catches only `TimeoutError`, so it escapes as an ASGI 500 (issue
  #211). The driver's fake therefore **also binds 11434** when that port is free. If it's
  taken, the smoke reports the contested-prompt checks as `KNOWN-BUG` rather than FAIL.
- **Screenshotting the dashboard needs `--timeout`, not `--virtual-time-budget`.** The
  page holds an open SSE connection to `/api/stream`, so the browser never reaches a
  quiet network and hangs forever. `--timeout=8000` returns a rendered PNG.
- **Tools on `/v1/messages` are forwarded untranslated to local runtimes.** Anthropic
  `input_schema` tools reach ollama/llama.cpp unconverted (`backends.py:138,250`); real
  llama.cpp answers `500 Failed to parse tools: Missing tool type`. The driver's
  tool check therefore uses OpenAI-format tools on `/v1/chat/completions`. See
  `docs/research/2026-09-11-claude-socket-loopback.md`.
- **`kultivait serve` has no `--config` flag** (only `cutover` does). Isolating a test
  instance means overriding `HOME`, which is what the driver does.
- **Homebrew's `chromium` on macOS may be a broken shim** pointing at a
  `/Applications/Chromium.app` that isn't installed. The driver prefers Playwright's
  `chrome-headless-shell` and falls back to real Chrome.
- **The fake's replies never parse as a preprocessor verdict**, so `kultivait harvest`
  shows `preprocessor marks … fail: 1`. That's the designed fallback-to-router path, not
  a broken sandbox.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `kultivait serve did not answer on /harvest` (driver prints the last 2 KB of `serve.log`) | Usually a bad sandbox config or a port already bound. `rm -rf $TMPDIR/kultivait-driver-home` and re-run. |
| `500` on a tools request + `preprocessor.py` + `ConnectError` in `serve.log` | Issue #211; port 11434 was busy so the shim couldn't bind. Stop whatever holds 11434, or accept the `KNOWN-BUG` line. |
| Screenshot command never returns | You used `--virtual-time-budget`; use `--timeout=8000` (see Gotchas). |
| `no headless chrome found` | Install Chrome, or `npx playwright install chromium`. |
| Stale processes after a crash | `driver.py down --home <dir>`; it SIGTERMs the pids in `driver-state.json`. |
