# Documentation Index

This directory houses the design history, architectural decisions, operational runbooks, evaluation registers, and agent conventions for **kultivait**.

Documentation in kultivait serves developers exploring or extending the proxy, contributors integrating new tools, and autonomous agent workers maintaining system invariants. All design choices are recorded as immutable Architecture Decision Records (ADRs) or dated specifications.

---

## 1. Architecture Decision Records

Locked decisions that define system boundaries, cost models, and routing contracts. See [docs/adr/README.md](adr/README.md) for the complete index and decision summaries.

- [docs/adr/0001-trolltoll-holds-requests.md](adr/0001-trolltoll-holds-requests.md) — Trolltoll request holding mechanism (for developers & agent workers)
- [docs/adr/0002-orchestration-fit-at-boundaries.md](adr/0002-orchestration-fit-at-boundaries.md) — Boundary-level model and effort fitting (for agent developers)
- [docs/adr/0003-route-menu-and-frontier-targets.md](adr/0003-route-menu-and-frontier-targets.md) — Route menu ranking and auto-policy local default (for core developers)
- [docs/adr/0004-api-frontier-surface.md](adr/0004-api-frontier-surface.md) — Direct REST frontier provider backend architecture (for backend contributors)
- [docs/adr/0005-cost-model-duality.md](adr/0005-cost-model-duality.md) — Dual-lens accounting: metered cash vs notional savings (for financial/ledger maintainers)
- [docs/adr/0006-mixed-route-menu.md](adr/0006-mixed-route-menu.md) — Mixed CLI and API route menu candidates with tool filtering (for routing engineers)
- [docs/adr/0007-preprocessor-tool-treatment.md](adr/0007-preprocessor-tool-treatment.md) — Preprocessor handling for tool-bearing requests (for pipeline contributors)
- [docs/adr/0008-api-effort-projection.md](adr/0008-api-effort-projection.md) — Canonical reasoning effort projection across API backends (for API backend maintainers)
- [docs/adr/0009-benchmark-harness-shape.md](adr/0009-benchmark-harness-shape.md) — Direct-to-backend capability eval harness design (for evaluation developers)
- [docs/adr/0010-key-management-and-onboarding.md](adr/0010-key-management-and-onboarding.md) — Three-source credential hierarchy: env, keychain, file (for security and CLI developers)
- [docs/adr/0011-api-retry-and-failover.md](adr/0011-api-retry-and-failover.md) — Buffered streaming replay and retry ladder for API tiers (for networking/runtime maintainers)
- [docs/adr/0012-distillation-targets.md](adr/0012-distillation-targets.md) — Single-call preprocessor contract distillation targets (for ML fine-tuning engineers)
- [docs/adr/0013-corpus-and-label-assembly.md](adr/0013-corpus-and-label-assembly.md) — Serving-shape chat JSONL dataset and truth hierarchy (for ML dataset curators)
- [docs/adr/0014-training-method-and-hardware-budget.md](adr/0014-training-method-and-hardware-budget.md) — Apple Silicon QLoRA resource ladder via mlx-lm (for local training operators)
- [docs/adr/0015-distillation-eval-protocol.md](adr/0015-distillation-eval-protocol.md) — Five-gate distillation evaluation protocol (for model qualification evaluators)
- [docs/adr/0016-teacher-selection-and-synthetic-policy.md](adr/0016-teacher-selection-and-synthetic-policy.md) — Dual-teacher synthetic data generation and filtering (for data synthesis engineers)
- [docs/adr/0017-distillate-deployment-and-shadow-rollout.md](adr/0017-distillate-deployment-and-shadow-rollout.md) — Distillate shadow serving and human-in-the-loop cutover (for proxy operators)
- [docs/adr/0018-cache-breakpoints.md](adr/0018-cache-breakpoints.md) — Proxy-owned deterministic prompt cache breakpoints (for prompt caching maintainers)

---

## 2. Design Specs & Findings

Historical design blueprints and empirical findings documenting the implementation of major features.

