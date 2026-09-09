# Ambient gates: CLI-direct, async, never-blocking; SessionStart injects; briefs are source of truth

Ambient phase-gates fire from agent-framework hooks through a framework-agnostic core — `kultivait gates fire`, one JSON payload on stdin — with `SubagentStop` and `PreCompact` triggering the distill and `SessionStart` injecting the latest handoff brief. The hooks call the `kultivait` binary directly rather than the running proxy: ambient hygiene must survive (and stay cheap on) machines where the proxy is not serving, and the `prune` standalone gate path (local model via the runtime) is the engine. Firing hooks run `async: true` and obey a never-block rule — no `decision`, no exit 2, no host-visible stall — because blocking `PreCompact` on recovery compaction fails the host's request outright and blocking `SubagentStop` loops the subagent; durability comes from composting the transcript synchronously before distillation begins, so a teardown-killed async hook (the host kills them under `-p`) loses at most the derived brief. Delivery is hybrid: `~/.kultivait/briefs/<project>/` is the source of truth (bounded rotation of 20, `latest.json` manifest, provenance headers make recency legible with no TTL), the all-source SessionStart matcher (`startup|resume|clear|compact|fork`) re-injects the latest brief after every session start and compaction, and a one-line project instruction names the directory as the fallback channel. The command family is `kultivait gates` — "hook" stays adoption-only vocabulary (`kultivait hook shell|ide|loopback`). Grounded in the hooks-API ground-truth register (`docs/research/2026-09-04-claude-hooks-api.md`, sources retrieved 2026-09-08).

## Considered Options

- **Proxy-transport gating** (hooks POST the running proxy's `/gate`): rejected — ambient hygiene would depend on proxy liveness and pay HTTP latency for a local operation; the standalone `prune` engine already runs without the proxy.
- **Synchronous distill hooks** (default sync, accept the stall): rejected — local-model distills run seconds to tens of seconds; sync `SubagentStop` would stall the parent session per subagent, and a host timeout cancels the work entirely (fail-open discards output).
- **Blocking gates** (use `decision:"block"` to enforce gating): rejected — blocking `PreCompact` during recovery auto-compaction fails the host request (payload cannot distinguish recovery from proactive), and blocking `SubagentStop` fights the 8-consecutive-block circuit breaker; gates advise via injected context, never coerce.
- **Stop-event firing** (gate every turn end): rejected — brief-per-turn floods the briefs lane and the compost pile with near-identical distills; phase boundaries are subagent ends and compaction points.
- **Single rolling `latest.md`** (no brief history): rejected — dogfooding and eval need the sequence visible; bounded rotation of 20 gives history without unbounded disk.
- **Staleness TTL on injection**: rejected — the provenance header (phases, timestamp, token counts) makes recency legible; the consuming agent judges relevance better than a clock.
- **Shaping compaction via PreCompact `custom_instructions`**: impossible rather than rejected — the field is input-only in the host API (register, open ambiguity 1); noted so nobody re-attempts it.
- **Model-labeled phase inference** (local model tags from/to phases from the transcript tail): rejected for v1 — nondeterministic, adds a model call on the firing path; the repo-local phase map (`.kultivait/gates.toml`, default `previous → next`) is explicit and project-controllable.
- **Extending `kultivait hook`** (a fourth `hook gates` flavor): rejected — "hook" is adoption wiring in the glossary and the CLI; gates are a different concept and earn their own family.

## Consequences

- `kultivait gates fire` is the single framework-agnostic entry point; adapters are thin config wrappers (v1: Claude Code; the contract deliberately stays at the event-vocabulary intersection so an opencode plugin adapter is additive, not a rewrite).
- SubagentStop gates read the subagent's own `agent_transcript_path`; PreCompact gates read the main `transcript_path`; both prefer inline fields per the host's freshness doctrine.
- Compost-before-distill is a hard ordering invariant (testable; carried into the eval as a kill-mid-distill case).
- Briefs are derived artifacts: rotation deletes old briefs without archival because every source transcript is composted.
- `gates install/uninstall --claude` manages a reviewable, committed `.claude/settings.json` block matched by command string; uninstall cannot collide with user hooks.
- All gate failures are silent-by-design (exit 0 + `~/.kultivait/gates.log`): fail-open matches the host's own posture toward broken hooks.
