# Ambient gates via agent-framework hooks — design

Date: 2026-09-08
Branch: main (wayfinder map #156)
Status: approved via wayfinder map #156 (issues #157–#161); research register: `docs/research/2026-09-04-claude-hooks-api.md`

## Problem

`kultivait prune` and `POST /gate` distill a transcript into a handoff brief only when invoked by
hand. Real agent sessions cross phase boundaries constantly — a subagent finishes, context pressure
triggers compaction — and nobody stops to run a manual gate. The README roadmap promises pruning at
phase boundaries without manual invocation. Agent frameworks now expose hook events rich enough to
fire the gate for us: Claude Code sends every hook the session `transcript_path`, gives
`SubagentStop` the subagent's own `agent_transcript_path` + `last_assistant_message` inline, and
lets `SessionStart` inject context ahead of the first prompt (verified facts, register §A/B).

## Decisions (locked at the grill, map #156)

1. **Framework-agnostic core**: `kultivait gates fire` reads one JSON payload on stdin and does all
   the work; the Claude Code adapter is a thin settings.json wrapper. Contract: *event name + JSON
   payload in → side effects + optional context JSON out*; event vocabulary stays at the
   intersection of hosts (tool-pre, tool-post, turn-end, session-start, compact-pre — register §c);
   anything host-specific (matchers, `hookSpecificOutput` envelope, transcript path fields) lives
   behind the adapter.
2. **Firing events**: `SubagentStop` and `PreCompact` fire the distill. `Stop` is excluded by
   default (per-turn briefs would spam the compost). `SessionStart` is the injection point.
3. **Hybrid brief delivery**: the briefs directory is the source of truth; SessionStart injects the
   latest brief where the framework supports it; a one-line instruction in the project's
   `CLAUDE.md` names the directory as the fallback channel.
4. **CLI-direct transport**: hooks invoke the `kultivait` binary directly. Ambient hygiene must not
   depend on proxy liveness; the `prune` standalone path (local model via the runtime) is the
   engine.
5. **Command family**: `kultivait gates …` — "hook" remains adoption-only vocabulary (glossary).
6. **Scope**: install/uninstall surface, herd dogfooding (#161), pre-registered eval (#160) all
   in-map.

## Architecture

### `kultivait gates fire` — the core

stdin: the host's hook payload verbatim (Claude Code's common-fields JSON), plus our envelope
recognizing `hook_event_name` and the kultivait-relevant fields:

```json
{
  "hook_event_name": "SubagentStop",
  "session_id": "…", "cwd": "…",
  "transcript_path": "…", "agent_transcript_path": "…",
  "last_assistant_message": "…", "agent_type": "…",
  "trigger": "manual|auto"
}
```

Behavior, in order:

1. **Resolve project identity** — from `cwd` (Claude Code runs handlers in the project dir; exec
   form uses `$CLAUDE_PROJECT_DIR` in the installed command). Project key: basename slug + first 8
   hex of the absolute path (stable across sessions, collision-safe).
2. **Resolve phases** — look up `.kultivait/gates.toml` walking up from `cwd`; match on event +
   context (`agent_type` for SubagentStop, `trigger` for PreCompact); unmapped → `previous → next`.
3. **Select the transcript source** — SubagentStop: `agent_transcript_path` (the subagent's own
   transcript; register B1), falling back to `last_assistant_message` alone if the file is
   unreadable. PreCompact: `transcript_path` (the full pre-compaction main history; async-write lag
   is low here since the whole conversation precedes the event — register B1). Transcript payloads
   are Claude-Code JSONL; the core extracts the text turns (role + content) and ignores the event
   envelope lines.
4. **Compost synchronously** — write the extracted transcript to `~/.kultivait/compost/` (existing
   invariant) *before* any model call. This is the durability boundary: an async hook killed at
   teardown loses at most the brief, never the source (register B3: `claude -p` kills async hooks).
5. **Distill** — reuse `Gate.distill` (local model, same template as `prune`); write the handoff
   brief to the briefs lane (below); update `latest.json`.
6. **Emit** — exit 0 with no stdout for firing events (async hooks' stdout is discarded anyway;
   register B3). Never emit `decision`, never exit 2. **The never-block safety rule**: a gate may
   not block, fail, or stall the host under any code path — blocking PreCompact on recovery
   compaction *fails the request* (register, open ambiguity 2) and blocking SubagentStop loops the
   subagent against its 8-block circuit breaker.
7. **SessionStart branch** — sync, milliseconds: read `latest.json` for the resolved project, print
   the latest brief as a fenced block with provenance header (below) via plain stdout (SessionStart
   promotes stdout to context; register A4) — no distillation happens on this path. No briefs →
   exit 0 silently.

Failure posture everywhere: any internal error → exit 0 silently (fail-open; matches the host's own
treatment — register A4: a mistyped path leaves hooks silently disabled). Errors log to
`~/.kultivait/gates.log` for debugging.

### Briefs lane (source of truth)

`~/.kultivait/briefs/<project-slug>-<path8>/`:

- `NNN-<from>_to_<to>-<yyyymmdd-hhmmss>.md` — the brief, prefixed by a provenance header:
  `> kultivait ambient gate · <from> → <to> · <iso-timestamp> · <tokens_before>→<tokens_after> tok · source: <event>`.
- `latest.json` — `{"path": …, "from": …, "to": …, "timestamp": …, "tokens_before": …, "tokens_after": …}`.
- Rotation: keep the most recent 20 briefs per project; older briefs are deleted (they are derived
  artifacts; the compost pile retains every source transcript, so nothing is lost that cannot be
  regenerated). No staleness TTL: the provenance header makes recency legible; the consuming agent
  judges.

Briefs are typically 1–2k chars — comfortably inside the host's 10,000-char context cap (register
A4); on overflow the host spills to file + preview, which degrades gracefully to the fallback
channel.

