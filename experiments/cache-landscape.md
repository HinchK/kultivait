# Cache landscape: provider prompt-caching mechanics & observability

Research for issue #75 (Map #74). Surveyed from primary documentation on 2026-08-25.
Companion to `experiments/rest-capability-matrix.md` (which covered REST surface broadly; this file goes deep on caching only).

Primary sources:

- **Anthropic prompt caching**: https://platform.claude.com/docs/en/build-with-claude/prompt-caching (canonical URL `docs.anthropic.com/en/docs/build-with-claude/prompt-caching` redirects here)
- **Anthropic rate limits (cache-aware ITPM)**: https://platform.claude.com/docs/en/api/rate-limits
- **OpenAI prompt caching**: https://platform.openai.com/docs/guides/prompt-caching
- **OpenRouter prompt caching**: https://openrouter.ai/docs/features/prompt-caching
- **OpenRouter models API (live query, 2026-08-25)**: `GET https://openrouter.ai/api/v1/models` (418 models)

## Comparison table

| Dimension | Anthropic (direct, Messages) | OpenAI (direct, Chat Completions / Responses) | OpenRouter (aggregator) |
|---|---|---|---|
| Opt-in model | Explicit breakpoints on content blocks, **or** top-level `cache_control` for automatic caching | **Automatic (implicit) by default** on supported models, no opt-in; explicit mode opt-in on GPT-5.6+ | Passthrough of either style; block markers translated across families |
| Breakpoint syntax | `"cache_control": {"type": "ephemeral"}` (+ optional `"ttl": "1h"`) on a content block in `tools` / `system` / `messages`; or one top-level `cache_control` for automatic mode | GPT-5.6+: `"prompt_cache_breakpoint": {"mode": "explicit"}` on a text block + request-root `prompt_cache_options: {"mode": "explicit", "ttl": "30m"}`. Pre-5.6: **no user-placeable breakpoints** (implicit intervals only) | Anthropic-style `cache_control` accepted and translated: → `prompt_cache_breakpoint` for OpenAI models; → default 5m `cache_control` for Google. Reverse direction also translated. **TTLs are never translated** (cache_control `ttl` dropped toward OpenAI; `prompt_cache_options` is OpenAI-only) |
| Max breakpoints / writes per request | **4 explicit breakpoints**; automatic caching consumes one of the 4 slots (4 explicit + top-level = 400 error) | GPT-5.6+: **4 cache writes** per request (implicit breakpoint uses one slot, leaving 3); reads consider up to the latest 50 breakpoints. Pre-5.6: no explicit breakpoints | Gemini: only the **last** breakpoint used (extras safe/no-op); Anthropic-family: full 4 |
| Min cacheable prefix | Per model: 512 (Opus 5, Fable 5, Mythos 5) · 1,024 (Opus 4.8, Sonnet 5/4.6/4.5, Opus 4.1/4, Sonnet 4) · 2,048 (Mythos Preview, Opus 4.7, Haiku 3.5) · 4,096 (Opus 4.6/4.5, Haiku 4.5) tokens. Below min: **silently not cached, no error** | 1,024 visible tokens (GPT-5.6+) · 2,048 (older; occasional sub-2,048 hits reported). Hidden OpenAI system tokens excluded from the count | Inherits upstream per-model minimums (docs repeat the Anthropic table; note OpenRouter's table lists Opus 4.8 at 4,096 but Anthropic's own page says 1,024 — trust Anthropic for direct semantics) |
| TTL options | 5m (default) or 1h (`ttl: "1h"`). Refreshed free on every read. TTL clock starts at request start; response generation time eats into it | GPT-5.6+: `prompt_cache_options.ttl`, only `"30m"`, default 30m. Pre-5.6: `prompt_cache_retention` = `in_memory` (~5–10 min) or `24h` (~30 min typical) | Per upstream family; 1h supported across all Claude providers (Anthropic/Bedrock/Vertex) |
| Cache write price | 5m: **1.25×** base input · 1h: **2×** base input | GPT-5.6+: **1.25×** (automatic or explicit) · pre-5.6: **no write charge** | Passes through per-model: `pricing.input_cache_write` (5m), `pricing.input_cache_write_1h`; Anthropic/Alibaba/GPT-5.6+ charge writes, most others don't |
| Cache read price | **0.1×** base input (all models) | GPT-5.6+: **0.1×** · pre-5.6: model-dependent cached-input rate (e.g. gpt-4.1 = 0.25× per live OpenRouter data) | Per-model `pricing.input_cache_read` is ground truth (e.g. qwen3-coder-plus read is 0.2× despite the doc's generic "0.1×" for Alibaba) |
| Usage fields on **hit** | `usage.cache_read_input_tokens` > 0 (+ `input_tokens` = post-breakpoint only, `cache_creation_input_tokens` = 0 on pure read) | `usage.prompt_tokens_details.cached_tokens` > 0 (Chat Completions) / `usage.input_tokens_details.cached_tokens` (Responses); GPT-5.6+ also `cache_write_tokens` when writing | Normalized to `usage.prompt_tokens_details.cached_tokens` + `cache_write_tokens` on both dialects; plus per-generation `cache_discount` (savings USD; negative on writes) and authoritative `usage.cost` |
| Usage fields on **miss** | `cache_read_input_tokens` = 0 and `cache_creation_input_tokens` = 0 (both zero ⇒ not cached — usually below min length); first write shows `cache_creation_input_tokens` > 0 | `cached_tokens` absent or 0; pre-5.6 reporting **rounds down to a multiple of 128** and excludes hidden tokens | Same normalization; absence of cache pricing fields on a model ≈ caching not billed (e.g. kimi-k2) |
| Tool definitions cacheable | Yes — `tools` array is the **first** level of the prefix hierarchy (`tools` → `system` → `messages`); changing tool defs invalidates the entire cache | Yes — tool definitions are part of the rendered prefix; `tools` changes (names/schemas/ordering) break the prefix. Keep defs stable and use `tool_choice: "none"` / `allowed_tools` instead of removing defs | Yes where upstream supports it |
| Rate-limit treatment | **Cache-aware ITPM**: `cache_read_input_tokens` does **not** count toward ITPM (exception: Haiku 3.5, †-marked); `input_tokens` + `cache_creation_input_tokens` do. 80% hit rate at 2M ITPM ≈ 10M effective tokens/min | **Cached tokens still count** toward tokens-per-minute limits; caching changes nothing about rate-limit math | n/a (upstream provider's limits apply once routed) |
| Cache locality / affinity | Org + workspace isolated; exact prefix match required | **Machine-local**; >15 RPM can overflow routes; `prompt_cache_key` (string) steers affinity; not shared across orgs/regions | **Provider sticky routing**: after a cache-bearing request, same-model requests stick to the provider; conversation keyed by hash of first system + first non-system message (or explicit `session_id` body/header, ≤256 chars; falls back to `prompt_cache_key`); sticky session expires after **10 min** idle |
| Model-family support (via OpenRouter) | Claude on Anthropic/Vertex/Azure/Bedrock/Claude-Platform-AWS; automatic top-level supported everywhere except legacy Bedrock (translated to a trailing breakpoint) | OpenAI: implicit everywhere; explicit = GPT-5.6+ only | Also: Google Gemini (explicit breakpoints, last-one-wins), Alibaba Qwen (explicit, Anthropic syntax, 5m TTL), implicit for DeepSeek/Grok/Groq/Moonshot/Z.AI |

## Usage-reporting shapes — exact field maps

**Anthropic dialect** (what `AnthropicBackend` parses at src/kultivait/api_backends.py:562-566):

```json
{
  "usage": {
    "input_tokens": 50,                     // tokens AFTER the last breakpoint only
    "cache_creation_input_tokens": 100000,  // written this request (miss → write)
    "cache_read_input_tokens": 0,           // read this request (hit)
    "output_tokens": 500
  }
}
// total input = cache_read + cache_creation + input_tokens  (doc-stated identity)
```

- Miss on first write: `cache_creation_input_tokens > 0`, `cache_read_input_tokens = 0`.
- Hit: `cache_read_input_tokens > 0`, `cache_creation_input_tokens = 0` (or > 0 if the breakpoint advanced past prior writes).
- **Both zero ⇒ prompt was not cached at all** (usually below the model minimum; no error is returned). This is the probe signal.
- Streaming: same fields arrive in the `message_start` event.

**OpenAI dialect** (what the OpenAI-path parses at src/kultivait/api_backends.py:811,883 and the normalizer at src/kultivait/backends.py:404):

```json
{
  "usage": {
    "prompt_tokens": 10339,
    "prompt_tokens_details": { "cached_tokens": 10318, "cache_write_tokens": 0 },
    "completion_tokens": 60
  }
}
```

- `cached_tokens` counts reads; `cache_write_tokens` (GPT-5.6+, and in OpenRouter's normalization) counts writes.
- Miss: `cached_tokens` 0/absent.
- Pre-5.6 reporting quantizes: `cached_tokens` = (last matched breakpoint − hidden tokens), rounded **down to a multiple of 128** — expect small accounting noise, not exactness.
- Chat Completions names it `prompt_tokens_details`; Responses names it `input_tokens_details`.

## Rate limits: confirmed and refined vs #26

`experiments/rest-capability-matrix.md:226` (from #26) said "cache reads don't count toward ITPM (all current models)". Current primary doc (https://platform.claude.com/docs/en/api/rate-limits §Cache-aware ITPM) **confirms with one refinement**: reads are exempt for *most* models; retired-except-Bedrock/GCP **Claude Haiku 3.5 is the † exception** and does count reads. `input_tokens` (post-breakpoint) and `cache_creation_input_tokens` always count. So: true for every active model kultivait can register; keep the Haiku-3.5 caveat in the notes.

**OpenAI is the opposite**: the prompt-caching FAQ states plainly "Cached input tokens still count toward tokens-per-minute limits" (https://platform.openai.com/docs/guides/prompt-caching#faq — "Do cached prompts count toward rate limits?"). Anthropic cache-read ITPM exemption remains a real differentiator for tool-heavy loops routed Anthropic-direct (as ADR 0004 argued).

## What this means for kultivait

Three seams the decision lands on:

### 1. Proxy breakpoint insertion point

- **One syntax covers everything if inserted as block-level Anthropic-style `cache_control`**: Anthropic-direct honors it natively; OpenRouter translates it to `prompt_cache_breakpoint` for OpenAI-family targets and to a default 5m `cache_control` for Google (openrouter.ai/docs/features/prompt-caching, "block-level markers are interchangeable"). OpenAI-direct pre-5.6 accepts no breakpoints at all — insertion there is a no-op; only `prompt_cache_key` helps.
- **Never rely on TTL crossing providers**: `cache_control.ttl` is dropped toward OpenAI; `prompt_cache_options` is OpenAI-only. If the proxy inserts breakpoints, emit default (5m) `cache_control` and treat longer TTLs as a per-target refinement, not a cross-cutting feature.
- **Insert on the last block that stays identical, not the final user message.** Both Anthropic and OpenAI docs warn of the varying-suffix trap: a breakpoint on per-request content (timestamps, the new message) writes a fresh entry every request and never reads. The proxy's insertion point is therefore "end of stable prefix" — in kultivait's translated bodies: the last tool definition (tool-bearing requests) or the last system block.
- **Lookback windows**: Anthropic reads walk back at most 20 blocks per breakpoint; OpenAI (GPT-5.6+) considers up to the latest 50 breakpoints. A growing conversation that adds >20 blocks between turns needs a second explicit breakpoint placed earlier — the proxy can emit the documented 2-breakpoint pattern (tools tail + conversation tail) within the 4-slot budget.
- **Idempotency/400 hazards** (Anthropic): 4 explicit breakpoints already present + top-level automatic `cache_control` = 400; top-level TTL conflicting with a same-block explicit TTL = 400. Insertion must count existing client-provided markers and skip if slots are full. Client-arrived markers in either dialect must survive translation (the dialect seam at src/kultivait/server.py:593 `/v1/chat/completions` and :691 `/v1/messages`).
- **Determinism is cache currency**: exact-prefix matching means the translation tables (tool schemas, key ordering) must be byte-stable across turns. Anthropic's troubleshooting explicitly flags JSON key-order randomization breaking caches.
- The stale `anthropic-beta: prompt-caching-2024-07-25` header at api_backends.py:549,622 is legacy — current docs describe caching (including the top-level automatic form) as GA with no beta header. Harmless but droppable whenever that file is next touched.

### 2. Ledger fields

- **Anthropic path already prices 5m correctly** (api_backends.py:569-574: 1.25× write / 0.1× read / plain input), and `tokens_in = input + creation + read` matches the doc's total-input identity. Gap: the multiplier is hardcoded 5m — a 1h-TTL write would be underpriced at 1.25× instead of 2×. If 1h is ever emitted, the ledger needs the TTL alongside the token counts, or write price keyed per (model, TTL).
- **OpenAI path reads only `cached_tokens`** (api_backends.py:811,883) and treats the rest as plain input. On GPT-5.6+ that **understates metered cost** by 0.25× on every cache write, because writes bill at 1.25× and are only visible via `cache_write_tokens`. Cheapest fix: read `prompt_tokens_details.cache_write_tokens` (already present in OpenRouter's normalized usage too) and apply 1.25× where the target model charges writes.
- **Notional cost (the savings lens) should key on per-model cache prices, not generic multipliers**: live models API gives exact values — `pricing.input_cache_read`, `pricing.input_cache_write`, `pricing.input_cache_write_1h` (USD/token). Verified: anthropic/claude-opus-4.5 = $5 base / $6.25 write / $10 write-1h / $0.50 read (exactly 1.25×/2×/0.1×); openai/gpt-5.6-sol = $2 / $2.50 / $0.20; openai/gpt-4.1 = $2 / read-only $0.50 (0.25×); qwen/qwen3-coder-plus read = 0.2× (doc's generic 0.1× is wrong for this model). Note: the legacy top-level `cache_pricing` field is **gone** — 0 of 418 models carry it; the subfields under `pricing` are the current shape.
- **Metered cost via OpenRouter stays `usage.cost`-authoritative**; `cache_discount` per generation quantifies cache savings directly and could feed the ledger's savings narrative without any multiplier math.
- OpenAI pre-5.6 `cached_tokens` quantizes to 128-token multiples — ledger reconciliation against Anthropic's exact counts should tolerate rounding drift on OpenAI-family targets.

### 3. Probe design

- A cache probe is inherently **two sequential dispatches with an identical stable prefix**: call 1 should show a write (`cache_creation_input_tokens > 0` or `cache_write_tokens > 0`), call 2 within TTL should show a read (`cache_read_input_tokens > 0` or `cached_tokens > 0`). Both-zero on both calls = sub-minimum prefix or unsupported (silent, no error) — so probe payloads must exceed the largest plausible minimum (4,096 tokens is safe across current Anthropic models; 2,048 for OpenAI pre-5.6).
- **Serialize the two calls**: Anthropic cache entries only become visible after the first response begins; parallel calls race the write.
- **Keep the two probe payloads byte-identical up to the breakpoint** and vary only post-breakpoint content — that isolates read-hit semantics from the varying-suffix trap the docs both warn about.
- **OpenRouter stickiness interacts with probing**: the first cache-bearing request pins the provider for that conversation key. kultivait's conversation fingerprint (hash of system + first user message, CONTEXT.md) is almost exactly OpenRouter's own sticky-routing key (hash of first system/developer + first non-system message) — forwarding the fingerprint as `session_id` (or `prompt_cache_key`) on proxied multi-turn traffic would keep caches warm for free; the probe should use the same key it intends production traffic to use, and remember sticky sessions lapse after 10 minutes idle.
- **Rate-limit observability differs by provider and belongs in the ledger's effective-throughput math**: Anthropic cache reads are ITPM-free (Haiku 3.5 caveat), OpenAI's are not. A hit-rate metric per frontier target is therefore not just a savings number — for Anthropic targets it approximates an ITPM multiplier.

### Smallest live-actionable corrections surfaced by the survey

1. OpenAI-dialect parse: add `cache_write_tokens` so GPT-5.6+ writes aren't priced as plain input (api_backends.py:811,883; backends.py:404).
2. Anthropic 1h writes would be mispriced at 1.25× by the hardcoded multiplier (api_backends.py:571) — fine while only 5m is emitted; gate 1h emission on carrying TTL into the price.
3. Drop the stale beta header (api_backends.py:549,622) on next touch.
4. rest-capability-matrix.md:226 "all current models" → "all active models (retired Haiku 3.5 excepted)".
