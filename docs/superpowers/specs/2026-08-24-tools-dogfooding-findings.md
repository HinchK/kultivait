# Live tool-agent dogfooding — findings

Date: 2026-08-24 · Map #61 ticket [#64](https://github.com/Standard-Pentest/kultivait/issues/64) · prototype evidence from live traffic through `kultivait serve` (:4114) with the registered OpenRouter api tiers.

## Environment

Agent-envelope traffic (client tool definitions in both dialects — the exact shape OpenCode/Cursor/Claude-Code send) against the live proxy; api targets registered per the bring-up ([#63](https://github.com/Standard-Pentest/kultivait/issues/63)): `anthropic/claude-sonnet-5`, `openai/gpt-4o`, `meta-llama/llama-3.3-70b-instruct`. Budget: **$0.20 of $10 spent** across the whole session.

## Verified end-to-end

1. **Tool passthrough under live REST targets — WORKS, after two real fixes.** Full round-trip: frontier-class tool prompt → routed to the tools-capable api tier → real `get_weather({"city":"Berlin"})` tool call returned to the client → tool result injected → second turn produced a final answer that weaves the result in ("21/sunny" used to pick the ops window). `finish_reason: tool_calls` semantics intact. **Zero `tools_unsupported` fallbacks** across every tool-bearing request; the ledger shows capability routing working (`no_backend` fallback from the virtual-classified tier down to the tools-capable api tier — the correct walk).
2. **Buffered relay under streaming — works.** SSE flows to the client with proxy-issued chunk ids (`kult-…`), emitted from the buffer after provider completion; tool-call deltas assemble per the index-keyed grammar. No truncated-content failure modes observed.
3. **Effort projection + per-model reasoning gate — WORKS, after one real fix.** Ledger records `canonical_effort: deep/balanced` on api dispatches; the OpenAI-dialect projection now emits `reasoning_effort` only for reasoning-capable models.

## Live bugs found & fixed during the run (the dogfooding yield)

1. **Reasoning params on non-reasoning models → provider 400.** First tool dispatch to `meta-llama/llama-3.3-70b-instruct` failed: the effort projection emitted `reasoning_effort`, which Google Vertex translates to a `thinking` field llama rejects ("thinking is not supported by this model"). Fix: `model_supports_reasoning()` gate (ADR 0008's per-model value subsets, now enforced); `gpt-4o` also correctly gated out (non-reasoning). The 400 was classified **non-retryable** and never hammered — the R-slice failure taxonomy held live (again).
2. **Tool plumbing stripped from CC-dialect history.** Second turns failed with "Expected input to contain field: 'tool_call_id'": the chat-completions path's history passed through `anthropic_messages_to_openai` (built for messages-dialect input), which dropped `tool_calls`/`tool_call_id` from already-OpenAI-shaped rows. Fix: CC-shaped rows pass through verbatim. 471 tests green after both fixes.

## Tollbooth on contested tool prompts — the honest finding

**The trolltoll never fired on live tool traffic — because the contested band is empty under the incumbent judge.** Every tool prompt ran the preprocessor (`preprocess_mark: ok`) and derived `frontier` (fits clustered high), routing straight to the api tier with the toll skipped. This is the #14 calibration weakness (fit clustering ≥ 0.85) confirmed **empirically on live tool traffic** — the strongest evidence yet for the distillation flywheel (Map #44): the judge, not the tollbooth, is the bottleneck. Tollbooth mechanics themselves remain hermetic-verified (26 tests + R5 integration); the headless auto-policy path (no presence → skip hold) behaved as designed.

## Capability filtering & mixed menus

Tool-bearing menus drop CLI targets by construction (R5); live traffic never presented a contested tool prompt to the tollbooth (see above), so the filtered menu was not rendered live this run. The capability walk in `_resolve_tier` (the live path tool requests actually took) selected tools-capable api tiers every time.

## Retry ladder

No organic provider hiccups occurred. The taxonomy's live evidence remains the #63 402 (non-retryable, no hammering) and this run's two 400s (non-retryable, correctly surfaced). A synthetic 429 was not forced — bounded spend prioritized real traffic over fault injection.

## What the evidence demands (input to [#67](https://github.com/Standard-Pentest/kultivait/issues/67))

1. The **judge calibration fix is the pipeline's next real work** — the distillation flywheel has a live-measured motive and a built pipeline (D1–D7) waiting on a teacher-viable corpus.
2. Per-model capability metadata (reasoning support) belongs in the curated provider table — the gate list worked, but a models-API-derived table beats pattern-matching.
3. Real agent-harness attachment (OpenCode via base-url env) remains untested live in this environment (nested-CLI constraints); the envelope-level traffic here is shape-identical to what agents send.
