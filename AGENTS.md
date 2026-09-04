# Project AGENTS.md - Kultivait

Pilot implementation of AgentsView session-insights recommendations.

---

## 1. Standard Prompt Preamble

When prompting in this repository, use the standard 3-line format:

1. **Intended Outcome**: [Target outcome or feature]
2. **Explicit Done-Criteria**: [Clear testable acceptance criteria]
3. **Verification Step**: [Command or test suite to run, e.g., `pytest`]

---

## 2. Agent Restatement Protocol

If a prompt omits explicit done-criteria or verification commands:
- The agent must restate its assumed outcome, completion criteria, and verification steps prior to starting multi-step execution.

---

## 3. Context Budget & Checkpoint Management

- **State File**: For complex tasks or extended planning, maintain a state file (`STATE.md` at the repo root; create it if absent) with decisions, open items, and next steps.
- **Slice Boundaries**: Execute multi-slice features across separate focused sessions.
- **Spec-Driven Work**: Start complex tasks from a design spec (`docs/superpowers/specs/<date>-<slug>-design.md`).
