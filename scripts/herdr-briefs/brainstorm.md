# Brainstorm — project direction → design → PRD → tickets (HITL, run in arch's pane)

You are running a brainstorm session for the kultivait herd. The human is
live in this pane with you: this is a human-in-the-loop session. You ask;
they answer. Never answer your own questions or fill in their preferences.

Work through these phases in order; do not skip ahead past a phase the human
hasn't signed off on.

## Phase 1 — Direction (grill-with-docs)

Call the Skill tool twice — "grilling" and "domain-modeling". Relentlessly
interview the human on the topic below until the direction is concrete:
- the problem and who it's for;
- the shape of the solution and its boundaries (what it is NOT);
- the domain vocabulary — record terms in CONTEXT.md as they settle;
- the decisions worth keeping — draft an ADR per locked decision
  (`docs/adr/NNNN-<slug>.md`, delegate polishing to agy-docs if the human
  prefers: `herdr agent prompt agy-docs "..." --wait`).

## Phase 2 — Design

If the direction implies UI or module interfaces, raise fidelity cheaply:
call the Skill tool "prototype" (a rough artifact to react to beats
abstraction) or "design-an-interface" for module-shape questions. Keep
iterating with the human until the design is reactable-to and specific.

## Phase 3 — PRD (to-spec)

Call the Skill tool "to-spec": synthesize the interview + design into a spec
published to the tracker as a GitHub issue (`-R Standard-Pentest/kultivait`),
no further interview — just what was actually discussed. Link the spec issue
into the docs: `docs/superpowers/specs/<date>-<slug>-design.md` gets the
durable copy.

## Phase 4 — Tickets (to-tickets)

Call the Skill tool "to-tickets": break the spec into tracer-bullet tickets,
each declaring its blocking edges, published to
`-R Standard-Pentest/kultivait` with native issue dependencies wired in a
second pass.

## Close

Post in this pane: `SPEC'D — <spec issue #> + N tickets (frontier: #a, #b)`.
The human then kicks the looper to drain the tickets.
