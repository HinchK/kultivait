# Cache breakpoints: proxy-owned at the stable prefix, Anthropic-form canonical, 5m default

The proxy inserts provider prompt-cache breakpoints on the stable agent-loop prefix — the tools array + system prompt at the tools→messages boundary — at translation time, per provider, before dispatch. Clients never carry `cache_control` through (stripped; the proxy is the single cache-policy owner). The canonical internal form is Anthropic-style block-level `cache_control`: passed verbatim to OpenRouter (whose translator reaches all upstream families), native on direct Anthropic, self-translated to `prompt_cache_breakpoint`/`prompt_cache_options` on direct OpenAI (GPT-5.6+; TTLs never ride toward OpenAI). Prefixes below per-model minimums insert nothing, silently, logged once per conversation. TTL defaults to 5m (write amortizes on turn 2 of a fast loop); 1h (2× write) is a config opt-in for known long-running sessions, recorded per-conversation in the ledger. The conversation fingerprint (hash of system + first user message) is the cache key, forwarded as OpenRouter `session_id` on cache-bearing dispatches; interleaved conversations isolate by fingerprint, shared-prefix collisions are legitimate hits, and cache-bearing dispatches skip the presence probe to preserve stickiness. Grounded in the cache-landscape findings (#75): `experiments/cache-landscape.md`.

## Considered Options

- **Client-honored passthrough** (honoring client-sent `cache_control` headers): rejected — creates non-uniform cache policies across different agent harnesses and leaks client-specific caching details into backend dispatch; the proxy is the single cache-policy owner.
- **Per-backend translation logic everywhere** (letting each backend reinvent breakpoint placement): rejected — Anthropic-form block-level `cache_control` serves as a universal canonical representation; OpenRouter's upstream translation already maps to OpenAI and Google formats without per-backend duplication.
- **Passthrough-first routing** (forwarding raw client cache headers directly): rejected — violates proxy abstraction; client-sent `cache_control` headers are stripped so proxy breakpoint placement remains deterministic.
- **System-only breakpoint placement** (caching only the system prompt and omitting tools): rejected — the tools array is level 1 in the prefix hierarchy and anchors agent loops; changing tool definitions invalidates everything below, so the breakpoint must sit at the tools→messages boundary.
- **5m-only TTL hardcoded** (no configurable TTL): rejected — ignores long-running architect sessions where turns exceed 5 minutes and amortize over a 1-hour window.
- **1h-always default TTL**: rejected — imposes a 2× write surcharge on typical fast agent loops that amortize on turn 2 under the 5m 1.25× write rate.
- **Separate cache key mechanism** (inventing a new session/cache tracking identifier): rejected — the conversation fingerprint already uniquely identifies the conversation prefix and maps 1:1 to OpenRouter's `session_id` routing.
- **Implicit-only caching** (relying purely on provider auto-caching without explicit breakpoints): rejected — misses explicit cache guarantees on Anthropic and OpenRouter endpoints where explicit breakpoint markers anchor prefix boundaries.

## Consequences

- The proxy dispatch path injects Anthropic-style block-level `cache_control` on the tools + system prompt prefix for payloads exceeding model minimum token thresholds.
- Client-provided cache controls are stripped at the proxy ingress.
- `conversation fingerprint` acts directly as the cache key and is forwarded as `session_id` on OpenRouter dispatches to anchor sticky prompt caching routes.
- Cache-bearing dispatches skip the presence probe to avoid breaking upstream sticky session affinity.
- Unblocks Issue #78 (Cache-probe) to validate prefix write-then-read behavior across serialized identical-prefix dispatches.
- Downstream accounting (#77) inherits per-conversation TTL tracking and addresses #75's identified code gaps: tracking `cache_write_tokens`, making the 1.25× write multiplier TTL-aware (2× for 1h), and retiring stale beta header requirements.
- Term canonized in CONTEXT.md: **Cache breakpoint**.
