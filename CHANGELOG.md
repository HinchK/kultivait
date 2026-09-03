# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-09-03

First public release.

### Added

- Local-first LLM routing proxy: every prompt embedded locally
  (`nomic-embed-text`, milliseconds) and routed to the cheapest model that
  can carry it — simple / reasoning / docs / architect tiers, thin-margin
  escalation one tier up.
- OpenAI-compatible (`/v1/chat/completions`) and Anthropic-compatible
  (`/v1/messages`) endpoints; streaming and tool support on both.
- Savings ledger (`~/.kultivait/ledger.jsonl`) with `kultivait harvest`
  and a real-time dashboard; metered cash, notional value, and
  kept-via-cache tracked as orthogonal lines.
- Zero-config adoption: `kultivait run --` process wrapper, `hook shell`
  (sh/bash/zsh/fish), `hook ide` (Cursor/VS Code/Windsurf), review-only
  `hook loopback` generation.
- Local-only mode as a first-class citizen: cloud-worthy prompts
  recognized, served by the best local model, archived as escalations with
  `--brief` paste-ready distillation.
- Phase-gate pruning (`kultivait prune`, `POST /gate`) with the full
  transcript composted as the escape hatch.
- Interactive setup screen with zero-to-local bootstrap on Apple Silicon:
  garden chooser tuned to RAM, SHA256-verified GGUF downloads, ollama or
  llama.cpp router mode.
- Direct REST API frontier providers (anthropic / openai / openrouter):
  env > keychain > credentials-file key resolution, proxy-owned prompt
  caching with dual-level breakpoints and TTL knobs.
- Distillation pipeline (`distill corpus/generate/train/eval/export`),
  shadow serving with ADR-0017 cutover readiness, human-gated cutover
  with instant rollback.
- Routing validated first: 24/24 held-out accuracy, zero dangerous
  misroutes (`experiments/routing_trust.py`).

### Removed

- All telemetry. The build makes zero outbound telemetry calls; the
  ledger, classification, and serving stay on your machine.

### Verified

- Launch checklist (gate run, telemetry-free build, clean public root,
  canonical links, reproduced claims, secrets sweep) recorded at
  `docs/launch-checklist-2026-09-03.md`.

[0.1.0]: https://github.com/Standard-Pentest/kultivait/releases/tag/v0.1.0
