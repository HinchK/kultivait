# Documentation Curation Manifest — 2026-09-03

**Parent Map**: [#150](https://github.com/Standard-Pentest/kultivait/issues/150) ("curate docs/ for the stranger and audit against reality")  
**Related Tickets**: [#151](https://github.com/Standard-Pentest/kultivait/issues/151) (docs curation audit), [#152](https://github.com/Standard-Pentest/kultivait/issues/152) (curation execution), [#153](https://github.com/Standard-Pentest/kultivait/issues/153) (curation manifest and indices)  
**Date**: 2026-09-03 / 2026-09-04  
**Auditor & Scribe**: `agy-docs` (DOCS WORKER)

This manifest records the comprehensive audit, triage, and curation of all 38 original documentation files in `docs/` and the root trio (`CONTEXT.md`, `AGENTS.md`, `CLAUDE.md`).

---

## 1. Original 38 Documentation Files Disposition

Every file under `docs/` was audited against running code in `src/kultivait/`, live tests, post-restructure `README.md`, and tracker history (`docs/research/2026-09-03-docs-curation-audit.md`).

**Summary Counts**:
- **keep-as-is**: 25 files
- **keep-fix-ref (fixed in #152)**: 6 files
- **annotated-historical**: 3 files (2 via in-file headers in #152; ADR 0004 via `docs/adr/README.md` in #153)
- **moved-to-internals**: 4 files (migrated to `../kultivait-internals/superpowers-plans/` in #152)
- **Total original files**: 38 files

### Full Disposition Table

| Original Path | Category | Disposition | Actions Taken / Notes |
|---|---|---|---|
| `docs/adr/0001-trolltoll-holds-requests.md` | ADR | keep-as-is | Verified in `server.py:150` (`toll_timeout_s = 60.0`). Historical cites intentional. |
| `docs/adr/0002-orchestration-fit-at-boundaries.md` | ADR | keep-as-is | In-band `kultivait_meta` verified in `server.py:451-462`. |
| `docs/adr/0003-route-menu-and-frontier-targets.md` | ADR | keep-as-is | Verified `tollbooth.py:44,154`; pricing in `config.py:36-38`. |
| `docs/adr/0004-api-frontier-surface.md` | ADR | annotated-historical | Decision shipped. Historical drift annotated in `docs/adr/README.md` (classes in `api_backends.py`; defaults are `claude-3-7-sonnet-20250219`/`gpt-4o`; prose kept untouched). |
| `docs/adr/0005-cost-model-duality.md` | ADR | keep-as-is | Notional vs metered cash verified in `ledger.py:22-42`; in-file cache amendment intact. |
| `docs/adr/0006-mixed-route-menu.md` | ADR | keep-as-is | Unified menu with tool filtering verified in `server.py:_resolve_tier`. |
| `docs/adr/0007-preprocessor-tool-treatment.md` | ADR | keep-as-is | Tool suppression verified in `server.py:283-284`; thresholds in `preprocessor.py:15`. |
| `docs/adr/0008-api-effort-projection.md` | ADR | keep-as-is | `model_supports_reasoning()` gate verified in `api_backends.py:298`. |
| `docs/adr/0009-benchmark-harness-shape.md` | ADR | keep-as-is | Direct-to-backend shape verified in `capability_eval.py`. |
| `docs/adr/0010-key-management-and-onboarding.md` | ADR | keep-as-is | 3-tier key resolution verified in `credentials.py:67-91`. |
| `docs/adr/0011-api-retry-and-failover.md` | ADR | keep-as-is | Buffered relay and retry ladder verified in `api_backends.py`. |
| `docs/adr/0012-distillation-targets.md` | ADR | keep-as-is | Single-call preprocessor contract distillation verified in `distill/`. |
| `docs/adr/0013-corpus-and-label-assembly.md` | ADR | keep-as-is | Gold/silver/bronze truth hierarchy and permanent held-out set verified in `corpus.py`. |
| `docs/adr/0014-training-method-and-hardware-budget.md` | ADR | keep-as-is | Apple Silicon QLoRA ladder verified in `trainer.py:26-54`. |
| `docs/adr/0015-distillation-eval-protocol.md` | ADR | keep-as-is | Five gates and band constants verified in `eval.py:30-33`. |
| `docs/adr/0016-teacher-selection-and-synthetic-policy.md` | ADR | keep-as-is | In-file 2026-08-24 amendment matches `generator.py:361` (`grok-4.6`). |
| `docs/adr/0017-distillate-deployment-and-shadow-rollout.md` | ADR | keep-as-is | `[distill]` config seat, async shadow pass, human cutover verified in `shadow.py`. |
| `docs/adr/0018-cache-breakpoints.md` | ADR | keep-as-is | Breakpoints, 1024 token minimum, and TTL multipliers verified in `api_backends.py:321,411`. |
| `docs/superpowers/plans/2026-07-04-copy-prompt-button.md` | Plan | move-to-internals | Feature shipped in `landing/`; moved to `../kultivait-internals/superpowers-plans/`. |
| `docs/superpowers/plans/2026-07-14-init-hardware-tuning.md` | Plan | move-to-internals | Feature shipped in `hardware.py`/`bootstrap.py`; moved to `../kultivait-internals/superpowers-plans/`. |
| `docs/superpowers/plans/2026-07-15-init-tui-polish.md` | Plan | move-to-internals | Feature shipped in `tui.py`; moved to `../kultivait-internals/superpowers-plans/`. |
| `docs/superpowers/plans/2026-08-21-magnitude-parity-setup.md` | Plan | move-to-internals | Feature shipped in `setup_state.py`/`setup_screen.py`; moved to `../kultivait-internals/superpowers-plans/`. |
| `docs/superpowers/specs/2026-07-03-copy-prompt-button-design.md` | Spec | keep-as-is | Accurate design for shipped landing CTA; clean, no stale refs. |
| `docs/superpowers/specs/2026-07-14-init-hardware-tuning-design.md` | Spec | keep-as-is | Shipped as designed; external research links live. |
| `docs/superpowers/specs/2026-07-15-init-tui-polish-design.md` | Spec | keep-fix-ref | Fixed in #152: replaced Obsidian wikilink `[[2026-07-14-init-hardware-tuning-design]]` with repo-relative link. |
| `docs/superpowers/specs/2026-08-21-magnitude-parity-setup-design.md` | Spec | keep-fix-ref | Fixed in #152: rewritten unresolvable `../../magnitude` sibling-clone paths to upstream repo URLs. |
| `docs/superpowers/specs/2026-08-21-preprocessor-routing-design.md` | Spec | annotated-historical | Annotated in #152: added historical header clarifying shipped `/v1/messages` tools and non-existence of `docs/API.md`/`[preprocess]`. |
| `docs/superpowers/specs/2026-08-23-distillation-pipeline-design.md` | Spec | annotated-historical | Annotated in #152: added historical header noting teacher row superseded by ADR 0016 amendment. |
| `docs/superpowers/specs/2026-08-23-rest-frontier-providers-design.md` | Spec | keep-fix-ref | Fixed in #152: updated backend module location pointer from `backends.py` to `api_backends.py`. |
| `docs/superpowers/specs/2026-08-24-tools-dogfooding-findings.md` | Spec | keep-as-is | Empirical dogfooding transcript analysis; references closed issues; code matches. |
| `docs/superpowers/specs/2026-08-25-prompt-caching-findings.md` | Spec | keep-fix-ref | Fixed in #152: fixed relative link depth to ADR 0018 (`../../adr/...`); annotated ephemeral `/tmp/cache-probe/` artifact. |
| `docs/superpowers/runbooks/2026-08-25-prompt-caching-runbook.md` | Runbook | keep-as-is | All operational instructions verified against `api_backends.py` and harvest output. |
| `docs/superpowers/runbooks/2026-09-02-zero-config-adoption-runbook.md` | Runbook | keep-fix-ref | Fixed in #152: removed broken link to non-existent ADR 0019; noted zero-config adoption shipped with runbook. |
| `docs/agents/domain.md` | Agent Doc | keep-as-is | Standard domain modeling conventions; stays public. |
| `docs/agents/issue-tracker.md` | Agent Doc | keep-as-is | Remote topology verified live (`origin` fork vs `upstream` canonical home). |
| `docs/agents/triage-labels.md` | Agent Doc | keep-fix-ref | Fixed in #152: reconciled label table to active repository labels (`ready-for-agent`, `wontfix`). |
| `docs/research/2026-09-03-public-claims-verification.md` | Research | keep-as-is | Dated research snapshot; preserved as historical audit record. |
| `docs/launch-checklist-2026-09-03.md` | Checklist | keep-as-is | Dated launch verification artifact for v0.1.0; all 6 axes verified green. |

---

## 2. Root Trio Fixes

The three root configuration files were audited and reconciled in ticket #152:

1. **`CONTEXT.md`**: Clean glossary; zero file reference errors; no changes needed.
2. **`AGENTS.md`**: Fixed 2 soft pointers in §3 (clarified that `docs/superpowers/specs/` exists, and specified `STATE.md` as create-if-absent).
3. **`CLAUDE.md`**: Fixed 3 stale references:
   - Line 36: Updated `/v1/messages` documentation to reflect that tool support has shipped (`tool_use` blocks, streaming and non-streaming).
   - Line 38: Corrected legacy `tool_fallback` metadata field name to live `fallback_reason`.
   - Line 55: Removed stale reference to deleted `HANDOFF.md`, pointing directly to `README.md`.

---

## 3. Post-Curation Additions

Five additions complete ticket #153 and close Wayfinder Map #150:

| Path | Purpose |
|---|---|
| `docs/README.md` | Complete documentation index grouping all 35 active files with descriptive one-liners and audience tags. |
| `docs/adr/README.md` | ADR index summarizing ADRs 0001–0018 with one-line gists and the ADR 0004 drift annotation. |
| `CONTRIBUTING.md` | Minimal contributor guide specifying canonical upstream home, `uv sync`, `uv run pytest -q` gate, Conventional Commits, and Python 3.12+ macOS target. |
| `docs/curation-manifest-2026-09-03.md` | This dated curation manifest documenting file dispositions, root trio fixes, and reproduction verification. |
| `docs/research/2026-09-03-docs-curation-audit.md` | Foundational audit and disposition register (created in #151). |

---

## 4. Verification & Reproduce Greps

### A. Tree Count Verification
Pre-addition tree count verified against the 35 remaining files (38 original - 4 moved plans + 1 audit register):
```bash
find docs -type f -name "*.md" | wc -l
# Result: 35
```

Following the addition of `docs/README.md`, `docs/adr/README.md`, and this manifest, the count is **38 markdown files** under `docs/`.

### B. Stale Reference Sweep
Checking for obsolete file references or phantom links across documentation:
```bash
grep -rn "scripts/herdr" docs/ || echo "Clean"
grep -rn "HANDOFF.md" docs/ || echo "Clean (historical citations in ADR 0001/0002 only)"
grep -rn "0019-zero-config" docs/ || echo "Clean"
grep -rn "kultivaite" docs/ || echo "Clean (historical quote in research register only)"
```

### C. Intentional Citation Exceptions
The following references are intentional and deliberately preserved:
1. **`docs/adr/0001-trolltoll-holds-requests.md` & `0002-orchestration-fit-at-boundaries.md`**: Cite `HANDOFF.md` / `TODO-AGY.md` as immutable historical context from the initial architecture brainstorming phase.
2. **`docs/research/2026-09-03-public-claims-verification.md`**: Quotes `Standard-Pentest/kultivaite` and notes `scripts/herdr-*` existence as an empirical record of the pre-cleanup codebase at the exact moment of the audit.
