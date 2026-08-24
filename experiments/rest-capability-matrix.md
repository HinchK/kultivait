# REST provider & tool-calling capability matrix

Research ticket: [Standard-Pentest/kultivait#26](https://github.com/Standard-Pentest/kultivait/issues/26) (child of map #25).
Date: 2026-08-23. Branch: `research/rest-capability-matrix`.

What the three candidate REST providers (Anthropic Messages API, OpenAI Chat Completions,
OpenRouter) actually expose today, established **entirely from primary documentation**
(docs.anthropic.com / platform.claude.com, platform.openai.com, openrouter.ai/docs) plus one
live pull of OpenRouter's public `GET /api/v1/models` pricing API. Read against kultivait's
proxy, which exposes BOTH `/v1/chat/completions` and `/v1/messages` to clients
(`server.py`), so every backend needs a dialect-translation story in both directions.

## Summary comparison

| | Anthropic Messages | OpenAI Chat Completions | OpenRouter |
| --- | --- | --- | --- |
| **Endpoint** | `POST https://api.anthropic.com/v1/messages` | `POST https://api.openai.com/v1/chat/completions` | `POST https://openrouter.ai/api/v1/chat/completions` (+ native `/v1/responses`, `/v1/messages`) |
| **Tool definition** | `tools: [{name, description, input_schema}]` (flat; JSON Schema) | `tools: [{type: "function", function: {name, description, parameters, strict}}]` (nested) | OpenAI shape, normalized across all upstream providers |
| **Tool choice** | `{type: "auto"\|"any"\|"tool"\|"none", name?, disable_parallel_tool_use?}` | `"none"\|"auto"\|"required"` or `{type:"function", function:{name}}`; `parallel_tool_calls: bool` | OpenAI shape (`auto`/`none`/named; `required` supported) |
| **Tool call in response** | `tool_use` content block `{id, name, input: <object>}`; `stop_reason: "tool_use"` | assistant msg `tool_calls: [{id, function: {name, arguments: <JSON string>}}]`; `finish_reason: "tool_calls"` | OpenAI shape |
| **Tool result back** | `tool_result` block `{tool_use_id, content, is_error}` inside a `user` message | `{role: "tool", tool_call_id, content}` message | OpenAI shape |
| **Streaming tool args** | `input_json_delta.partial_json` string fragments on a `tool_use` block (keyed by block `index`) | `delta.tool_calls[].function.arguments` string fragments (keyed by tool_calls `index`; `id`+`name` on first fragment) | OpenAI shape + `: OPENROUTER PROCESSING` SSE comments + mid-stream `error` events |
| **Usage fields** | `input_tokens` (post-breakpoint only!), `cache_creation_input_tokens`, `cache_read_input_tokens`, `output_tokens`, `output_tokens_details.thinking_tokens` | `prompt_tokens`, `completion_tokens`, `total_tokens`, `prompt_tokens_details.cached_tokens`/`cache_write_tokens`, `completion_tokens_details.reasoning_tokens` | OpenAI shape **plus `usage.cost` (USD) + `cost_details.upstream_inference_cost`** — always included |
| **Billable cost field?** | **No** (tokens only; compute client-side) | **No** (tokens only) | **Yes** — `usage.cost` in every response/final chunk |
| **Auth** | `x-api-key: <key>` **and** `anthropic-version: 2023-06-01` headers | `Authorization: Bearer <key>` | `Authorization: Bearer <key>`; optional `HTTP-Referer` / `X-OpenRouter-Title` |
| **Effort knob** | `output_config.effort: low\|medium\|high\|xhigh\|max` (+ `thinking: {type:"adaptive"}`); manual `budget_tokens` **rejected (400) on Claude 4.7+/5-series** | `reasoning_effort: none\|minimal\|low\|medium\|high\|xhigh\|max` (model-dependent subset) | OpenAI `reasoning_effort` / `reasoning: {...}` passthrough + `:thinking` model-variant suffix |
| **Frontier price (in/out, USD/MTok)** | Sonnet 5 $2/$10; Opus 5 $5/$25; Fable 5 $10/$50; Haiku 4.5 $1/$5 | gpt-5.6-sol $4/$20 (promo); terra $2/$12; luna $0.20/$1.20; gpt-5.5 $5/$30 | Matches direct (sonnet-5 $2/$10, opus-5 $5/$25); sol observed listed at $2/$10; grok-4.6 $2/$6; gemini-3.7-flash $0.375/$1.875 |
| **Cache pricing** | writes 1.25x (5m) / 2x (1h), reads 0.1x | cached reads 0.1x, writes 1.25x (gpt-5.6) | per-model `input_cache_read` in pricing API |
| **Rate-limit headers** | `anthropic-ratelimit-{requests,tokens,input-tokens,output-tokens}-{limit,remaining,reset}`, `retry-after` | `x-ratelimit-{limit,remaining,reset}-{requests,tokens}` (+project-token variants), `Retry-After` | `X-RateLimit-*` **only on 429 error responses**; poll `GET /api/v1/key` |

## (a) Tool schema formats & translation needs

**OpenAI Chat Completions.** Definitions nest under a `type: "function"` wrapper:
`function.parameters` carries the JSON Schema; `strict: true` enables guaranteed schema
adherence (structured-outputs subset). `tool_choice` takes string modes
(`none`/`auto`/`required`) or a named-tool object. `parallel_tool_calls: boolean`
controls parallel calls. The model's call arrives as
`message.tool_calls: [{id, type: "function", function: {name, arguments}}]` where
`arguments` is a **JSON-encoded string** (docs warn it "does not always generate valid
JSON" — validate before executing). `finish_reason: "tool_calls"`. Results return as
dedicated `role: "tool"` messages keyed by `tool_call_id`; there is no structured
error flag (errors are conveyed as content). With o1+ models the `developer` role
replaces `system`.

**Anthropic Messages.** Definitions are flat: `{name, description, input_schema}` — no
`function` wrapper, and the schema key is `input_schema`, not `parameters`. `strict: true`
exists here too. `tool_choice` is object-only: `{type: "auto"|"any"|"tool"|"none", name?,
disable_parallel_tool_use?}`. The model's call is a `tool_use` **content block**
`{id, name, input}` where `input` is a **parsed object**, never a string.
`stop_reason: "tool_use"`. Results return as `tool_result` blocks
`{tool_use_id, content, is_error}` nested in the next **`user`** message — with a
first-class `is_error` boolean for error signaling. System prompt is a top-level
`system` param, not a role. Anthropic bills a tool-use system-prompt overhead
(~286–675 tokens depending on model and tool_choice mode).

**Translation matrix for kultivait's two client dialects** (`server.py` exposes both):

| Concept | `/v1/chat/completions` client speak | `/v1/messages` client speak | Losses/gotchas |
| --- | --- | --- | --- |
| Tool def | `{type:"function", function:{name, parameters}}` | `{name, input_schema}` | mechanical wrap/unwrap |
| Force tool | `{type:"function",function:{name}}` | `{type:"tool", name}` | mechanical |
| Must-call-any | `"required"` | `{type:"any"}` | semantic pair |
| No tools | `"none"` | `{type:"none"}` | direct |
| Disable parallel | (no direct flag; `parallel_tool_calls:false`) | `disable_parallel_tool_use:true` | near-pair |
| Call args | string `arguments` (may be invalid JSON) | object `input` | CC→Anthropic must parse (lenient); Anthropic→CC must serialize |
| Tool result | `role:"tool"` message | `tool_result` block in user msg | merge/split multiple results per turn |
| Result error | content convention only | `is_error: true` | flag has no CC equivalent |
| System | `system`/`developer` role message | top-level `system` | hoist on CC→Anthropic |
| OpenAI backend | native | full inverse translation | OpenAI never returns object args |
| Anthropic backend | full translation | native | Anthropic never returns string args |
| OpenRouter backend | **native (zero translation)** | OpenRouter also serves `/v1/messages` natively | router re-validates schema every call — `tools` must be resent each request |

## (b) Streaming behavior for tool calls

**OpenAI Chat Completions.** SSE `data:` lines of `chat.completion.chunk` objects;
`data: [DONE]` terminates. Text arrives as `delta.content` fragments. Tool calls arrive
as `delta.tool_calls` array entries, each `{index, id?, function: {name?, arguments?},
type?}` — **keyed by `index`**: the first fragment for a given index carries `id` + `name`,
subsequent fragments carry only `arguments` string shards to concatenate per index.
Terminal chunk carries `finish_reason: "tool_calls"`. Usage is **opt-in**:
`stream_options: {include_usage: true}` yields one extra pre-`[DONE]` chunk whose
`usage` holds totals (`choices: []`); if the stream aborts you may never see it.

**Anthropic Messages.** One unified SSE event grammar for everything (docs: "unified
streaming"): `message_start` (Message with empty content, initial usage) → per block
`content_block_start` → zero+ `content_block_delta` → `content_block_stop` → one+
`message_delta` (top-level deltas; **usage here is cumulative**) → `message_stop`, with
`ping` events interspersed and `event: error` for mid-stream failures (e.g. 529
overloaded). A tool call opens as `content_block_start` with the full
`{type:"tool_use", id, name, input:{}}` header, then streams
`delta: {type: "input_json_delta", partial_json: "<fragment>"}` fragments (first
fragment may be the empty string `""`); `input` is only guaranteed parseable at
`content_block_stop`. Models emit one key/value pair at a time, so bursts are normal.
Thinking blocks stream as `thinking_delta` + a `signature_delta` just before stop.
Error recovery differs by generation (assistant-prefill resume ≤4.5; user-continuation
message ≥4.6); tool_use and thinking blocks cannot be partially recovered.

**Proxy translation.** CC-dialect clients expect index-keyed `tool_calls` fragments;
Anthropic delivers block-index-keyed `partial_json` — assembly logic is structurally
similar (concatenate strings per key) but the shapes, headers, and terminators differ
(`[DONE]` sentinel vs `message_stop` event; opt-in usage chunk vs always-on cumulative
`message_delta`). `ping`/`error` events need CC-dialect mappings (comment or synthetic
chunk). Fidelity here is explicitly a first-class constraint of map #25.

**OpenRouter.** OpenAI chunk dialect verbatim, plus: SSE comment lines
`: OPENROUTER PROCESSING` (must be skipped before `JSON.parse` — naive parsers crash);
mid-stream errors arrive as a top-level `error` field on a chunk with
`finish_reason: "error"` (HTTP stays 200); `X-Generation-Id` response header; usage
**with cost** arrives automatically in the final chunk (no `include_usage` needed —
that param is deprecated/no-op). Stream cancellation (client abort) stops billing on
supported providers (OpenAI, Anthropic, and most major ones; not Google/Bedrock).

## (c) Usage & cost reporting (exact fields)

- **OpenAI** `usage`: `prompt_tokens`, `completion_tokens`, `total_tokens`;
  `prompt_tokens_details: {cached_tokens, cache_write_tokens, audio_tokens, image_tokens, text_tokens}`;
  `completion_tokens_details: {reasoning_tokens, text_tokens, audio_tokens, accepted_prediction_tokens, rejected_prediction_tokens}`.
  Reasoning tokens are hidden but billed as output. **No cost field.**
- **Anthropic** `usage`: `input_tokens`, `output_tokens`,
  `cache_creation_input_tokens`, `cache_read_input_tokens` (present from `message_start`
  onward when streaming); `output_tokens_details.thinking_tokens` (final `message_delta`
  only); `server_tool_use` counts for server tools. **Critical accounting subtlety:**
  `input_tokens` counts ONLY tokens after the last cache breakpoint —
  `total_input = cache_read + cache_creation + input_tokens`. Cost math and rate-limit
  math must use all three. **No cost field.**
- **OpenRouter** `usage`: OpenAI shape **plus** `cost` (USD charged) and
  `cost_details.upstream_inference_cost`; always included in non-streaming responses and
  the final streaming chunk — the deprecated `usage:{include:true}` /
  `stream_options:{include_usage:true}` params are no-ops. `cached_tokens` = cache reads;
  `cache_write_tokens` only for models with explicit caching pricing. Async alternative:
  `GET /generation?id=...`.
- **Ledger implication:** only OpenRouter hands the harvest/ledger a ground-truth USD
  figure per request; Anthropic/OpenAI require client-side price tables keyed by model
  (+ cache multipliers), which is exactly the duality the cost-model ticket owns.

## (d) Auth & key handling

- **Anthropic:** two headers required on every request — `x-api-key: <ANTHROPIC_API_KEY>`
  and `anthropic-version: 2023-06-01` (all docs curl examples show both). Omitting the
  version header is the classic 400. No Bearer for API keys (Bearer is the OAuth-token
  path).
- **OpenAI:** single header — `Authorization: Bearer $OPENAI_API_KEY`. Keys are opaque
  strings; rate limits live at org+project level.
- **OpenRouter:** `Authorization: Bearer <key>` (base `https://openrouter.ai/api/v1`,
  OpenAI SDK-compatible); optional attribution headers `HTTP-Referer`, `X-OpenRouter-Title`;
  keys support per-key credit caps and `GET /api/v1/key` introspection (`limit_remaining`,
  `usage_*` buckets) — a built-in spend-gauge endpoint the other two lack.

## (e) Reasoning-effort knobs

**OpenAI:** `reasoning_effort` on Chat Completions:
`none | minimal | low | medium | high | xhigh | max` (model-dependent subset; gpt-5.5/5.6
default `medium`). Adaptive across efforts; reasoning tokens billed as output. Docs
recommend reserving ≥25k tokens of output headroom; budget via `max_completion_tokens`
(`max_tokens` is deprecated and incompatible with o-series/gpt-5 reasoning models).

**Anthropic:** the ticket's assumed knob `thinking: {type: "enabled", budget_tokens: N}`
is **legacy**: min 1,024, must be `< max_tokens` (exception: interleaved thinking, where
it may span the turn), counts toward `max_tokens` — but it is deprecated on 4.6 models
and **rejected with a 400 on Claude 4.7, 4.8, 5, Sonnet 5, Fable 5, Mythos 5**. The
current control surface on those models is:

- `thinking: {type: "adaptive"}` (always-on for Fable 5), and
- `output_config: {effort: low|medium|high|xhigh|max}` — default `high`, no beta header
  needed, affects **all** tokens including tool-call volume, works with or without
  thinking. Opus 5 forbids `thinking:{type:"disabled"}` at `xhigh`/`max` (400).
  Changing effort mid-conversation invalidates prompt-cache prefixes (budget change
  did the same in manual mode) — hold effort constant within cached sessions.

**Canonical fast/balanced/deep mapping** (for `effort.py`'s adapter table):

| kultivait tier | OpenAI `reasoning_effort` | Anthropic `output_config.effort` | OpenRouter |
| --- | --- | --- | --- |
| fast | `low` (or `minimal`/`none` where supported) | `low` | passthrough of either |
| balanced | `medium` (gpt-5.5/5.6 default) | `medium` | passthrough |
| deep | `high` (→ `xhigh`/`max` for frontier tasks) | `high` (→ `xhigh`) | passthrough / `:thinking` |

Both providers now expose near-identical 5+ level ordinal scales — the four-mechanism
CLI effort table from Map #4 collapses to one mechanism (an ordinal param) for REST
backends, modulo per-model value subsets.

## (f) Pay-per-token pricing (USD per MTok, standard tier)

**Anthropic** (docs pricing table):

| Model | Input | Output | 5m cache write | 1h cache write | Cache read |
| --- | --- | --- | --- | --- | --- |
| claude-fable-5 / claude-mythos-5 | $10 | $50 | $12.50 | $20 | $1 |
| claude-opus-5 (and 4.x) | $5 | $25 | $6.25 | $10 | $0.50 |
| claude-sonnet-5 | $2 | $10 | $2.50 | $4 | $0.20 |
| claude-sonnet-4-6 / 4-5 | $3 | $15 | $3.75 | $6 | $0.30 |
| claude-haiku-4-5 | $1 | $5 | $1.25 | $2 | $0.10 |

Multipliers: 5m write 1.25x, 1h write 2x, read 0.1x. Batch API 50% off.

**OpenAI** (docs pricing page):

| Model | Input | Cached in | Cache write | Output | Long-ctx in/out |
| --- | --- | --- | --- | --- | --- |
| gpt-5.6-sol | $4.00 | $0.40 | $5.00 | $20.00 | $8 / $30 |
| gpt-5.6-terra | $2.00 | $0.20 | $2.50 | $12.00 | $4 / $18 |
| gpt-5.6-luna | $0.20 | $0.02 | $0.25 | $1.20 | $0.40 / $1.80 |
| gpt-5.5 | $5.00 | $0.50 | — | $30.00 | $10 / $45 |
| gpt-5.4 | $2.50 | $0.25 | — | $15.00 | $5 / $22.50 |
| gpt-5.1 / gpt-5 | $1.25 | $0.125 | — | $10.00 | — |

sol's $4/$20 is promotional "at least through November 21, 2026". Batch and Flex are
50% off; Fast mode is 2x. Context window ≥272k triggers long-context pricing on 5.5+.

**OpenRouter** (live `GET /api/v1/models`, USD/MTok = per-token × 1e6, sampled
2026-08-23): `anthropic/claude-sonnet-5` $2/$10 (cached read $0.20),
`anthropic/claude-opus-5` $5/$25 ($0.50), `openai/gpt-5.6-terra` $2/$12 ($0.20),
`openai/gpt-5.6-luna` $0.20/$1.20, `openai/gpt-5.6-sol` **listed $2/$10** — below
OpenAI direct's standard $4/$20 (observed discrepancy worth re-checking at build time;
likely promo pass-through). Notable non-hyperscaler frontier options:
`x-ai/grok-4.6` $2/$6 (500k ctx, cached $0.50), `google/gemini-3.7-flash`
$0.375/$1.875, `deepseek/deepseek-v4-pro-0813` ~$1.12/$3.37,
`deepseek/deepseek-v4-flash-0731` $0.14/$0.28.

## (g) Rate-limit shape

- **Anthropic:** org-level tiers (Evaluation → Start → Build → Scale → Custom), auto-
  graduated by usage history; per-model-class limits in **RPM / ITPM / OTPM**
  (token-bucket, continuously replenished). Start tier: 1,000 RPM / 2M ITPM / 400k OTPM
  for Opus 5, Sonnet 5, Sonnet 4.x, Haiku 4.5 (Fable 5: 500k/100k). Build 5,000 RPM /
  5M ITPM / 1M OTPM; Scale 10,000 / 10M / 2M. **Cache-aware ITPM:** cache **reads**
  don't count toward ITPM (all current models) — effective throughput can be ~5x the
  nominal limit at 80% hit rate. `max_tokens` does NOT count against OTPM. Monthly
  spend caps: Start $500, Build $1k, Scale $200k (breach → 429
  `enforced_spend_limit_reached`, no retry-after). Headers on every response:
  `anthropic-ratelimit-requests-{limit,remaining,reset}`,
  `anthropic-ratelimit-tokens-*`, `anthropic-ratelimit-{input,output}-tokens-*`
  (+ `anthropic-priority-*` on Priority Tier), `retry-after` on 429.
- **OpenAI:** org+project-level tiers graduated by lifetime spend (Free $100/mo →
  Tier 5 $200k/mo at $1k paid). Limits per model in RPM/RPD/TPM/TPD (+IPM); some model
  families share a bucket; long-context requests have separate limits (gpt-5.5).
  Response headers: `x-ratelimit-limit-requests`, `x-ratelimit-limit-tokens`,
  `x-ratelimit-remaining-*`, `x-ratelimit-reset-*`, project-scoped
  `x-ratelimit-{limit,remaining,reset}-project-tokens`; `Retry-After` on 429 (treat as
  minimum; SDKs honor it automatically). Rate limit is estimated as
  max(`max_tokens`, char-count estimate) — oversized `max_tokens` burns TPM.
- **OpenRouter:** no published per-model request caps for paid models (Cloudflare DDoS
  protection as backstop; limits are global per account, not per key). Free `:free`
  variants: 20 RPM always; 50 RPD if <$10 lifetime credits, 1,000 RPD if ≥$10.
  Successful responses carry **no** rate-limit headers; `X-RateLimit-Limit/-Remaining/
  -Reset` appear **only on the 429 error itself** (plus `Retry-After` when providers
  hint). Proactive monitoring via `GET /api/v1/key`. Upstream 429/5xx surface as 429
  with `error.metadata.provider_code`, after fallback routing has already retried
  alternative providers of the same model automatically.

## Ruling: does the Responses API matter for a CC-speaking proxy?

**Not required; one fidelity caveat.** Chat Completions remains fully supported on the
current frontier (gpt-5.6 family) including `tools`, `tool_choice`, streaming
`tool_calls` deltas, `reasoning_effort`, and structured outputs — everything kultivait's
clients send can be served through CC. OpenAI's own guidance nudges new projects to
Responses ("reasoning models work better with the Responses API... improved model
intelligence and performance"), and at least one capability is Responses-only:
`reasoning.mode: "pro"` on gpt-5.6 (their "highest-intelligence API option... use
gpt-5.6-sol in the Responses API with reasoning.mode set to pro"). So: build the proxy
against CC; record Responses as the escalation path if sol-at-max-intelligence becomes a
requirement (OpenRouter also fronts a Responses endpoint if it's ever needed without new
translation code). Responses-only conveniences (previous_response_id state,
encrypted reasoning replay) are client-orchestration features that ADR 0002 says stay
client-side anyway.

## Ruling: does OpenRouter earn the one-key-many-models third slot?

**Yes.** The case, from its own docs/API: (1) one Bearer key over an OpenAI-compatible
base URL reaching every frontier family, with tool calling **normalized to the OpenAI
schema across all upstream providers** — the router validates the schema each call and
tracks per-provider tool-call error rates; (2) it natively serves `/v1/chat/completions`,
`/v1/responses`, **and** `/v1/messages` — the only backend that speaks both of
kultivait's client dialects out of the box, collapsing the translation matrix; (3) it is
the **only** provider returning billable `usage.cost` (USD) per response — direct
ground truth for the ledger/harvest accounting, no price tables to maintain; (4) live
pricing via the public models API (this file's OpenRouter prices came from it);
(5) automatic provider fallback on upstream 429/5xx plus per-key credit caps and a
`GET /api/v1/key` spend gauge — the failover/semantics fog on map #25 partially
resolves for free. Costs of admission: an aggregator hop (latency; SSE comment lines;
mid-stream `error` events; generation routed to whichever provider passes validation),
and pricing that can drift from direct (sol observed *below* direct — favorable — but
verify at build time). It complements rather than replaces direct Anthropic/OpenAI keys
(maximum fidelity, cache-aware ITPM, first-party rate-limit headers).

## Implications for kultivait

1. **Two native backends + one aggregator covers both client dialects.**
   `RESTBackend` needs: OpenAI-dialect core, an Anthropic-dialect core, and an
   OpenRouter backend that is OpenAI-core + different base URL/auth/cost-extraction.
   Translation code is bounded by the matrix in section (a).
2. **The tools gate can lift for API backends.** Both dialects support full client-side
   tool passthrough (`server.py`'s `tools_unsupported` fallback at `_resolve_tier`
   never needs to fire for these three); the client's agent loop stays the orchestrator
   (ADR 0002) — both APIs return `tool_calls`/`tool_use` and wait.
3. **Effort fitting collapses to one ordinal param** (per-provider value subsets
   aside) — a single `EffortAdapter` for REST backends replaces the four CLI mechanisms;
   hold effort constant within cached conversations.
4. **Cost accounting is asymmetric**: OpenRouter reports USD directly; Anthropic/OpenAI
   report tokens requiring a price table (Anthropic's three-way input split — see (c) —
   and cache multipliers must be honored). The cost-model duality ticket inherits this.
5. **Cache-aware rate limits favor Anthropic for tool-heavy loops** (cache reads exempt
   from ITPM; tool defs are cacheable prefix), and OpenRouter for availability
   (fallback routing). Retry policy: honor `retry-after`/`Retry-After`/`X-RateLimit-Reset`
   per provider; OpenRouter mid-stream errors need a CC-dialect error mapping.
6. **Streaming fidelity**: the two SSE grammars differ in terminator, usage cadence
   (opt-in final chunk vs cumulative `message_delta`), keep-alives (`ping`, `: OPENROUTER
   PROCESSING`), and tool-arg fragment keys (tool_calls index vs block index) — the
   proxy needs a per-dialect event normalizer, not a shared one.

## Sources

- Anthropic Messages API reference: https://docs.anthropic.com/en/api/messages (tool_use/tool_result blocks, tool_choice, thinking config, usage)
- Anthropic tool use: https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/overview
- Anthropic streaming: https://docs.anthropic.com/en/docs/build-with-claude/streaming (input_json_delta, message_delta cumulative usage, ping/error events)
- Anthropic extended thinking: https://docs.anthropic.com/en/docs/build-with-claude/extended-thinking (budget ≥1024 & <max_tokens; 400 on 4.7+/5-series; adaptive migration)
- Anthropic effort: https://docs.anthropic.com/en/docs/build-with-claude/effort (levels, defaults, tool-call effect, cache invalidation)
- Anthropic prompt caching: https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching (usage fields, token-breakdown math, pricing multipliers, per-model minimums)
- Anthropic models: https://docs.anthropic.com/en/docs/about-claude/models/overview (pricing, context, thinking-mode availability)
- Anthropic rate limits: https://platform.claude.com/docs/en/api/rate-limits (tiers, cache-aware ITPM, header table, spend caps)
- OpenAI Chat Completions API reference: https://platform.openai.com/docs/api-reference/chat (tools/tool_choice/tool_calls, chunk delta shape, usage details, stream_options)
- OpenAI reasoning guide: https://platform.openai.com/docs/guides/reasoning (effort values/defaults, Responses preference, pro mode, reasoning-token billing)
- OpenAI pricing: https://platform.openai.com/docs/pricing (standard/batch/flex/fast tables, promo note)
- OpenAI rate limits: https://platform.openai.com/docs/guides/rate-limits (tiers, header table, Retry-After)
- OpenRouter auth: https://openrouter.ai/docs/api-reference/authentication
- OpenRouter usage accounting: https://openrouter.ai/docs/use-cases/usage-accounting (cost/cost_details, always-on usage)
- OpenRouter tool calling: https://openrouter.ai/docs/guides/features/tool-calling (normalized schema, per-call validation, error-rate tracking)
- OpenRouter streaming: https://openrouter.ai/docs/api_reference/streaming (comments, mid-stream errors, X-Generation-Id, cancellation)
- OpenRouter limits: https://openrouter.ai/docs/api_reference/limits (free-variant caps, 429 headers, key introspection)
- OpenRouter live pricing: `GET https://openrouter.ai/api/v1/models` (fetched 2026-08-23)
