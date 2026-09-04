# Docs curation audit — every docs/ file against reality

Research ticket: [#151](https://github.com/Standard-Pentest/kultivait/issues/151) · parent map: [#150](https://github.com/Standard-Pentest/kultivait/issues/150)
Date: 2026-09-03 · Branch: `research/docs-curation-audit` · Method: full read of all 38 docs/ files (18 ADRs, 4 plans, 2 runbooks, 9 specs, 3 agents docs, research register, launch checklist) against `src/kultivait/` (read + grep), post-restructure `README.md`, live issue tracker (`gh`), and repo history; quick stale-ref audit of the root trio (`CONTEXT.md`, `AGENTS.md`, `CLAUDE.md`). No files modified outside this artifact; no pytest run (research only).

**Headline counts: 25 keep-as-is · 6 keep-fix-ref · 3 annotated-historical · 4 move-to-internals (= 38).**

- **Copy-prompt-button verdict: SHIPPED** (landing pair accurate; see (c)).
- **ADR supersession verdict: NO** cross-ADR pairs; two intra-file amendments carry their own trail (see (d)).
- **Stale-ref inventory: 15 entries** (11 under docs/, 4 in the root trio) beyond the intentional historical citations.

---

## (a) DISPOSITION REGISTER

| Path | Disposition | Evidence / notes |
|---|---|---|
| docs/adr/0001-trolltoll-holds-requests.md | keep-as-is | `toll_timeout_s = 60.0` (`server.py:150`); headless arm, pending queue, auto-policy all in `server.py`/`tollbooth.py`. `HANDOFF.md:107-113` cite is intentional historical citation (per ticket). |
| docs/adr/0002-orchestration-fit-at-boundaries.md | keep-as-is | `kultivait_meta` in-band channel shipped (`server.py:451-462`); orchestration-at-boundaries is the live shape. `HANDOFF.md`/`TODO-AGY.md` cites intentional. Minor: predicted `orchestrator`/`worker` ledger fields never landed under those names (see (c)). |
| docs/adr/0003-route-menu-and-frontier-targets.md | keep-as-is | `build_route_menu` (`tollbooth.py:44`), `resolve_auto_policy` (`tollbooth.py:154`); codex (1.25, 10.0) / opencode (3.0, 15.0) verified in `config.py:36-38` incl. the multi-provider caveat. |
| docs/adr/0004-api-frontier-surface.md | annotated-historical | Decision shipped intact (three standalone classes, manual `[[tiers]]`, pinned ids), but two cited details drifted: classes live in `api_backends.py` (`:520,:793,:1055`), not `backends.py` as cited; curated defaults shipped as claude-3-7-sonnet-20250219 / gpt-4o (`config.py:81-103`), not the "sonnet-5-class, terra-class" the prose names. Per map, ADR prose stays untouched — annotation rides the ADR index. |
| docs/adr/0005-cost-model-duality.md | keep-as-is | `notional_usd`/metered split verified (`ledger.py:22-42`); 2026-08-25 cache amendment is in-file and matches `api_backends.py:411-412` + harvest cache section. |
| docs/adr/0006-mixed-route-menu.md | keep-as-is | Capability filter + local-first auto-policy shipped (`server.py` `_resolve_tier`; register #26/#36 verified). |
| docs/adr/0007-preprocessor-tool-treatment.md | keep-as-is | Suppression shipped verbatim — `server.py:283-284` cites this ADR in-code; `VERDICT_THRESHOLDS = (0.65, 0.85)` (`preprocessor.py:15`). |
| docs/adr/0008-api-effort-projection.md | keep-as-is | `model_supports_reasoning()` gate exists (`api_backends.py:298`, added per dogfooding fix); per-provider projection in `api_backends.py`. |
| docs/adr/0009-benchmark-harness-shape.md | keep-as-is | `capability_eval.py` exists; direct-to-backend, accuracy-only shape matches. |
| docs/adr/0010-key-management-and-onboarding.md | keep-as-is | env→keychain→credentials.toml precedence verified (`credentials.py:67-91`; register #32). |
| docs/adr/0011-api-retry-and-failover.md | keep-as-is | Buffered relay + retry ladder shipped (register #23/#25 live-verified streaming behavior); map-#25 revision recorded in-file. |
| docs/adr/0012-distillation-targets.md | keep-as-is | Whole-contract distill shipped (`distill/`); note only: the `preprocess_model` swap wording was later refined by ADR 0017's `[distill]` seat (refinement, not supersession — see (d)). |
| docs/adr/0013-corpus-and-label-assembly.md | keep-as-is | Gold/silver/bronze + permanent held-out verified (`corpus.py`, register #39). |
| docs/adr/0014-training-method-and-hardware-budget.md | keep-as-is | Resource ladder exactly as written (`trainer.py:26-54`; register #41). |
| docs/adr/0015-distillation-eval-protocol.md | keep-as-is | Five gates + band discipline constants (`eval.py:30-33`; register #42). |
| docs/adr/0016-teacher-selection-and-synthetic-policy.md | keep-as-is | 2026-08-24 amendment in-file and matches code (`generator.py:361` grok-4.6 via OpenRouter). |
| docs/adr/0017-distillate-deployment-and-shadow-rollout.md | keep-as-is | `[distill]` seat (`config.py:123-124,261-265`), shadow pass, 90/30 human cutover (`shadow.py`; register #44). |
| docs/adr/0018-cache-breakpoints.md | keep-as-is | `MIN_CACHE_PREFIX_TOKENS = 1024` (`api_backends.py:321`), dual-level placement, `session_id` forward (`:402-403`), TTL multipliers (`:411-412`). |
| docs/superpowers/plans/2026-07-04-copy-prompt-button.md | move-to-internals | Feature SHIPPED (see (c)); the plan itself is a checkbox task-list herd working artifact (branch names, commit messages, verification steps) — internal workflow per map's plans-relocation decision, not an unshipped-feature case. |
| docs/superpowers/plans/2026-07-14-init-hardware-tuning.md | move-to-internals | Feature shipped (`hardware.py`, `bootstrap.py`, `tests/test_hardware.py`); plan = internal working artifact. |
| docs/superpowers/plans/2026-07-15-init-tui-polish.md | move-to-internals | Feature shipped (`tui.py`, rich in deps); plan = internal working artifact. |
| docs/superpowers/plans/2026-08-21-magnitude-parity-setup.md | move-to-internals | Feature shipped (`setup_state.py`, `setup_screen.py`, `onboarding.py`, `keys.py`); plan = internal working artifact. |
| docs/superpowers/specs/2026-07-03-copy-prompt-button-design.md | keep-as-is | Describes the shipped landing CTA accurately (see (c)); self-contained, stranger-legible, no stale refs. |
| docs/superpowers/specs/2026-07-14-init-hardware-tuning-design.md | keep-as-is | Shipped as designed; external research links live; dated provenance (branch line) is honest history. |
| docs/superpowers/specs/2026-07-15-init-tui-polish-design.md | keep-fix-ref | `:9` Obsidian wikilink `[[2026-07-14-init-hardware-tuning-design]]` renders dead on GitHub — reword to a repo-relative link. |
| docs/superpowers/specs/2026-08-21-magnitude-parity-setup-design.md | keep-fix-ref | `:5-8` references sibling clone `../../magnitude` and `magnitude/...` doc paths — unresolvable outside the original dev machine; reword to the upstream repo URLs. |
| docs/superpowers/specs/2026-08-21-preprocessor-routing-design.md | annotated-historical | Map-#4 register of a shipped architecture, but the tail drifted: `:267` lists "/v1/messages tool calling support (tracked separately under BACKLOG F4)" as out-of-scope — BACKLOG.md was removed (#134) **and** the feature shipped (`server.py:754-861`; current README:149-151 documents it); `:260` points at `docs/API.md` and `[preprocess]`/`[effort]` config sections that were never created (`config.py` has neither). Historical header + those two lines reconcile at execution time. |
| docs/superpowers/specs/2026-08-23-distillation-pipeline-design.md | annotated-historical | Pipeline shipped (`distill/` modules, register #39-#44), but the #50 teacher row ("Judge teacher = GLM via opencode CLI") was superseded by ADR 0016's 2026-08-24 amendment: local vary model drafts, neutral API teacher (x-ai/grok-4.6 via OpenRouter) labels — code truth at `generator.py:353-388`, `cli.py:1385-1389`. Spec table was never amended. |
| docs/superpowers/specs/2026-08-23-rest-frontier-providers-design.md | keep-fix-ref | Shipped and verified end-to-end (register #30-#35); `:62` architecture block cites "backends.py — OpenAIBackend / AnthropicBackend / OpenRouterBackend" — classes live in `api_backends.py` (`:520,:793,:1055`). Fix the module pointer. |
| docs/superpowers/specs/2026-08-24-tools-dogfooding-findings.md | keep-as-is | Dated live-probe record; referenced issues #63/#64/#67 all exist and are closed; no broken paths; both in-run fixes verifiable in code (`model_supports_reasoning`, `api_backends.py:298`). |
| docs/superpowers/specs/2026-08-25-prompt-caching-findings.md | keep-fix-ref | `:12` links ADR 0018 as `docs/adr/0018-cache-breakpoints.md` — repo-root path, broken from the file's depth (should be `../../adr/...`); `:5` points at ephemeral `/tmp/cache-probe/summary.json`. |
| docs/superpowers/runbooks/2026-08-25-prompt-caching-runbook.md | keep-as-is | Every operational claim verified: 1,024-token floor (`api_backends.py:321`), `cache_ttl` 5m/1h multipliers (`:411-412`), harvest cache block format (register #34 "line-for-line identical"), ledger fields. |
| docs/superpowers/runbooks/2026-09-02-zero-config-adoption-runbook.md | keep-fix-ref | Operationally accurate (`run --host/--port` exist `cli.py:1420-1421`; `PROXY_ENV_STRIP` at `backends.py:21,479`), **but** `:5` links `../../adr/0019-zero-config-adoption.md` — ADR 0019 does not exist (docs/adr/ stops at 0018); the hook feature shipped without its ADR. Drop or de-link the reference. |
| docs/agents/domain.md | keep-as-is | Generic convention doc; `CONTEXT-MAP.md` mention is existence-guarded; stays public per map. |
| docs/agents/issue-tracker.md | keep-as-is | Remote topology verified live: `origin` = HinchK/kultivait (fork, issues disabled), `upstream` = Standard-Pentest/kultivait. |
| docs/agents/triage-labels.md | keep-fix-ref | `:7-9` table claims tracker labels `needs-triage`, `needs-info`, `ready-for-human` — none exist on the tracker (live label list has only `ready-for-agent` + `wontfix` of the five). Reconcile the right-hand column. |
| docs/research/2026-09-03-public-claims-verification.md | keep-as-is | Dated research snapshot: its README:NNN citations, the `scripts/herdr-*` existence note (`:98`), and the kultivaite typo quotes describe the pre-#134/pre-#138 tree by design. Read as-of its commit; do not renumber (renumbering would falsify the record). The typo quote is an intentional citation per ticket; the `scripts/herdr-*` line is flagged in (b) for awareness only. |
| docs/launch-checklist-2026-09-03.md | keep-as-is | Dated one-time all-green artifact; its fresh-clone surface list matches the current tree exactly (incl. `vercel.json`, no `scripts/`); referenced #133-#141 all closed. |

### Root trio (stay public per map; stale refs for the execution ticket)

| Path | Verdict | Notes |
|---|---|---|
| CONTEXT.md | clean | Pure glossary, zero file references, no drift found. |
| AGENTS.md | 2 soft stale refs | §3 points at `STATE.md` and `docs/spec.md` as conventions — neither exists in the repo (aspirational pointers, not citations of moved files). |
| CLAUDE.md | 3 stale refs | `:36` "no tool support yet" for `/v1/messages` — FALSE since the messages-dialect tools landed (`server.py:754-861`; README:149-151 now documents tool support); `:38` `tool_fallback` — legacy field name, actual key is `fallback_reason` (`server.py:481-498`); `:55` "per README/HANDOFF" — HANDOFF.md was removed in #134. |

---

## (b) STALE-REF INVENTORY (file:line, beyond intentional citations)

1. `docs/superpowers/runbooks/2026-09-02-zero-config-adoption-runbook.md:5` — link to `docs/adr/0019-zero-config-adoption.md`; ADR 0019 never written (tree has 0001-0018 only).
2. `docs/superpowers/specs/2026-08-25-prompt-caching-findings.md:12` — ADR 0018 linked with repo-root path `docs/adr/…` from `docs/superpowers/specs/` depth (broken relative link).
3. `docs/superpowers/specs/2026-08-25-prompt-caching-findings.md:5` — artifact pointer `/tmp/cache-probe/summary.json` (ephemeral, gone).
4. `docs/superpowers/specs/2026-08-21-preprocessor-routing-design.md:267` — "BACKLOG F4" (BACKLOG.md removed in #134; the item itself shipped).
5. `docs/superpowers/specs/2026-08-21-preprocessor-routing-design.md:260` — `docs/API.md` and `[preprocess]`/`[effort]` config sections referenced as follow-ups; none exist (`docs/API.md` absent; `config.py` has neither section).
6. `docs/superpowers/specs/2026-07-15-init-tui-polish-design.md:9` — `[[2026-07-14-init-hardware-tuning-design]]` Obsidian wikilink; dead on GitHub render.
7. `docs/superpowers/specs/2026-08-21-magnitude-parity-setup-design.md:5-8` — `../../magnitude` sibling clone + `magnitude/design/...`, `magnitude/packages/...` paths; unresolvable outside the original machine.
8. `docs/superpowers/specs/2026-08-23-rest-frontier-providers-design.md:62` — API backend classes located in "backends.py"; actual module `src/kultivait/api_backends.py`.
9. `docs/adr/0004-api-frontier-surface.md:3` — same module drift (backends.py) plus "sonnet-5-class, terra-class" curated defaults vs shipped `PROVIDER_DEFAULTS` = claude-3-7-sonnet-20250219 / gpt-4o (`config.py:81-103`). ADR prose untouched per map — carry in the ADR index.
10. `docs/agents/triage-labels.md:7-9` — labels `needs-triage` / `needs-info` / `ready-for-human` claimed for this tracker; absent (live: `ready-for-agent`, `wontfix` only).
11. `docs/research/2026-09-03-public-claims-verification.md:98` — "`scripts/herdr-kultivait-session.sh` + `scripts/herdr-briefs/` exist"; true at research time, removed by #134 (launch checklist §3 confirms). Awareness flag only — dated snapshot, do not edit.
12. `CLAUDE.md:36` — "/v1/messages (Anthropic-compatible, no tool support yet)"; tools shipped (`server.py:754-861`).
13. `CLAUDE.md:38` — `tool_fallback` field name; actual `fallback_reason`.
14. `CLAUDE.md:55` — "per README/HANDOFF"; HANDOFF.md removed in #134.
15. `AGENTS.md` §3 — `STATE.md` / `docs/spec.md` convention pointers; neither file exists.

---

## (c) MISMATCH EVIDENCE (annotated-historical + move-to-internals proof)

**Copy-prompt-button plan/spec pair — SHIPPED, accurate:**
- `landing/index.html:540` and `:826` — both `data-copy-prompt` hero + final-CTA buttons present with the exact prompt text; matching `.prompt-copy*` CSS at `:168-184`; dedicated `[data-copy-prompt]` JS handler present (3rd grep hit).
- `landing/start.md` exists in the tree, content matches the plan's Task-1 spec verbatim; every command it shows appears in the current README.
- The register's (b)#2 "dead starter-prompt URL" finding is a **deploy** gap (kultivait.ai not serving the tree's landing; `/start.md` 404 until the vercel deploy runs — launch checklist §5 records this as a known deferred truth gap), not missing code. No dedicated tracker issue exists for the feature ("copy prompt" search → no hit); it landed with the landing work.
- Drift: cosmetic line-number shifts only (buttons now at :540/:826 vs plan's :517/:793 expectations after the #139 landing sync). Disposition: spec keep-as-is, plan → internals as a working artifact.

**Annotated-historical calls:**
1. `docs/adr/0004-api-frontier-surface.md` — decision shipped, details drifted: (i) classes cited "in src/kultivait/backends.py" actually live in `src/kultivait/api_backends.py:520,793,1055` (post-decision module split); (ii) curated defaults table prose says "sonnet-5-class, terra-class, and OpenRouter equivalents" — shipped `PROVIDER_DEFAULTS` (`config.py:81-103`) pins `claude-3-7-sonnet-20250219` ($3/$15), `gpt-4o` ($2.5/$10), `anthropic/claude-3.7-sonnet` ($3/$15). Annotation rides the ADR index; prose untouched per map.
2. `docs/superpowers/specs/2026-08-21-preprocessor-routing-design.md` — shipped map-#4 register with drifted tail: `:267` names Anthropic `/v1/messages` tool support as out-of-scope under removed-file tracker "BACKLOG F4", but the support shipped (`server.py:754-799` streaming, `:842-861` non-streaming; current README:149-151 advertises it; register (b)#4 called the identical README claim FALSE for the same reason); `:260` cites never-created `docs/API.md` + `[preprocess]`/`[effort]` sections.
3. `docs/superpowers/specs/2026-08-23-distillation-pipeline-design.md` — shipped pipeline with one superseded row: #50 teacher description ("GLM via opencode CLI" judge; variations from the judge) was replaced next day by ADR 0016's 2026-08-24 amendment (local vary model drafts variations — `qwen3:14b` default, `cli.py:1388-1389`; neutral API judge labels — `x-ai/grok-4.6` via OpenRouter, `generator.py:361`, `cli.py:1385-1387`; opencode remains only the no-arg fallback). Current README:433-439 documents the amended shape.

**Move-to-internals calls (all four plans describe SHIPPED features — the internal-workflow clause applies, not unshipped):**
- `2026-07-04-copy-prompt-button.md` → shipped in `landing/` (evidence above).
- `2026-07-14-init-hardware-tuning.md` → `src/kultivait/hardware.py`, `bootstrap.py`, `tests/test_hardware.py`, `tests/test_bootstrap.py` all present; README "Setup deep-dive" documents the flow.
- `2026-07-15-init-tui-polish.md` → `src/kultivait/tui.py`, `tests/test_tui.py` present; `rich>=13.0.0` in pyproject deps.
- `2026-08-21-magnitude-parity-setup.md` → `setup_state.py`, `setup_screen.py`, `onboarding.py`, `tests/test_setup_screen.py`, `tests/test_setup_state.py`, `tests/test_onboarding.py` present; README:52-63 documents the screen, Esc-skip, `onboarding.json`, `--setup` re-entry.
No unshipped-feature docs were found anywhere in docs/ — every feature described has code, tests, or tracker-closed evidence.

**Minor note (no disposition change):** ADR 0002's consequence line "ledger records will capture `orchestrator` and `worker` metadata fields" never landed under those names — the only `orchestrator` tag in src is the teacher-dispatch provenance in `distill/generator.py:248`; routing entries carry `subtask_candidates_count` + `kultivait_meta` instead (`server.py:446-462`). Forward-looking consequence wording; the decision itself is intact.

---

## (d) ADR SUPERSESSION

**No.** No ADR reverses or absorbs another; no superseded-by trail is needed (resolves map #150's open fog item).

- Two **intra-file amendments** carry their own trail in prose: ADR 0005 (2026-08-25, cache-aware accounting extension) and ADR 0016 (2026-08-24, three-way teacher split superseding its own original CLI-teacher choice).
- Closest cross-ADR relationships are explicit extensions/refinements, not supersessions: ADR 0006 grows ADR 0003's menu while stating the total order is unchanged; ADR 0017 refines ADR 0012's deployment surface (`preprocess_model` swap → `[distill]` config seat, resolved per-call — the ledger field name `preprocess_model` survived, `server.py:206`); ADR 0011 revises a map-#25 note, not an ADR; ADR 0009 redistributes a pre-ADR chart premise.
- The one superseded *prose* anywhere is ADR 0016's original teacher paragraph — inside the same file as its amendment.

---

## (e) HEADLINE COUNTS

| Disposition | Count | Files |
|---|---|---|
| keep-as-is | 25 | ADRs 0001-0003, 0005-0018 (17); specs copy-prompt-button, init-hardware-tuning, tools-dogfooding (3); runbook prompt-caching (1); agents domain.md, issue-tracker.md (2); research register (1); launch checklist (1) |
| keep-fix-ref | 6 | specs init-tui-polish (wikilink), magnitude-parity (sibling-clone refs), rest-frontier (api_backends.py pointer), prompt-caching-findings (relpath + /tmp artifact); runbook zero-config-adoption (ADR 0019 link); agents triage-labels (missing labels) |
| annotated-historical | 3 | ADR 0004 (module + defaults-table drift — index note, prose untouched); spec preprocessor-routing (BACKLOG F4 + shipped /v1/messages tools + docs/API.md); spec distillation-pipeline (teacher row vs ADR 0016 amendment) |
| move-to-internals | 4 | all four superpowers plans (internal herd working artifacts; every underlying feature shipped) |

Plus root trio: CONTEXT.md clean; CLAUDE.md 3 stale refs; AGENTS.md 2 soft pointers — both stay public per map, fixes ride the execution ticket (#152).

Issue-tracker cross-check: every issue cited by any audited doc (#4-#14, #25-#35, #44-#52, #61, #63, #64, #67, #74, #75, #77, #78, #85, #132-#141) exists and is CLOSED — no spec cites a phantom or still-open ticket.
