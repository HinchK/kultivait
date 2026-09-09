# Claude Code hooks API — ground truth for the ambient-gates design

Research ticket: [#157](https://github.com/Standard-Pentest/kultivait/issues/157) · parent map: [#156](https://github.com/Standard-Pentest/kultivait/issues/156)
Date opened: 2026-09-04 · **All sources retrieved 2026-09-08** · Branch: `research/claude-hooks-api`
Method: full read of the official hooks reference and hooks guide at `code.claude.com/docs/en/hooks` and `/hooks-guide` (Anthropic's current canonical location; `docs.anthropic.com` Claude Code pages redirect there), the `anthropics/claude-code` CHANGELOG.md (raw, GitHub `main`), and `opencode.ai/docs/plugins`. Every fact below carries a register label: **VERIFIED** (prose in an official doc, URL cited), **INFERRED** (from doc examples/tables/diagram alt-text), or **UNVERIFIED** (docs silent; flagged, not guessed).

Scope note: this is the API as of Claude Code v2.1.25x-era docs (Sep 2026). The surface has tripled since the 2025 "classic hooks" era; the classic 9 events are stable, the rest are v2.x additions with pinned intro versions below.

---

## (a) VERIFIED-FACTS REGISTER — event × payload × control × timing

### A1. Hook-event list (33 events) and stability

VERIFIED — https://code.claude.com/docs/en/hooks (Hook events section + lifecycle table; identical table at /docs/en/hooks-guide#how-hooks-work), retrieved 2026-09-08.

| Stability class | Events | Evidence |
|---|---|---|
| **Classic core (stable since v1.x, 2025)** | `PreToolUse`, `PostToolUse`, `UserPromptSubmit`, `Notification`, `Stop`, `SubagentStop`, `PreCompact`, `SessionStart`, `SessionEnd` | INFERRED — changelog (retrieved 2026-09-08, raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md) reaches back to 0.2.21 and shows these only in fixes/enhancements, never as additions |
| **v2.x additions (intro version VERIFIED from changelog)** | `SubagentStart` (2.0.43) · `TeammateIdle`, `TaskCompleted` (2.1.33) · `ConfigChange` (2.1.49) · `WorktreeCreate`, `WorktreeRemove` (2.1.50) · `InstructionsLoaded` (2.1.69) · `Elicitation`, `ElicitationResult` (2.1.76) · `StopFailure` (2.1.78) · `CwdChanged`, `FileChanged` (2.1.83) · `TaskCreated` (2.1.84) · `MessageDisplay` (2.1.152) · `DirectoryAdded` (2.1.219) · `PreModelSwitch`, `PostModelSwitch` (2.1.251, docs also state "requires v2.1.251") | changelog entries, retrieved 2026-09-08 |
| **Current but intro version not pinned (UNVERIFIED version)** | `Setup`, `UserPromptExpansion`, `PermissionRequest`, `PermissionDenied`, `PostToolUseFailure`, `PostToolBatch` | listed in the current reference event table; no intro entry found in the searched changelog span |
| **Experimental (docs say so)** | `agent`-type hooks ("Agent hooks are experimental and may change") | VERIFIED /docs/en/hooks, Hook handler fields |

Note: `PreCompact` the *event* is classic, but its **blocking** support (exit 2 / `decision:"block"`) was added in 2.1.105 (changelog, VERIFIED). `Stop`/`SubagentStop` `last_assistant_message` input added 2.1.47; `background_tasks`/`session_crons` added 2.1.145; Stop/SubagentStop `hookSpecificOutput.additionalContext` feedback added ~2.1.x (changelog line 2200).

### A2. Common stdin JSON fields (all events)

VERIFIED — https://code.claude.com/docs/en/hooks#common-input-fields, retrieved 2026-09-08. Command hooks get JSON on stdin; HTTP hooks get the same JSON as POST body.

| Field | Presence | Notes |
|---|---|---|
| `session_id` | all events | |
| `transcript_path` | **all events** (common-field table; appears in every event's example JSON) | Path to conversation JSONL. **Written asynchronously; may lag the in-memory conversation** — may not include the current turn's latest messages when the hook fires. Docs direct hooks needing the final assistant text to `last_assistant_message` (Stop/SubagentStop) instead of parsing the transcript. |
| `cwd` | all events | working dir at hook invocation |
| `hook_event_name` | all events | |
| `permission_mode` | *not all events* ("check the JSON example in each event's section") | values incl. `default`, `plan`, `acceptEdits`, `auto`, `dontAsk`, `bypassPermissions` |
| `prompt_id` | v2.1.196+; absent until first user input | correlates with OTEL prompt id |
| `effort` | events firing in tool-use context (PreToolUse, PostToolUse, Stop, SubagentStop, …) | when model supports it |
| `agent_id`, `agent_type` | when running `--agent` or inside a subagent | identify subagent context on any event |
| `model` | **SessionStart only**, and not always | PreModelSwitch/PostModelSwitch get `from_model`/`to_model` instead |

### A3. Per-event payload, control, and timing register

Timing legend: **sync-block** = agent waits for hook; **side** = fires off the main blocking path (see C2 for the ambiguity); **async-opt** = can be made background via `async: true` (command hooks only). All facts VERIFIED from https://code.claude.com/docs/en/hooks respective event sections + Decision control + Exit-code-2-per-event tables, retrieved 2026-09-08, unless labeled otherwise.

| Event | Extra input fields (beyond common) | Output control | Exit 2 | Timing |
|---|---|---|---|---|
| `SessionStart` | `source` (`startup`/`resume`/`clear`/`compact`/`fork`), optional `model`, `agent_type`, `session_title`; on resume/fork ≥1 response (v2.1.251+): `seconds_since_last_response`, `context_tokens`, `prompt_cache_likely_expired`, `estimated_cache_write_usd` | `hookSpecificOutput.additionalContext` (context before first prompt), `initialUserMessage`, `sessionTitle`, `watchPaths`, `reloadSkills`; **plain stdout also becomes context**; no blocking. Only `command` and `mcp_tool` types supported | No — stderr to user only, session proceeds | sync-block; runs before first prompt |
| `Setup` | `trigger` (`init`/`maintenance`) | none | ignored | fires only with `--init-only` / `-p --init` / `--maintenance` |
| `InstructionsLoaded` | load-reason matcher (`session_start`, `nested_traversal`, …) | none | ignored | side |
| `UserPromptSubmit` | `prompt` | plain stdout → context; `hookSpecificOutput.additionalContext`, `sessionTitle`, `suppressOriginalPrompt`; `decision:"block"`+`reason` erases the prompt | Yes — blocks prompt, erases it | **sync-block; 30 s default timeout** (stalls session if stuck) |
| `UserPromptExpansion` | command name matcher | `decision:"block"` | Yes — blocks expansion | sync-block |
| `PreToolUse` | `tool_name`, `tool_input`, `tool_use_id` | `hookSpecificOutput`: `permissionDecision` (`allow`/`deny`/`ask`/`defer`), `permissionDecisionReason`, `updatedInput` (rewrites args), `additionalContext` | Yes — blocks tool call | sync-block; timeout → **fail-open** (call proceeds through permission flow) |
| `PermissionRequest` | tool fields | `hookSpecificOutput.decision.behavior` (`allow`/`deny`) + `updatedInput`, `updatedPermissions` | not honored | sync-block |
| `PermissionDenied` | tool fields | `hookSpecificOutput.retry: true` | ignored (already happened) | side |
| `PostToolUse` | tool fields + `tool_response`, `duration_ms` (changelog 2.x) | `decision:"block"`+`reason` (feedback to Claude), `updatedToolOutput`, `additionalContext` | No — shows stderr to Claude; tool already ran | sync-block |
| `PostToolUseFailure` | tool fields + error info | `decision:"block"` | No — stderr to Claude | sync-block |
| `PostToolBatch` | batch info | `decision:"block"` stops loop before next model call | Yes | sync-block |
| `Notification` | `message`, matcher = notification type (`permission_prompt`, `idle_prompt`, …) | none (side effects; `terminalSequence` works) | ignored | side |
| `MessageDisplay` | display info | `hookSpecificOutput.displayContent` (display-only) | No | fires during text display; **10 s default timeout** |
| `SubagentStart` | `agent_id`, `agent_type` | `additionalContext` (start of subagent conversation) | No — stderr to subagent transcript only | sync-block |
| **`SubagentStop`** | `stop_hook_active`, `agent_id`, `agent_type`, **`agent_transcript_path`**, **`last_assistant_message`**, `background_tasks`, `session_crons` (parent-scoped) | same as Stop: `decision:"block"`+`reason` keeps subagent running, reason delivered as next instruction; `hookSpecificOutput.additionalContext` = non-error feedback; matcher = agent type | Yes — prevents subagent stop; stderr routes as reason | sync-block; 8-consecutive-block cap via `stop_hook_active` |
| `TaskCreated` | `task_id`, `task_subject`, … | exit 2 or `decision:"block"` cancels task | Yes | sync-block |
| `TaskCompleted` | task fields | exit 2 blocks completion; `{"continue": false, "stopReason"}` stops teammate | Yes | sync-block |
| `Stop` | `stop_hook_active`, **`last_assistant_message`**, `background_tasks`[], `session_crons`[] | `decision:"block"`+`reason` (Claude continues); `hookSpecificOutput.additionalContext` (labeled "Stop hook feedback", no error notice) | Yes — same routing as reason | sync-block; 8-block cap; not fired on user interrupt (StopFailure on API error instead) |
| `StopFailure` | `error`, `error_details`, `last_assistant_message` (holds the API error string) | none (output ignored except `terminalSequence`) | ignored | side |
| `TeammateIdle` | teammate fields | exit 2 / `continue:false` | Yes | sync-block |
| `ConfigChange` | `source`, `file_path` | `decision:"block"` (not for `policy_settings`) | Yes | side |
| `CwdChanged` | cwd fields | none (can write `CLAUDE_ENV_FILE`) | stderr to user | side; no matcher |
| `DirectoryAdded` | how added | none | stderr to debug log | side |
| `FileChanged` | changed file; matcher = literal watch list | `watchPaths` additions | stderr to user | side |
| `WorktreeCreate` | worktree request | stdout = worktree path (command) / `hookSpecificOutput.worktreePath` (http); any nonzero exit fails creation | Yes (any nonzero) | sync-block |
| `WorktreeRemove` | worktree info | none | failures debug-logged | side |
| **`PreCompact`** | **`trigger`** (`manual`/`auto`), **`custom_instructions`** (INPUT: what the user passed to `/compact`; `null` if nothing; always `null` for `auto`) | **block only**: exit 2 or `decision:"block"` (+`reason`); `systemMessage` and `continue` are **discarded**; **no documented output field to set/modify the compaction instructions** | Yes — blocks compaction (manual: stderr to user; auto-proactive: skipped, continues uncompacted; auto-recovery: request fails) | sync-block |
| `PostCompact` | `trigger`, `compact_summary` (the generated summary) | none | stderr to user | side |
| `PreModelSwitch` | `from_model`, `to_model` (v2.1.251+) | `permissionDecision` allow/deny/ask or `decision:"block"` | Yes | sync-block; **timeout → fail-closed** (blocks switch); 30 s default |
| `PostModelSwitch` | `from_model`, `to_model` | `additionalContext` (next request); plain stdout → context | No | side |
| `Elicitation` / `ElicitationResult` | MCP server, message, schema / response | `hookSpecificOutput.action` accept/decline/cancel + `content` | Yes | sync-block |
| `SessionEnd` | `reason` (`clear`/`resume`/`logout`/`prompt_input_exit`/`other`) | none — "no decision control", JSON output fields discarded | stderr to user only | **1.5 s shared budget** (see C3) |

### A4. Output schemas, exit codes, size limits

All VERIFIED — https://code.claude.com/docs/en/hooks#json-output, #exit-code-output, #decision-control, retrieved 2026-09-08.

- **Return path**: JSON object on stdout, exit 0 preferred ("choose one approach per hook"). stdout must contain only the JSON object. Multi-line/malformed JSON rules: `{…}` shape → parse; anything else → plain text (only `UserPromptSubmit`, `UserPromptExpansion`, `SessionStart`, `PostModelSwitch` promote plain stdout to context).
- **Universal JSON fields**: `continue` (false = stop Claude entirely; takes precedence over event decisions), `stopReason` (user-facing only), `systemMessage` (user-facing warning), `suppressOutput` (accepted no-op), `terminalSequence` (allowlisted OSC escapes for notifications — works even on events that discard everything else).
- **Three decision shapes**: (1) top-level `decision: "block"` + `reason` (UserPromptSubmit, UserPromptExpansion, PostToolUse, PostToolUseFailure, PostToolBatch, Stop, SubagentStop, ConfigChange, PreCompact, TaskCreated); (2) `hookSpecificOutput` (requires `hookEventName`) for PreToolUse `permissionDecision`/`updatedInput`, PermissionRequest `decision.behavior`, and `additionalContext` on SessionStart/SubagentStart/UserPromptSubmit/UserPromptExpansion/PostToolUse-family/Stop/SubagentStop/PostModelSwitch; (3) special path-return (WorktreeCreate).
- **`additionalContext` placement** varies by event: SessionStart/SubagentStart → start of conversation before first prompt; UserPromptSubmit → alongside prompt; tool events → next to tool result; Stop/SubagentStop → end of turn, conversation continues; PostModelSwitch → next request. Multiple hooks' values all delivered. Injected as a system-reminder wrapper; saved to transcript and replayed on resume instead of re-running.
- **Exit codes**: 0 = success/no objection (does NOT approve — permission flow still applies); 2 = blocking error, stderr is the message, JSON cannot override it; any other code = non-blocking error, action proceeds (`Failed with non-blocking status code:` + first stderr line in transcript). Schema-validation failure of JSON output = non-blocking error. Hook that fails to start (e.g. exit 127, missing script) = non-blocking error → "a mistyped path in settings.json leaves the gate silently disabled" (docs' own warning — load-bearing for gates).
- **Size limits**: output strings (`additionalContext`, `systemMessage`, plain stdout) **capped at 10,000 chars** — overflow spilled to a session-dir file and replaced by a preview + path (same mechanism as large Bash results). `background_tasks`/`session_crons` `description`/`command`/`prompt` capped at 1,000 chars. **No documented limit on stdin payload or transcript reads — UNVERIFIED (absence in docs, not a verified absence).**

### A5. Configuration, scope, uninstall

All VERIFIED — https://code.claude.com/docs/en/hooks#configuration + #hook-locations, retrieved 2026-09-08.

- **Format**: `{"hooks": {"<EventName>": [{"matcher": "…", "hooks": [{"type": "command", "command": "…", "args": […], "timeout": 600, "async": true, "if": "Bash(git *)"}]}]}}`. Three nesting levels: event → matcher group → handler array. Handler types: `command`, `http` (POST body in, JSON body out; URL allowlist `allowedHttpHookUrls`), `mcp_tool`, `prompt` (30 s default), `agent` (experimental, 60 s default).
- **Matcher semantics**: `*`/`""`/omitted = all; exact-string set (letters, digits, `_`, `-`, space, `,`, `|`; comma needs v2.1.191+, hyphen v2.1.195+) else unanchored JS RegExp. Matched field varies per event (tool name for tool events; `startup|resume|clear|compact|fork` for SessionStart; `manual|auto` for PreCompact; agent type for SubagentStop; …). Matcher on a no-matcher event is silently ignored. Per-handler `if` = permission-rule syntax, tool events only.
- **Locations** (merge across levels, never replace): `~/.claude/settings.json` (user, all projects) · `.claude/settings.json` (project, committed) · `.claude/settings.local.json` (project-local, gitignored) · managed policy settings (org) · plugin `hooks/hooks.json` · skill/subagent frontmatter (skill hooks live for the session, `once: true` to auto-remove; subagent hooks removed when the subagent ends; a `Stop` hook in a subagent's frontmatter is converted to `SubagentStop`).
- **`$CLAUDE_PROJECT_DIR`**: placeholder usable in `command`/`args` and also exported as an env var on the spawned process (with `CLAUDE_PLUGIN_ROOT`, `CLAUDE_PLUGIN_DATA`). Handlers run in cwd with Claude Code's environment; prefer exec form (`args` set) for path placeholders.
- **Duplicate handling**: same handler defined in multiple settings files runs once; all *matching* handlers run in parallel and all run to completion before merge; PreToolUse merge = most restrictive wins (`deny > defer > ask > allow`).
- **Clean uninstall**: delete the hook entry from the settings JSON (file-watcher picks up edits live). Kill switches: `disableAllHooks: true` (respects managed-settings hierarchy; `--settings '{"disableAllHooks":true}'` overrides for one run). No per-hook disable flag exists. `/hooks` menu is read-only inspection. Workspace trust gates settings-file hooks in interactive sessions; `-p`/SDK sessions treat the folder as trusted (hooks in a cloned repo's `.claude/settings.json` WILL run under `-p` — security-relevant to gates).

---

## (b) Ambient-gates synthesis — the three load-bearing mechanisms

### B1. How SubagentStop and PreCompact get transcripts

**VERIFIED** (/docs/en/hooks#subagentstop, #precompact, #common-input-fields, retrieved 2026-09-08):

- Every event receives `transcript_path` (main session's JSONL). `SubagentStop` additionally receives **`agent_transcript_path`** — the subagent's own transcript in a nested `subagents/` folder — plus **`last_assistant_message`** (the subagent's final response text inline, so gates don't need to parse the transcript at all), `agent_id`/`agent_type` (matcher filters on `agent_type`), and parent-scoped `background_tasks`/`session_crons`. A gate on SubagentStop can therefore read the finished subagent's full transcript *and* its final message without touching the parent transcript.
- `PreCompact` receives only the common fields + `trigger` + `custom_instructions`. So a PreCompact gate reads the **main session transcript via `transcript_path`** — the full pre-compaction history — with the caveat that the transcript is **written asynchronously and may lag in-memory state** (docs' words); for PreCompact the whole conversation precedes the hook, so lag risk is low but not zero.
- Transcript-freshness doctrine from docs: prefer event-provided inline fields (`last_assistant_message`) over parsing `transcript_path` when you need the just-finished turn's final text.
- Gate semantics: SubagentStop can **block the stop** (`decision:"block"`+`reason` → reason becomes the subagent's next instruction; exit 2 routes stderr the same way; 8-consecutive-block circuit breaker via `stop_hook_active`). PreCompact can **block compaction** but nothing else; blocking *auto*-compaction that was triggered to recover from a context-limit error **fails the current request** — a PreCompact gate must distinguish proactive vs recovery auto-compact, which the payload does NOT expose (only `manual`/`auto`) — **UNVERIFIED/ambiguous, flagged**.

### B2. How SessionStart injects context

**VERIFIED** (/docs/en/hooks#sessionstart, #add-context-for-claude, retrieved 2026-09-08):

- Two channels, both land **at the start of the conversation, before the first prompt**: (1) plain-text stdout (SessionStart is one of only four events where plain stdout becomes context); (2) `hookSpecificOutput.additionalContext` — use JSON when combining with `sessionTitle`, `initialUserMessage`, `watchPaths`, or `reloadSkills`. Text is wrapped in a system reminder; not a chat message; Claude reads it on the first model request.
- `matcher` on `source`: `startup|resume|clear|compact|fork` — the `compact` matcher is the canonical "re-inject after every compaction" pattern (guide shows exactly this), and `resume` hooks re-run on `--resume`/`--continue` (refreshing stale injected state; mid-session injections are *replayed* from the transcript rather than re-run).
- Limits: 10,000-char cap per string → file spill with preview. SessionStart cannot block or fail the session (exit 2 = stderr to user, session proceeds) and supports only `command`/`mcp_tool` handler types. Env-var persistence available via `$CLAUDE_ENV_FILE` (append `export` lines).

### B3. Timeout & sync/async posture

**VERIFIED** (/docs/en/hooks#timeouts, #common-fields (timeout row), #run-hooks-in-the-background; /docs/en/hooks-guide, retrieved 2026-09-08):

- **Default is synchronous**: "By default, hooks block Claude's execution until they complete." All matching handlers run in parallel but the event's outcome waits for all of them; results merge (most-restrictive wins).
- **Timeout budgets**: `timeout` field per handler, seconds. Defaults: 600 (command/http/mcp_tool), 30 (prompt), 60 (agent). **Lowered defaults: 30 s on `UserPromptSubmit`, `PreModelSwitch`, `PostModelSwitch`; 10 s on `MessageDisplay`. `SessionEnd`: 1.5 s *shared* budget across all its hooks, auto-raised to the highest configured per-hook timeout up to 60 s (plugin-hook timeouts don't raise it), overridable via `CLAUDE_CODE_SESSIONEND_HOOKS_TIMEOUT_MS`.**
- **On timeout the hook is cancelled and its output discarded** → fail-open, with two fail-closed exceptions: a timed-out `PreModelSwitch` blocks the switch, and Agent SDK *callback* hooks (not settings-file command hooks) block on timeout at PreToolUse/UserPromptSubmit. Docs warn explicitly: "don't count on a stalled hook to act as a gate."
- **`async: true`** (command hooks only): runs in background, agent continues; only `additionalContext`/`systemMessage` from the JSON response are delivered **on the next turn**; decision fields have no effect; `timeout` not enforced while backgrounded; in `claude -p`, async hooks are killed at teardown (outcome `cancelled`) — detached process needed to outlive the session. `asyncRewake` variant (timeout still enforced; exit 2 wakes an idle session) — INFERRED from brief mentions, details thin: **UNVERIFIED specifics**.
- **Ambiguity flag (UNVERIFIED)**: the reference prose says hooks block by default, but the lifecycle diagram's alt text labels `WorktreeCreate/Remove`, `Notification`, `ConfigChange`, `InstructionsLoaded`, `CwdChanged`, `FileChanged`, `DirectoryAdded`, and `PostModelSwitch` as "standalone **async** events." INFERRED reading: these side-events don't sit on the model's blocking path (consistent with their "no decision control / ignored exit code" rows), but the docs never state their blocking posture in prose. A gates contract must not assume these can gate anything — they are observe-only by schema.

---

## (c) opencode hook/event surface (pressure-test paragraph)

**VERIFIED** — https://opencode.ai/docs/plugins/ (retrieved 2026-09-08; page footer "Last updated: Sep 8, 2026"). opencode has no settings-JSON hooks: extensions are **JS/TS plugin modules** auto-loaded from `.opencode/plugins/` (project) or `~/.config/opencode/plugins/` (global), or npm packages named in `opencode.json`'s `plugin` array. A plugin is an async function receiving `{project, client, $, directory, worktree}` that returns a hooks map with two surfaces: **interception hooks** — `tool.execute.before` / `tool.execute.after` (mutable `(input, output)`; throw to block — ≈ PreToolUse/PostToolUse), `shell.env`, and `experimental.session.compacting` (`output.context.push(...)` injects compaction context or `output.prompt` **replaces the whole compaction prompt** — an ability PreCompact notably lacks) — and **bus events** — `event: async ({event}) => …` with `event.type` from a flat catalogue (`session.created`, `session.idle` ≈ Stop, `session.compacted` ≈ PostCompact-but-after-the-fact, `session.error`, `message.updated`, `permission.asked`, `file.edited`, `todo.updated`, `tui.*`, …) that are observe-only. There is no SessionStart-context-injection hook and no PreCompact block; payloads are in-process objects, not stdin JSON, and config lives in `opencode.json`, not `settings.json`. Pressure-test conclusion for a framework-agnostic `gates fire` contract: model each gate as *event name + JSON payload in → decision/context JSON out*, keep the event vocabulary to the intersection (tool-pre, tool-post, turn-end, session-start ≈ plugin-init, compact-pre), and treat "block" as a first-class return that each adapter maps to its host's mechanism (exit 2 / `decision:"block"` for Claude Code; a thrown error for opencode) — the contract survives both hosts; anything Claude-Code-specific (matchers, `hookSpecificOutput` envelope, transcript paths) must stay behind the adapter.

---

## (d) Sources

| # | Source | URL | Retrieved |
|---|---|---|---|
| 1 | Claude Code hooks reference (canonical, current) | https://code.claude.com/docs/en/hooks | 2026-09-08 |
| 2 | Claude Code hooks guide ("Automate actions with hooks") | https://code.claude.com/docs/en/hooks-guide | 2026-09-08 |
| 3 | anthropics/claude-code CHANGELOG.md (raw, `main`) — event intro versions 2.0.43–2.1.251 | https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md | 2026-09-08 |
| 4 | opencode Plugins docs (events catalogue, compaction hooks, config) | https://opencode.ai/docs/plugins/ | 2026-09-08 |

Note: `docs.anthropic.com/en/docs/claude/code/hooks` is the legacy URL for source 1; the live canonical host is `code.claude.com` (the docs' own cross-links all use it).

### Open ambiguities carried to the spec ticket

1. **PreCompact cannot set compaction instructions** — `custom_instructions` is input-only; no output field documented. If ambient gates must *shape* compaction (not just block it), that's impossible via hooks in Claude Code today (opencode can, via `experimental.session.compacting`). VERIFIED-as-absence.
2. **PreCompact `auto` payload does not distinguish proactive vs recovery compaction**, but blocking them has opposite failure modes (skip-and-continue vs fail-the-request). VERIFIED gap.
3. **Blocking posture of the eight "standalone async" side-events** is only in diagram alt text, never prose. UNVERIFIED.
4. **No documented limits on stdin payload size or transcript read rate**; the only hard caps are the 10,000-char output strings and 1,000-char task-description fields. UNVERIFIED-as-absence.
5. **Intro versions for `Setup`, `UserPromptExpansion`, `PermissionRequest`, `PermissionDenied`, `PostToolUseFailure`, `PostToolBatch`** not pinned in the searched changelog span. UNVERIFIED.
