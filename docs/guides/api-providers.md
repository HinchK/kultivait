# API providers and prompt caching

Besides local runtimes and CLI backends, kultivait can call the Anthropic,
OpenAI, and OpenRouter REST APIs directly, paying per token.

## Configure an API tier

Add an `api` tier to `~/.kultivait/config.toml`:

```toml
[[tiers]]
name = "anthropic"
role = "architect"
kind = "api"
model = "claude-3-7-sonnet-20250219"
price_in = 3.0
price_out = 15.0

[[tiers]]
name = "openai"
role = "architect"
kind = "api"
model = "gpt-4o"
price_in = 2.5
price_out = 10.0

[[tiers]]
name = "openrouter"
role = "architect"
kind = "api"
model = "anthropic/claude-3.7-sonnet"
price_in = 3.0
price_out = 15.0
```

An API tier without prices gets a conservative default ($3.00 in, $15.00
out per million tokens) and a warning, which keeps the ledger's accounting
accurate.

## Credentials

API keys resolve from three sources, in this order:

1. Environment variables:
   ```bash
   export ANTHROPIC_API_KEY="sk-ant-..."
   export OPENAI_API_KEY="sk-..."
   export OPENROUTER_API_KEY="sk-or-..."
   ```
2. The macOS keychain (`security`, service `kultivait`):
   ```bash
   security add-generic-password -s kultivait -a anthropic -w "sk-ant-..."
   security add-generic-password -s kultivait -a openai -w "sk-..."
   security add-generic-password -s kultivait -a openrouter -w "sk-or-..."
   ```
3. A credentials file, `~/.kultivait/credentials.toml`, with mode `0600`:
   ```toml
   [anthropic]
   api_key = "sk-ant-..."

   [openai]
   api_key = "sk-..."

   [openrouter]
   api_key = "sk-or-..."
   ```

API keys never go in `config.toml`, and kultivait never logs or exposes
them.

> A key can authenticate and pass the route menu's presence probe while the
> account has no credit. OpenRouter then answers every completion with HTTP
> 402. The probe checks authentication, not balance, so make sure the
> account is funded.

## Prompt caching

For pay-per-token providers, kultivait manages prompt caching itself
([ADR 0018](../adr/0018-cache-breakpoints.md), with an amendment to
[ADR 0005](../adr/0005-cost-model-duality.md)). Multi-turn agent loops get
upstream prefix caching without any prompt engineering on your side.

- kultivait is the only cache policy owner. It strips any `cache_control`
  the client sends before translating the request.
- For prompts over 1,024 tokens, it places cache breakpoints at the last
  tool definition (`tools[-1]`) and at the system prompt, so the cached
  prefix survives as the message history grows.
- On OpenRouter it forwards a conversation fingerprint (a hash of the
  system prompt and the first user message) as `session_id`, which steers
  requests toward instances that already hold a warm cache.
- Set `cache_ttl = "5m"` (the default, billed at 1.25× on writes) or `"1h"`
  (2.0×) on any `api` tier. Anthropic bills cache reads at 0.1×. OpenAI
  GPT-4o caches implicitly, and GPT-5.x reads bill at 0.1×. llama.cpp-class
  targets don't cache and report zero cached tokens.

`kultivait harvest` reports what caching saved in its own "cache economics"
block, separate from routing savings and metered cash.

## Related

- [Prompt caching runbook](../superpowers/runbooks/2026-08-25-prompt-caching-runbook.md): configuring and verifying caching and TTLs
- [Prompt caching findings](../superpowers/specs/2026-08-25-prompt-caching-findings.md): measured hit rates and TTL behavior
- [ADR 0010](../adr/0010-key-management-and-onboarding.md): key management
- [ADR 0011](../adr/0011-api-retry-and-failover.md): retries and failover for API tiers
