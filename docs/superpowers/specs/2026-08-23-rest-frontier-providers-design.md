# Direct REST frontier providers & tool-calling passthrough — design

Date: 2026-08-23
Branch: main (wayfinder map #25)
Status: approved via wayfinder map #25 (issues #26–#35); prototype validated (#32)

## Problem

Kultivait's frontier surface is CLI-only: every frontier dispatch shells out to an installed CLI (`CLIBackend`), which runs its own internal tool loop and **cannot accept client tool definitions** (`supports_tools = False`). Autonomous agent harnesses — OpenCode, Cursor, Claude Code — pass `tools: [...]` on every request, so `_resolve_tier` silently downgrades every tool-bearing frontier-worthy prompt to the local tier (`fallback_reason: "tools_unsupported"`), archiving escalations that can never be served. Dogfooding confirmed the cost: tool agent traffic is exactly where local models fumble (20k+ token loops), and exactly where frontier quality is most wanted. Additionally, CLI dispatches are priced **notionally** (`CLI_PRICING` rough defaults) with no metered-cash lane, so a real pay-per-token bill and a subscription-covered dispatch are indistinguishable in the ledger and harvest.

## Goal

Extend kultivait with **direct REST API frontier provider backends** carrying **full client tool-calling passthrough**:

1. Three providers — **Anthropic direct, OpenAI direct, OpenRouter** — as standalone `Backend`-conformant classes with per-dialect SSE normalizers, dissolving the `tools_unsupported` gate for tool agents while keeping the client's agent loop the orchestrator (ADR 0002).
2. **Mixed route menus** under ADR 0003's unchanged total order over a grown candidate pool (CLI ∪ served api-kind tiers), with a **capability filter** for tool-bearing requests, presence-probe-verified candidacy, and local-first capability-aware auto-policy.
3. **Dual-track cost accounting** — metered cash vs notional value — through the ledger, a two-lens harvest, and uniform-notional tollbooth display with cash annotations.
4. A **capability eval harness**: identical tool-loop tasks dispatched directly to backends, cross-family model-judged, accuracy-only — the evidence base for local-first tool auto-policy.

## Decisions made

| Decision / Issue | Choice | Artifact / ADR |
|---|---|---|
| [#26 REST capability matrix](https://github.com/Standard-Pentest/kultivait/issues/26) | Both dialects tool-passthrough-capable with a bounded translation matrix; effort knobs converge on ordinals (`reasoning_effort` ↔ `output_config.effort`; manual `budget_tokens` dead on Claude 4.7+); OpenRouter speaks both kultivait dialects natively and alone returns per-response USD `usage.cost`; Responses API not required | `experiments/rest-capability-matrix.md` (branch `research/rest-capability-matrix`) |
| [#27 API frontier surface](https://github.com/Standard-Pentest/kultivait/issues/27) | All three providers in v1, phased OpenRouter (wedge) → Anthropic → OpenAI; three standalone Backend-conformant classes, per-dialect SSE normalizers, shared pure helpers (no inheritance); manual `[[tiers]]` registration with `kind = "api"` (no detect() integration); **registered = tier present, served = key resolvable at construction**; model ids pinned exact with curated copy-ready defaults; unpriced api tiers load a conservative default with a warning | [ADR 0004](../../adr/0004-api-frontier-surface.md) |
| [#28 Cost model duality](https://github.com/Standard-Pentest/kultivait/issues/28) | Dual-track ledger: `cost_usd` redefined as **metered cash** (API real spend; CLI/local $0), additive **`notional_usd`** at the target's own prices; lossless legacy migration (notional defaults to old cost_usd); baseline = one declared **reference price** (default flat $3/$15, config-pinnable); harvest prints baseline / notional spent / cash out / kept-in-pocket = baseline − notional; tollbooth uniform notional primary + per-kind cash annotation, ranking untouched | [ADR 0005](../../adr/0005-cost-model-duality.md) |
| [#29 Mixed route menu](https://github.com/Standard-Pentest/kultivait/issues/29) | ADR 0003's total order kept (fit desc → task_type capability match → notional price asc → target id) over CLI ∪ served api-kind tiers — cash never ranks; **capability filter** drops CLI targets on tool-bearing requests (menus may shrink; no toll fires when local alone serves); auto-policy local-first capability-aware, top-ranked capability-filtered API target on local inability, fail-fast when nothing capable; escalations archive **unserved worthiness** only | [ADR 0006](../../adr/0006-mixed-route-menu.md) |
| [#30 Preprocessor tool treatment](https://github.com/Standard-Pentest/kultivait/issues/30) | Contested requests preprocess unconditionally — no capability gating, prompt surface unchanged (last-user-message only, no tool digest, CLI-only judge enum; API options rank via the total order's tail keys at fit 0.0); thresholds **[0.65, 0.85) finalized** for all traffic; **sub-task candidates suppressed on tool-bearing requests** (server-side emptying; channel survives for compound non-tool prompts) | [ADR 0007](../../adr/0007-preprocessor-tool-treatment.md) |
| [#31 Effort projection](https://github.com/Standard-Pentest/kultivait/issues/31) | Canonical effort stays the only shared currency; API backends **self-project** per-provider divergent tables (OpenAI `reasoning_effort` deep→xhigh; Anthropic `output_config.effort` deep→high, xhigh never auto-projected; OpenRouter mirrors OpenAI; `:thinking` suffix rejected); **fixed per-model token table** alongside curated pricing (client value passthrough never lowered; raised to effort headroom); effort **sticky per (fingerprint, target) pair** | [ADR 0008](../../adr/0008-api-effort-projection.md) |
| [#33 Benchmark harness shape](https://github.com/Standard-Pentest/kultivait/issues/33) | Redefined as a **capability eval**: identical tool-loop tasks dispatched **directly to backends** (bypassing routing), accuracy-only (savings stay the harvest's lane); ground truth by **model-as-judge, cross-family** (judge ≠ target's provider family; versioned rubric; archived transcripts); router-side tool-traffic accuracy consciously unvalidated | [ADR 0009](../../adr/0009-benchmark-harness-shape.md) |
| [#34 Key management](https://github.com/Standard-Pentest/kultivait/issues/34) | Hierarchy **env → OS keychain (first-class v1; macOS `security`, service `kultivait`) → `~/.kultivait/credentials.toml`** (0600); keys never in config.toml; serving = hierarchy resolvability; **route-menu candidacy = live presence probe per provider at menu build** (concurrent, fail-fast; failures drop targets like missing binaries; outcomes ride toll metadata); no keys CLI, no validation state — onboarding is documentation with copy-ready examples; key material never displayed | [ADR 0010](../../adr/0010-key-management-and-onboarding.md) |
| [#35 Retry & failover](https://github.com/Standard-Pentest/kultivait/issues/35) | **Aggressive same-target retry** (≤5 attempts, jittered exponential backoff, provider Retry-After headers honored, ~120s total budget; non-retryable 4xx fails fast) made safe by **buffered relay** (proxy buffers the provider stream fully before relaying — mid-stream failures become clean pre-stream errors; TTFT-at-proxy price consciously accepted); failover **presence-gated**: headless dispatches fail fast with dialect-native errors; **human toll picks fail over unbounded** across the registered-and-capable ranking (capability filter holds); full hop telemetry | [ADR 0011](../../adr/0011-api-retry-and-failover.md) |
| [#32 Tools passthrough probe](https://github.com/Standard-Pentest/kultivait/issues/32) | Prototype PASS both legs: CC↔Anthropic grammar (`input_json_delta` assembly) and messages↔OpenAI grammar (index-keyed `delta.tool_calls` assembly), tool-result injection, second-turn completion; hermetic fixtures via `httpx.MockTransport`, `--live` ready; the validated translation/assembly code is the seed for the streaming cores | branch `prototype/tools-passthrough-probe` (commit `aaafe3f`) |

## Research & empirical findings

1. **Tool schema translation is bounded and mechanical** (#26 §a): nested `{type:"function", function:{parameters}}` ↔ flat `{name, input_schema}`; string `arguments` ↔ parsed `input` (CC→Anthropic parses leniently, Anthropic→CC serializes); `role:"tool"` messages ↔ `tool_result` blocks (`is_error` has no CC equivalent); system hoisted on CC→Anthropic.
2. **The two SSE grammars differ structurally** (#26 §b): OpenAI index-keyed `delta.tool_calls` fragments + opt-in usage chunk + `[DONE]`; Anthropic `content_block_*`/`input_json_delta`/cumulative `message_delta` + `ping`/`error` events; OpenRouter adds `: OPENROUTER PROCESSING` comments (must be skipped pre-parse) and mid-stream `error` chunks at HTTP 200. Per-dialect normalizers, never one shared.
3. **Cost reporting is asymmetric**: only OpenRouter returns `usage.cost` USD per response; Anthropic/OpenAI report tokens (Anthropic's `input_tokens` counts only post-breakpoint — `total_input = cache_read + cache_creation + input_tokens`; cache multipliers 1.25×/2× write, 0.1× read) requiring client-side price tables keyed on exact pinned ids.
4. **Effort knobs converge on ordinals**: OpenAI `reasoning_effort` and Anthropic `output_config.effort` (manual `budget_tokens` is 400-rejected on Claude 4.7+/5-series); effort changes invalidate prompt-cache prefixes on both providers — hence per-(fingerprint, target) stickiness.
5. **Rate limits favor Anthropic for tool loops** (cache reads exempt from ITPM; tool defs are cacheable prefix) and OpenRouter for availability (automatic provider fallback). Probe validation: the #32 prototype round-tripped both dialect legs cleanly hermetically (3/3 checks each), surfacing one real grammar subtlety (SSE event separation) en route.

## Architecture

```
HTTP Request (/v1/chat/completions OR /v1/messages)
  │
  ├─ 1. Router & Preprocessor (unchanged, ADR 0007)
  │      ├─ Fat margin ──► Router verdict (api targets eligible in _resolve_tier)
  │      └─ Contested ───► Preprocessor (unconditional; tool-blind; CLI-only fits)
  │
  ├─ 2. Route Resolution (server.py)
  │      ├─ Verdict local/frontier ──► dispatch (api tier = ApiBackend, tools pass through)
  │      └─ Verdict contested ──► Tollbooth (mixed menu):
  │            ├─ Candidate pool: registered CLI ∪ served api-kind tiers
  │            ├─ Presence probe per provider (concurrent, fail-fast) → candidacy
  │            ├─ Capability filter: tools present ⇒ CLI targets drop
  │            ├─ Rank: (-fit, cap_score, notional price, target id); top 3 + local anchor
  │            ├─ Options: uniform notional estimate + cash annotation (metered/subscription/$0)
  │            └─ Empty capable frontier + local serves ──► no toll, straight local
  │
  ├─ 3. API Dispatch (api_backends.py — OpenAIBackend / AnthropicBackend / OpenRouterBackend)
  │      ├─ Translate client dialect → provider grammar (pure helpers)
  │      ├─ Effort self-projection (per-provider table; sticky per fingerprint+target)
  │      ├─ Token clamp: client value never lowered; per-model default; effort headroom
  │      ├─ Aggressive retry (≤5, jittered, header-honoring, ~120s budget; 4xx fail-fast)
  │      ├─ Buffered relay: buffer provider stream → relay client SSE from buffer
  │      └─ Failure: headless → dialect-native error (fail fast);
  │         human toll pick → unbounded failover across capable ranking
  │
  └─ 4. Ledger & Harvest (dual-track)
         ├─ cost_usd = metered cash (usage.cost or tokens × pinned price; CLI/local $0)
         ├─ notional_usd = value at target's own prices (CLI = old cost_usd; API = metered)
         ├─ harvest: baseline (reference price) / notional spent / cash out / kept-in-pocket
         └─ hop telemetry: route_choice, serving target, provider_error chain, retry stats
```

### Module layout & shapes

**`config.py`** — `TierSpec.kind` gains `"api"` (round-trips through save/load unchanged); curated defaults table: per provider, pinned model ids with `price_in`/`price_out`, default max output tokens, and token field name (`max_completion_tokens` vs `max_tokens`). No `detect()` change.

**Credentials resolution (new module)** — hierarchy env (`ANTHROPIC_API_KEY`/`OPENAI_API_KEY`/`OPENROUTER_API_KEY`) → OS keychain (`security find-generic-password -s kultivait -a <provider>`; platform backends where available) → `~/.kultivait/credentials.toml` (0600). Pure `resolve_key(provider) -> str | None`; never displays, logs, or persists to config.toml.

**`backends.py`** — three standalone classes, `Backend` protocol conformance, `supports_tools = True`, `local = False`:

```python
@dataclass(frozen=True)
class ProviderDefaults:   # curated table entry (from #32 probe + ADR 0008)
    model: str            # pinned exact id
    price_in: float       # USD/MTok
    price_out: float
    max_output_tokens: int
    token_field: str      # "max_tokens" | "max_completion_tokens"
```

Shared pure helpers (module-level, from the #32 probe seed): dialect translation both directions per the matrix above; per-dialect SSE event iterators (`iter_sse`, Anthropic `content_block`/`input_json_delta` assembler, OpenAI index-keyed `tool_calls` assembler). Per class: auth headers (Anthropic `x-api-key` + `anthropic-version`; OpenAI/OpenRouter Bearer), base URL, effort projection table, cost extraction (OpenRouter `usage.cost`; token-count × table elsewhere, honoring Anthropic's three-way input split).

**Presence probe (tollbooth/server)** — concurrent per-provider authenticated GETs (Anthropic/OpenAI models-list, OpenRouter `/api/v1/key`), fail-fast timeout, outcomes into menu metadata.

**Ledger/harvest** — additive `notional_usd` (legacy default = old `cost_usd`); `harvest()` gains `notional_spent_usd`/`metered_spent_usd` with old keys retained as notional-lens aliases.

**Capability eval (new experiments-level harness)** — repo-embedded corpus of tool-loop tasks; dispatcher runs each task directly per registered-and-served backend × effort level; cross-family judge with versioned rubric; artifacts per case (transcript + scores + usage); accuracy-only summary.

## Error handling summary

- Non-retryable 4xx (auth/validation): fail fast, never hammered; dialect-native error to the client.
- Retryable (429/529/5xx/connect/timeout): aggressive same-target retry, jittered, header-honoring, ~120s budget.
- Mid-stream provider failure: impossible at the client boundary — buffered relay makes every failure pre-stream; failed attempts discarded and retried whole.
- Exhausted retries: headless → fail-fast dialect-native error; human toll pick → unbounded failover across the capable ranking (never onto an incapable target; never a silent local dump of unservable work).
- Missing/unresolvable key: tier registered but not served (excluded like a missing binary); menu probe failure drops the target from that menu only.
- Unpriced api tier: conservative frontier default price + warning — ledger math never silently $0.

## Testing

Good tests exercise external behavior at the highest seam: the two HTTP endpoints (request in → routed/dispatched/streamed/recorded out) and the public module surfaces (`resolve_effort`, `build_route_menu`, `resolve_auto_policy`, `harvest`, credentials resolution). Prior art: hermetic backend tests via `httpx.MockTransport` with grammar-faithful SSE fixtures (the #32 probe's fixtures are the seed); tollbooth's 26 hermetic tests; server integration tests on both endpoints; ledger/harvest field tests with legacy-entry migration cases. Live verification: OpenRouter wedge smoke (real key, both dialects, tool round-trip), presence-probe drop behavior, retry on 429 fixtures, presence-gated failover paths. The capability eval ships with a smoke corpus run hermetically judged (cross-family rule structurally enforced, judge mocked).

## Docs

README: provider registration (copy-ready `[[tiers]]` blocks + curated defaults pointer), the three-source key contract (env lines, `security add-generic-password`, credentials.toml snippet), two-lens harvest reading guide, capability eval usage. CONTEXT.md terms already canonized (Frontier provider, Dialect, Metered/Notional cost, Reference price, Capability filter, Effort projection, Capability eval, Presence probe, Buffered relay).

## Out of scope

- Autonomous multi-agent orchestration executing sub-task candidates (ADR 0002 stands; fresh effort later).
- Live visual tollbooth & harvest dashboard (map #25's ruled-out candidate C).
- Judge fitting of API targets by the preprocessor (fits stay CLI-only; tail-key ranking per ADR 0007).
- Router-accuracy eval on tool traffic (consciously unvalidated per #30/#33).
- OpenAI Responses API (CC covers the surface; `reasoning.mode:"pro"` noted as a future escalation path).
- Pricing auto-discovery from live APIs (curated pinned table only).

## Further notes

- Build phasing (the R-slices): registration/credentials → backend core → OpenRouter wedge end-to-end → Anthropic+OpenAI direct (parallel) → contested-path integration (absorbs the shared contested-resolution refactor, stray #24) → capability eval → tollbooth hardening (absorbs stray #23).
- The #32 probe (branch `prototype/tools-passthrough-probe`) is the copy-ready seed for the translation helpers and both SSE assemblers; its `--live` mode becomes the R3 smoke test once a key exists.
- Dogfooding follow-up: once tool traffic reaches API targets, the harvest's cash-out lane gives the first real metered-spend telemetry; the capability eval quantifies the local-first trade it buys.
