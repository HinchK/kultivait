# Ambient-gates herd dogfood — verdict & evidence

Ticket: [#161](https://github.com/Standard-Pentest/kultivait/issues/161) · map: [#156](https://github.com/Standard-Pentest/kultivait/issues/156)
Date: 2026-09-08 · Subject: `kultivait gates` as installed on this repo, Claude Code 2.1.239, kultivait tool installed from upstream main (post-#164).

**Verdict: PASS — the loop is live end-to-end on real herd traffic.**

## What ran

1. `kultivait gates install --claude` into project `.claude/settings.json` (+ `.kultivait/gates.toml` scaffold). Claude Code's session footer confirmed **5 hooks** loaded (our 3 + 2 pre-existing local ones).
2. **Session 1** (headless `claude -p`, subagent task on AGENTS.md): the model spawned several Task subagents; each subagent end fired the async SubagentStop gate. Result: **4 briefs written live** (21:09–21:10) to `~/.kultivait/briefs/kultivait-6fc6c061/`, provenance headers per spec, compost grown in the same window (e.g. `previous-next-1c222372.txt` at 21:10:30). No `gates.log` entries — zero errors.
3. **Session 2** (fresh `claude -p`, explicitly forbidden from reading files): asked what the latest ambient brief concluded. It **quoted brief 004's FINDINGS verbatim** — file paths, 29-line count, the `.codex` distinction, and the 4-section count — sourced solely from the SessionStart injection. **Consumption proven.**
4. **Uninstall drill**: `gates uninstall --claude` removed all three events, leaving `{}` (the two foreign hooks in `settings.local.json` untouched by design); reinstall restored idempotently. End state: **gates reinstalled** for continued herd dogfooding.

## Evidence pointers

- Briefs: `~/.kultivait/briefs/kultivait-6fc6c061/00{1..4}-*.md` + `latest.json` (listing via `kultivait gates briefs`).
- Brief 002 is the richest distillation (full AGENTS.md heading analysis with paths, decisions, constraints); brief 004 (the `latest`) is the clean final handoff the next session consumed.
- Session transcripts: `~/.claude/projects/-Users-hinchk-seeds-_KULT_-kultivait/` (21:09–21:10 window).

## Friction notes (honest)

- **Thin briefs from trivial subagents**: briefs 001/003 (3→17 and 2→29 tokens) came from tiny subagent turns (file-existence checks). Not wrong — every subagent end is a boundary — but the designed remedy is the phase map / `agent_type` matcher in `.kultivait/gates.toml` to gate only meaningful agent types. Recorded as the tuning knob for real herd use.
- **The `-p` async-kill caveat was NOT observed**: research says headless teardown kills pending async hooks, but all four distills (10–20 s each) completed inside the session's lifetime. Durable compost guarantees the worst case regardless (eval G3, #160).
- Driving the **interactive** TUI under automation was abandoned (slow startup made pty scripting unreliable); headless `-p` exercised the same hook wiring — hooks load and fire identically per the API register.
- `.claude/settings.json` and `.kultivait/` are kept **uncommitted** local herd state for now (gitignored): committing project-scope hooks — so every clone gets gated fail-open — is a rollout decision, deliberately left to the README/docs fog item on map #156.

## Rollout updates landed with this ticket

README: `gates` command line added; "Ambient gates" removed from Roadmap (shipped). Docs index + ADR index: ambient-gates spec, hooks-API research register, and ADR 0019 rows added.