- [docs/superpowers/specs/2026-07-03-copy-prompt-button-design.md](superpowers/specs/2026-07-03-copy-prompt-button-design.md) — Design spec for landing page copy-prompt CTA and start.md onboarding (for frontend developers)
- [docs/superpowers/specs/2026-07-14-init-hardware-tuning-design.md](superpowers/specs/2026-07-14-init-hardware-tuning-design.md) — Sizing algorithms and garden recommendation ladder for Apple Silicon (for hardware integration developers)
- [docs/superpowers/specs/2026-07-15-init-tui-polish-design.md](superpowers/specs/2026-07-15-init-tui-polish-design.md) — Rich-based visual setup screen and garden chooser design (for TUI developers)
- [docs/superpowers/specs/2026-08-21-magnitude-parity-setup-design.md](superpowers/specs/2026-08-21-magnitude-parity-setup-design.md) — State machine, cancellation safety, and download resumption for setup (for CLI setup engineers)
- [docs/superpowers/specs/2026-08-21-preprocessor-routing-design.md](superpowers/specs/2026-08-21-preprocessor-routing-design.md) — Spec for preprocessor routing, hybrid menus, and sub-task extraction *(historical record; for routing architecture researchers)*
- [docs/superpowers/specs/2026-08-23-distillation-pipeline-design.md](superpowers/specs/2026-08-23-distillation-pipeline-design.md) — Pipeline design for synthetic generation, MLX training, and Ollama export *(historical record; for distillation researchers)*
- [docs/superpowers/specs/2026-08-23-rest-frontier-providers-design.md](superpowers/specs/2026-08-23-rest-frontier-providers-design.md) — Design specification for direct REST frontier provider integrations (for backend engineers)
- [docs/superpowers/specs/2026-08-24-tools-dogfooding-findings.md](superpowers/specs/2026-08-24-tools-dogfooding-findings.md) — Empirical dogfooding transcript analysis of streaming tool calling (for agent harness integrators)
- [docs/superpowers/specs/2026-08-25-prompt-caching-findings.md](superpowers/specs/2026-08-25-prompt-caching-findings.md) — Cache amortization measurements and TTL cohort behavior (for performance evaluators)

---

## 3. Operational Runbooks

Step-by-step procedures for operating and troubleshooting runtime proxy features.

- [docs/superpowers/runbooks/2026-08-25-prompt-caching-runbook.md](superpowers/runbooks/2026-08-25-prompt-caching-runbook.md) — Operational guide for configuring and verifying prompt caching and TTLs (for proxy operators)
- [docs/superpowers/runbooks/2026-09-02-zero-config-adoption-runbook.md](superpowers/runbooks/2026-09-02-zero-config-adoption-runbook.md) — Runbook for process wrapping, shell hooks, IDE patching, and loopback rules (for developers adopting kultivait)

---

## 4. Research Registers

Verified empirical snapshots validating public documentation claims against running code.

- [docs/research/2026-09-03-public-claims-verification.md](research/2026-09-03-public-claims-verification.md) — Audit register verifying claims in public docs against repository code (for release auditors)
- [docs/research/2026-09-03-docs-curation-audit.md](research/2026-09-03-docs-curation-audit.md) — Comprehensive audit and disposition register of all repository documentation (for documentation maintainers)

---

## 5. Launch Checklist

Release readiness checklists and verification runs.

- [docs/launch-checklist-2026-09-03.md](launch-checklist-2026-09-03.md) — Six-axis launch qualification record for v0.1.0 release (for release managers)
- [docs/curation-manifest-2026-09-03.md](curation-manifest-2026-09-03.md) — Dated record of this tree's curation: every file's disposition and the reproduce greps (for maintainers)

---

## 6. Agent Conventions

Conventions and operational protocols for automated agent workers and herd members.

- [docs/agents/domain.md](agents/domain.md) — Single-context domain modeling guidelines and CONTEXT.md conventions (for agent herd developers)
- [docs/agents/issue-tracker.md](agents/issue-tracker.md) — GitHub issue tracker conventions, remote topology, and wayfinding protocols (for herd loopers and task workers)
- [docs/agents/triage-labels.md](agents/triage-labels.md) — Canonical GitHub issue triage labels and categorization rules (for triage operators)