### Claude Code adapter (installed config)

`gates install --claude` writes into project `.claude/settings.json` (committed; shareable) a
hooks block shaped (register A5):

```json
{"hooks": {
  "SubagentStop": [{"hooks": [{"type": "command", "command": "kultivait gates fire", "async": true, "timeout": 300}]}],
  "PreCompact":  [{"hooks": [{"type": "command", "command": "kultivait gates fire", "async": true, "timeout": 300}]}],
  "SessionStart": [{"matcher": "startup|resume|clear|compact|fork", "hooks": [{"type": "command", "command": "kultivait gates fire", "timeout": 10}]}]
}}
```

- All-source SessionStart matcher is the canonical re-inject-after-compaction pattern (register B2).
- Distill hooks `async: true`: the brief is consumed at the *next* SessionStart, so background
  execution costs nothing and stalls nothing (register B3); `timeout` is not enforced while
  backgrounded but bounds pathological hangs.
- `--dry-run` prints the exact JSON diff; `gates uninstall --claude` removes precisely our entries
  (matched by the `kultivait gates fire` command string — settings JSON admits no marker comments);
  user-level kill switch `disableAllHooks` documented in `--help`.
- Install also scaffolds `.kultivait/gates.toml` if absent (default: empty mapping →
  `previous → next` for both firing events) and prints the one-line `CLAUDE.md` fallback
  instruction for the human to paste:
  `Phase context lives in ~/.kultivait/briefs/ — read the latest brief before starting a new phase.`
- Security note (register A5): settings-file hooks in a cloned repo run under `-p`/SDK trust. Our
  command only reads local transcripts and writes local files; on machines without kultivait
  installed the hook fails to start = non-blocking = silently disabled (fail-open, safe).

### `gates` CLI surface

```
kultivait gates fire                     # the core (stdin JSON, auto-detects event)
kultivait gates install --claude [--dry-run]
kultivait gates uninstall --claude
kultivait gates briefs [--project DIR]   # list briefs + latest manifest (dogfood visibility)
```

## Eval handoff (bars pre-registered in #160, not here)

Measured: (1) planted-fact recall over gate outputs (transcripts seeded with known constraints /
paths / decisions; fraction retained in brief), (2) tokens-kept ratio, (3) compost-before-distill
guarantee (kill -9 mid-distill; transcript survives), (4) SessionStart injection latency, (5)
async no-stall (host-observable stall while a SubagentStop gate fires). Numeric pass/fail bars are
written down in #160 **before** the run; FAIL branches reported honestly and dispositioned.

## Out of scope

Native adapters beyond Claude Code (opencode's plugin surface — register §c — informs the contract
but gets no adapter in v1); Stop-event gating; proxy-transport gating; shaping compaction
instructions (impossible via Claude Code hooks — `custom_instructions` is input-only, register,
open ambiguity 1); a versioned release entry.

## Glossary terms crystallized

*Ambient gate*, *Handoff brief*, *Phase map* — added to `CONTEXT.md` with this spec.
