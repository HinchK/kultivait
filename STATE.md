# State checkpoint

Local working memory for agent sessions (see AGENTS.md §3). Gitignored: this
file is not part of the public repo.

## Epics

All four epics shipped in v0.2.0 (2026-09-10): ambient gates (ADR 0019),
energy estimation (ADR 0020), learned centroids (ADR 0021, shadow-only), and
the planted-fact distillation eval (ADR 0022). The herd is fed one epic at a
time.

## Active milestone

None chartered. The README's Roadmap section is a stub waiting for the next
milestone.

## Open items

- Terminal garbles during model download in `init --setup`:
  [#198](https://github.com/Standard-Pentest/kultivait/issues/198). The PTY
  repro harness is embedded in the issue; it currently hangs against `main`.

## Recently landed (2026-09-10)

- Runtime consent card (8a77c58, spec
  `docs/superpowers/specs/2026-09-10-runtime-consent-design.md`): `init
  --setup` no longer starts an idle ollama on its own.
- Docs pass on branch `docs/human-eyes`: README consolidated into a pitch plus
  `docs/guides/`, indices brought current, STATE.md untracked.
