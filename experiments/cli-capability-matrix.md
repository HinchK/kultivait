# CLI dispatch & effort capability matrix

Research ticket: [Standard-Pentest/kultivait#5](https://github.com/Standard-Pentest/kultivait/issues/5) (child of map #4).
Date: 2026-08-21. Machine: darwin/arm64.

What each of the five frontier CLIs can do when driven **non-interactively**, established from
primary sources: the installed binary's `--help` output for the exact local version, plus official
web docs where `--help` is silent. One empirical probe (`claude -p ... --output-format json`) was
run to ground exit-code and JSON-shape claims.

## Versions (installed, on PATH)

| CLI | Path | Version |
| --- | --- | --- |
| claude | ~/.local/bin/claude | 2.1.238 (Claude Code) |
| agy | ~/.local/bin/agy | 1.1.17 |
| gemini | /opt/homebrew/bin/gemini | 0.56.0 |
| codex | /opt/homebrew/bin/codex | codex-cli 0.149.0 |
| opencode | /opt/homebrew/bin/opencode | 1.18.21 |

## Summary comparison

| | claude | agy | gemini | codex | opencode |
| --- | --- | --- | --- | --- | --- |
| **Non-interactive invocation** | `claude -p <prompt>` | `agy -p <prompt>` (`--print`, `--prompt`) | `gemini -p <prompt>` (headless) | `codex exec <prompt>` (subcommand; **no `-p`** — `-p` means `--profile`) | `opencode run <message>` (subcommand; **no `-p`** — top-level `--prompt` starts the TUI) |
| **Model flag** | `--model <alias\|full>` (e.g. `sonnet`, `opus`) | `--model <name>` (e.g. `gemini-3.7-flash-high`) | `-m, --model <name\|alias>` | `-m, --model <MODEL>` | `-m, --model provider/model` |
| **Effort knob** | `--effort low\|medium\|high\|xhigh\|max` | `--effort low\|medium\|high` **and** effort-suffixed model names | none in CLI; `modelConfigs` `thinkingLevel`/`thinkingBudget` via settings + `-m <alias>` | `-c model_reasoning_effort="minimal\|low\|medium\|high\|xhigh"` (config override) | `--variant <effort>` on `run` (e.g. `high`, `max`, `minimal`) |
| **Prompt input** | positional, `-p`, stdin (10 MB cap) | `-p`/positional via `--print`, stdin (`--input-format text\|stream-json`) | `-p` (appended to stdin if piped), positional `query`, stdin | positional PROMPT, stdin (prompt-plus-context), `codex exec -` (stdin as full prompt) | positional `message` (array), `-f/--file` attachments |
| **Resume / session** | `--resume <id>`, `--continue`, `--session-id <uuid>`, `--fork-session` | `--conversation <id>`, `--continue` | `-r/--resume latest\|<index>`, `--session-id <uuid>`, `--session-file <path>` | `codex exec resume <id>\|--last`, `codex resume`, `codex fork`, `codex queue` | `-s/--session <id>`, `-c/--continue`, `--fork` |
| **Structured output** | `--output-format json` + `--json-schema <schema>` (validated; `structured_output` field) | `--output-format json` + `--json-schema` | `-o text\|json\|stream-json` (no schema enforcement) | `--output-schema <file>` + `-o/--output-last-message <file>`, `--json` JSONL | `--format default\|json` (raw JSON events) |
| **Streaming** | `--output-format stream-json` (+ `--include-partial-messages` for token deltas) | `--output-format stream-json` | `-o stream-json` | `--json` JSONL events (thread/turn/item) | `--format json` (raw JSON events) |
| **Usage/cost reported?** | yes — `usage`, `total_cost_usd` in json result | json result (print mode) | json output | yes — `turn.completed` carries token usage (input/cached/output/reasoning) | json events |
| **Auth** | subscription OAuth or `ANTHROPIC_API_KEY` (`--bare` = key only) | Google/Antigravity account (delegated) | OAuth or `GEMINI_API_KEY`/`GOOGLE_API_KEY` (Vertex via `GOOGLE_CLOUD_PROJECT`) | `codex login` (ChatGPT OAuth) or `CODEX_API_KEY` | `opencode providers/auth` — many providers, per-provider credentials |
| **Exit codes** | 0 success, non-zero failure (empirically 1 on API error), 143 on SIGTERM | undocumented in --help; standard 0/non-zero | undocumented in --help; standard 0/non-zero | 0 success, non-zero failure (errors to stderr; stdout stays final message) | undocumented in --help; standard 0/non-zero |

## claude (Claude Code 2.1.238)

- **Model**: `--model` takes aliases (`opus`, `sonnet`, `fable`) or full names (`claude-fable-5`); `--fallback-model` (print mode only) retries alternates when the primary is overloaded.
- **Effort**: `--effort <level>` with `low, medium, high, xhigh, max` (CLI `--help`). SDK docs confirm `EffortLevel = low | medium | high | xhigh` and note `xhigh` falls back to `high` on models that don't support it. `--max-budget-usd` caps spend (print mode).
- **Prompt**: positional arg or `-p/--print`; reads stdin (piped data capped at 10 MB). Heredoc/pipes work as ordinary stdin.
- **Sessions**: `-r/--resume <id>`, `-c/--continue`, `--session-id <uuid>` (pre-chosen UUID), `--fork-session`, `--from-pr`. Docs show the dispatch pattern: capture `session_id` from `--output-format json`, then `--resume "$session_id"`. `--no-session-persistence` opts out.
- **Structured output**: `--output-format text|json|stream-json`; `--json-schema '{"type":...}'` validates (invalid schema exits with an error) and lands the parsed object in `structured_output`.
- **Streaming**: `stream-json` + `--include-partial-messages` yields token deltas; last line is a `result` message with final text, cost, session metadata.
- **Exit/auth (empirical + docs)**: exit 0 success / non-zero failure; 143 on SIGTERM. Auth is subscription OAuth by default (`apiKeySource: "none"` in the probe init), or `ANTHROPIC_API_KEY`; `--bare` skips all host customization and *requires* key/apiKeyHelper auth. Failures inside the run (e.g. 429 rate limit) are printed as the result on stdout with `is_error: true`, exit 1 — dispatchers must check the JSON, not just exit code.
- Sources: `claude --help` (2.1.238); https://code.claude.com/docs/en/headless ; Agent SDK Python reference (`EffortLevel`).

## agy (Antigravity CLI wrapper, 1.1.17)

- **What it wraps**: native arm64 binary delegating to Google **Antigravity** (Gemini-family backend). Config lives at `~/.gemini/antigravity-cli/settings.json` (current: `model: "Gemini 3.7 Flash (High)"`, `agentMode: accept-edits`, `toolPermission: always-proceed`); state (conversations, brain, `jetski_state.pbtxt`) lives beside it in `~/.gemini/antigravity-cli/`.
- **Model**: `--model`; `agy models` lists effort-baked names: `gemini-3.7-flash-{high,medium,low}`, `gemini-3.1-pro-{high,low}`, plus non-Gemini guests (`claude-sonnet-4-6`, `claude-opus-4-6-thinking`, `gpt-oss-120b-medium`).
- **Effort**: two roads — the `--effort low|medium|high` flag, or selecting an effort-suffixed model name. Settings also carry a `runningLightSpeed: "fast"` knob.
- **Prompt**: `-p`/`--print`/`--prompt` (aliases); `--input-format text|stream-json` for NDJSON stdin; `--print-timeout` (default 5m) bounds print mode.
- **Sessions**: `--conversation <ID>` resumes by ID; `-c/--continue` continues the most recent.
- **Structured output**: `--output-format text|json|stream-json`; `--json-schema` (string or path) enforces a schema (final result only, in stream mode).
- **Auth**: whatever the wrapped Antigravity runtime is logged in as (Google account).
- Sources: `agy --help`, `agy models`, `~/.gemini/antigravity-cli/settings.json`.

## gemini (Gemini CLI 0.56.0)

- **Model**: `-m/--model`; accepts built-in aliases (`pro`, `flash`, `flash-lite`, `auto`) and custom aliases defined under `modelConfigs.customAliases` — aliases resolve to a model plus generation config.
- **Effort**: **no CLI flag**. Controlled by `modelConfigs` in settings.json (`~/.gemini/settings.json`, `.gemini/settings.json`): `generateContentConfig.thinkingConfig.thinkingLevel` (`"HIGH"` etc., used by the Gemini-3 `chat-base-3` default) and `thinkingBudget` (token budget; `0` disables — used by built-in utility aliases like `prompt-completion`). Practical dispatch: define custom aliases (e.g. `fast` = `thinkingBudget: 0`, `deep` = `thinkingLevel: HIGH`) and select them with `-m`. Plan-vs-fast is otherwise approximated by `--approval-mode plan` (read-only) and `general.plan.modelRouting` (Pro for planning, Flash for implementation).
- **Prompt**: `-p/--prompt` runs headless and is *appended to stdin if stdin is piped*; positional `query` stays interactive unless `-p`. `-i/--prompt-interactive` runs one prompt then opens the TUI.
- **Sessions**: `-r/--resume latest|<n>` (index-based, per project), `--session-id <uuid>`, `--session-file <path>`, `--list-sessions`, `--delete-session`.
- **Structured output**: `-o/--output-format text|json|stream-json`; no schema enforcement — parse `json` output yourself.
- **Auth**: OAuth login or `GEMINI_API_KEY`/`GOOGLE_API_KEY` env vars; Vertex via `GOOGLE_CLOUD_PROJECT` + billing settings. Note: docs banner says unpaid/Google-One tiers are being moved to Antigravity CLI.
- Sources: `gemini --help` (0.56.0); https://geminicli.com/docs/reference/configuration/ ; https://geminicli.com/docs/cli/generation-settings/ .

## codex (Codex CLI 0.149.0)

- **Dispatch shape**: non-interactive is a **subcommand** — `codex exec "<prompt>"`. `-p` on the root command means `--profile`, not print. Streams progress to stderr; final agent message on stdout.
- **Model**: `-m/--model <MODEL>` (root and exec).
- **Effort**: no flag; config override `-c model_reasoning_effort="minimal|low|medium|high|xhigh"` (values from the official config reference), or persist in `~/.codex/config.toml`. Also `agents.default_subagent_reasoning_effort` for spawned agents.
- **Prompt**: positional PROMPT; stdin piped alongside a prompt arg becomes a `<stdin>` context block; `codex exec -` makes stdin the whole prompt (heredoc-friendly).
- **Sessions**: `codex exec resume <SESSION_ID>` / `codex exec resume --last`; also `codex resume` (interactive picker, `--last`), `codex fork`, `codex queue` (queue a message into an existing session), `codex archive/delete`. `--ephemeral` skips persistence.
- **Structured output**: `--output-schema <FILE>` (JSON Schema) shapes the final response; `-o/--output-last-message <FILE>` writes it to disk. `--json` switches stdout to JSONL events (`thread.started`, `turn.started/completed/failed`, `item.*`, `error`); `turn.completed` carries `usage` with input/cached/output/reasoning tokens.
- **Sandbox**: default read-only; `-s/--sandbox workspace-write|danger-full-access`; `-a/--ask-for-approval never` for unattended runs; `--skip-git-repo-check` outside repos.
- **Auth**: reuses `codex login` credentials (ChatGPT OAuth) by default; `CODEX_API_KEY` env for single-run API-key auth. Git repo required by default.
- Sources: `codex --help`, `codex exec --help` (0.149.0); https://developers.openai.com/codex/non-interactive-mode ; config reference (`model_reasoning_effort`).

## opencode (1.18.21)

- **Dispatch shape**: non-interactive is a **subcommand** — `opencode run [message..]` (positional message array). The root command has `--prompt` but that is for the TUI; `opencode -p` is not a print mode.
- **Model**: `-m/--model provider/model` (namespaced format); `opencode models [provider]` lists.
- **Effort**: `--variant <effort>` on `run` — "model variant (provider-specific reasoning effort, e.g. high, max, minimal)". This is the effort knob.
- **Prompt**: positional `message`; `-f/--file` attaches files; `--command` runs a saved command with message as args.
- **Sessions**: `-s/--session <id>` to continue, `-c/--continue` last session, `--fork`; `--share`, `opencode export <sessionID>`; can `--attach` to a running `opencode serve` instance (client/server dispatch).
- **Structured output**: `--format default|json` — json emits raw JSON events; no schema flag. `--thinking` includes thinking blocks.
- **Auth**: `opencode providers` (alias `auth`) manages per-provider credentials — multi-provider by design (any provider/model pair), so pricing varies by selection.
- Sources: `opencode --help`, `opencode run --help` (1.18.21).

## Implications for kultivait

1. **`CLIBackend`'s `-p <prompt>` assumption breaks for codex and opencode** (`src/kultivait/backends.py:301`). `codex -p <prompt>` would be parsed as `--profile <prompt>` (wrong semantics, likely an error), and `opencode -p` isn't a print mode at all. Correct dispatch: `codex exec <prompt>` and `opencode run <prompt>`. The `command` TierSpec field is already a `list[str]`, so per-CLI templates (e.g. `["codex", "exec"]`, `["opencode", "run"]`) plus a prompt-position convention would fix this without reshaping the config.
2. **codex/opencode are unregistered** in `KNOWN_CLIS`/`CLI_PRICING` (`src/kultivait/config.py:26-31`), so `detect()` silently drops them even when installed and authenticated. Registering them would fill the `docs`/`architect` roles on machines without claude/agy/gemini.
3. **Effort fitting is expressible on every CLI, but through four different mechanisms** — flag (`claude --effort`, `agy --effort`, `opencode --variant`), config override (`codex -c model_reasoning_effort=...`), or model-name/alias selection (`agy` effort-suffixed models; `gemini` custom aliases carrying `thinkingLevel`/`thinkingBudget`). A kultivait effort tier therefore needs a per-CLI *adapter* mapping an abstract level (fast/balanced/deep) onto the CLI's mechanism, not a shared flag.
4. **Token-estimate workaround can be retired selectively**: claude (`--output-format json`: `usage`, `total_cost_usd`) and codex (`--json`: `turn.completed` usage) report real usage; CLIBackend's ~4-chars/token estimate (backends.py:311-313) only needs to cover agy/gemini/opencode.
5. **Sessions are resume-capable everywhere** (claude `--resume <id>`, agy `--conversation <id>`, gemini `--resume`, codex `exec resume`, opencode `-s <id>`), so a future dispatch-continuation feature has uniform building blocks — but session IDs must be captured from JSON output (claude/codex) rather than stdout text.
6. **Structured output**: only claude (`--json-schema`) and codex (`--output-schema`) enforce a schema; plan for lenient JSON parsing on the rest. **Error detection** must not rely on exit codes alone — claude prints in-run failures (rate limits) as a normal result with exit 1; check `is_error`/`terminal_reason` in the JSON.

## Sources

- Local binaries: `claude --help` (2.1.238), `agy --help` + `agy models` (1.1.17), `gemini --help` (0.56.0), `codex --help` + `codex exec --help` (0.149.0), `opencode --help` + `opencode run --help` (1.18.21); `~/.gemini/antigravity-cli/settings.json`.
- Empirical: `claude -p "..." --output-format json --effort low` (exit 1 on 429; full JSON event shape observed).
- Docs: https://code.claude.com/docs/en/headless ; https://code.claude.com/docs/en/sdk/sdk-python (EffortLevel) ; https://geminicli.com/docs/reference/configuration/ ; https://geminicli.com/docs/cli/generation-settings/ ; https://developers.openai.com/codex/non-interactive-mode ; https://developers.openai.com/codex/config-reference (model_reasoning_effort).
