# Phase gates and escalations

Long agent sessions pile up context. kultivait can distill a transcript into
a short brief with a local model, so starting the next phase fresh costs
nothing, and it can hand a local conversation off to a frontier model when
the garden isn't enough.

## Phase-gate briefs: `kultivait prune`

`prune` distills a transcript into a FINDINGS / DECISIONS / CONSTRAINTS /
OPEN QUESTIONS brief using a local model:

```bash
kultivait prune --from explore --to plan transcript.txt
```

The full transcript is always composted to `~/.kultivait/compost/` first.
Distillation loses detail by design, and the compost pile is where you go to
get it back. The proxy offers the same operation as `POST /gate`.

## Ambient gates

Ambient gates run the same distillation at phase boundaries without you
invoking it, through agent-framework hooks. Claude Code is the supported
framework today:

```bash
kultivait gates install --claude     # add the hooks to the project's .claude/settings.json (--dry-run to preview)
kultivait gates briefs               # list handoff briefs for this project
kultivait gates uninstall --claude   # remove kultivait's hooks; other hooks are left alone
```

When a subagent finishes or the context is about to be compacted, the hook
composts the transcript and distills a handoff brief into
`~/.kultivait/briefs/<project>/`, which keeps the latest 20. After every
session start, including the one that follows a compaction, the latest
brief is injected back into the session.

The hooks call the `kultivait` binary directly, so gates work whether or not
the proxy is running. They run asynchronously and never block the agent. If
the host kills a hook partway through, the transcript is already in the
compost pile; at most the brief is lost. Phase names come from
`.kultivait/gates.toml` in the project and default to `previous → next`.

## Escalations

When a request is classified for the cloud but served locally, either
because it carried tools or because you don't have that cloud tier,
kultivait archives the full conversation as an escalation. When you decide
the local answer wasn't good enough:

```bash
kultivait escalations              # list cloud-worthy prompts served locally
kultivait escalations --brief      # distill the latest into a paste-ready brief
```

The brief (TASK / CONTEXT / PROGRESS / NEEDED) is distilled by your local
model and names the recommended target, such as "take this to Claude", so
escalating costs one paste instead of re-explaining the whole session. The
brief is only distilled when you ask for it, so requests never wait on it.

## Related

- [ADR 0019](../adr/0019-ambient-gates.md): why gates are asynchronous and never block
- [Ambient gates design](../superpowers/specs/2026-09-08-ambient-gates-design.md)
- [Claude Code hooks API notes](../research/2026-09-04-claude-hooks-api.md)
- [Ambient gates dogfood verdict](../research/2026-09-08-ambient-gates-dogfood.md)
