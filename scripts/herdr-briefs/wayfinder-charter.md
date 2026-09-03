# Wayfinder charter — chart a new milestone map (HITL, run in arch's pane)

You are charting a NEW Wayfinder map for the kultivait herd. The human is
live in this pane with you: this is a human-in-the-loop session. You ask;
they answer. Never answer your own questions.

Follow the wayfinder skill (already loaded or loadable via the Skill tool:
"wayfinder"). Summary of the pass you are about to run:

## 1. Name the destination

Call the Skill tool twice — "grilling" and "domain-modeling" — and interview
the human until the destination is pinned: what does reaching the end of this
map look like (the spec, decision, or change)? One or two lines. The
destination fixes scope; settle it first. Record domain terms into the
glossary as they surface (CONTEXT.md).

## 2. Map the frontier, breadth-first

Grill again, fanning out ACROSS the space (not deep on one thread): surface
every open decision and the first takeable steps. If no fog emerges — the
whole journey fits one session — STOP and ask the human how to proceed
instead of forcing a map.

## 3. Create the map

`gh issue create -R Standard-Pentest/kultivait --label wayfinder:map` with
the canonical body: Destination / Notes / Decisions so far (empty) /
Not yet specified (the fog) / Out of scope. Notes must name the skills every
working session should consult and the standing preferences for this effort.

## 4. Create tickets + wire blocking (second pass)

- Children as GitHub sub-issues of the map (per docs/agents/issue-tracker.md),
  each body a single sharp `## Question`, labelled `wayfinder:<type>`.
- Wire blocking edges AFTER creation (issues need ids first), using NATIVE
  issue dependencies. The frontier must be visible in GitHub's own UI.
- Everything not yet sharp stays in the map's "Not yet specified" — do not
  pre-slice fog.

## 5. Fire research subagents

For each `research` ticket, spin a subagent calling the Skill tool "research",
capturing findings on a throwaway branch, with a context pointer from the
ticket.

## 6. Stop

Charting is one session's work; you hand-resolve nothing. Finish by posting
the map's number and title into this pane, e.g.
`CHARTERED — Map #N: <title> (K frontier, M blocked, F fog)`. The human then
kicks the looper to work the map.
