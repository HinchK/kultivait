# Prompt Caching Empirical Findings — Live Probe & Amortization

**Date**: 2026-08-25  
**Map / Ticket**: Issue #78 (Cache-probe live verification under ADR 0018 & ADR 0005)  
**Artifacts**: `/tmp/cache-probe/summary.json`  
**Total Probe Spend**: $0.089  

---

## 1. Environment & Probe Setup

This evaluation tested the prompt caching architecture specified in [ADR 0018](docs/adr/0018-cache-breakpoints.md) against live pay-per-token frontier providers via OpenRouter. 

### Probe Parameters
- **Prefix Structure**: A stable ~4.6k-token agent prefix consisting of tools definitions array + system prompt (exceeding provider minimum token thresholds).
- **Cache Breakpoint Placement**: Injected at the tools→messages boundary per ADR 0018 canonical Anthropic block-level `cache_control` specification.
- **Session Identity**: `conversation fingerprint` forwarded as OpenRouter `session_id` to enforce upstream sticky routing.
- **Probe Cadence**: 6 sequential multi-turn requests per model with ~2s turn intervals (well within the 5m TTL horizon).
- **Presence Probe**: Bypassed on cache-bearing dispatches per ADR 0018 to preserve sticky upstream routing affinity.

---

## 2. Per-Model Results

### A. `claude-sonnet-5` (`anthropic/claude-sonnet-5`, $2.00 / $10.00 per MTok)
- **Turn 1 (Write)**: Uncached write. Full prompt cost $0.012376 at 5.18s latency.
- **Turns 2–3 (Hits)**: Exact 4,600 token cache read hits. Cost dropped to $0.001902–$0.001972 (**6.5× cheaper**; ~84% input discount), latency improved to 3.58–3.91s.
- **Turns 4–6 (Misses / Instability)**: Cache was dropped on unchanged prefix; cost reverted to full uncached pricing ($0.012552).

| Turn | HTTP | Latency (s) | Prompt Tokens | Cached Tokens | Cost (USD) | Cache Status |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| 1 | 200 | 5.18 | 4,738 | 0 | $0.012376 | MISS (Write) |
| 2 | 200 | 3.91 | 4,791 | 4,600 | $0.001902 | **HIT** (4.6k tokens) |
| 3 | 200 | 3.58 | 4,826 | 4,600 | $0.001972 | **HIT** (4.6k tokens) |
| 4 | 200 | 3.79 | 4,826 | 0 | $0.012552 | MISS (Lost) |
| 5 | 200 | 3.01 | 4,826 | 0 | $0.012552 | MISS (Lost) |
| 6 | 200 | 6.69 | 4,826 | 0 | $0.012552 | MISS (Lost) |

---

### B. `gpt-4o` (`openai/gpt-4o`, $2.50 / $10.00 per MTok)
- **Behavior**: Steady implicit prompt caching across 5 of 6 turns.
- **Economics**: Input costs dropped ~1.7× ($0.00622 $\rightarrow$ $0.00347–$0.00413), with 2,304 cached tokens on turns 2, 3, 5, and 6 (1,792 on turn 4).
- **Write Surcharge**: No explicit 1.25× write premium billed (implicit caching model).

| Turn | HTTP | Latency (s) | Prompt Tokens | Cached Tokens | Cost (USD) | Cache Status |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| 1 | 200 | 1.01 | 2,409 | 0 | $0.006223 | MISS |
| 2 | 200 | 0.76 | 2,444 | 2,304 | **HIT** (2.3k tokens) |
| 3 | 200 | 1.55 | 2,471 | 2,304 | **HIT** (2.3k tokens) |
| 4 | 200 | 0.89 | 2,471 | 1,792 | **HIT** (1.8k tokens) |
| 5 | 200 | 0.81 | 2,471 | 2,304 | **HIT** (2.3k tokens) |
| 6 | 200 | 0.95 | 2,471 | 2,304 | **HIT** (2.3k tokens) |

---

### C. `llama-3.3-70b` (`meta-llama/llama-3.3-70b-instruct`, $0.10 / $0.32 per MTok)
- **Behavior**: Zero cache fields reported across all successful turns.
- **Provider Stability**: Turns 5 and 6 failed with HTTP 429 upstream rate limits from the underlying provider.
- **Conclusion**: The Llama 3.3 anchor does not exhibit observable prompt caching benefits via OpenRouter.

| Turn | HTTP | Latency (s) | Prompt Tokens | Cached Tokens | Cost (USD) | Cache Status |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| 1 | 200 | 1.02 | 3,505 | 0 | $0.002552 | Uncached |
| 2 | 200 | 1.33 | 3,543 | 0 | $0.002570 | Uncached |
| 3 | 200 | 0.71 | 3,572 | 0 | $0.002591 | Uncached |
| 4 | 200 | 0.79 | 3,572 | 0 | $0.002601 | Uncached |
| 5 | 429 | 0.33 | — | — | $0.000000 | Rate limited |
| 6 | 429 | 0.29 | — | — | $0.000000 | Rate limited |

---

## 3. Amortization Analysis

When explicit prompt caching hits (observed on `claude-sonnet-5`):
- **Base Input Rate**: $2.00 / MTok ($0.002 / kTok).
- **Cache Read Rate**: $0.20 / MTok ($0.0002 / kTok, 90% discount).
- **Cache Write Surcharge (5m TTL)**: 1.25× base rate = $2.50 / MTok ($0.0025 / kTok).
- **One-Time Write Surcharge**: 4,600 tokens $\times$ $0.0005/kTok = **$0.00230** (total write cost $0.01150).
- **Per-Turn Read Savings**: 4,600 tokens $\times$ $0.0018/kTok = **$0.00828** saved per hit.
- **Break-Even Horizon**:
  $$\text{Break-Even} = \frac{\text{Write Surcharge}}{\text{Per-Turn Savings}} = \frac{\$0.00230}{\$0.00828} \approx 0.28 \text{ turns}$$
  Including the base turn cost, amortization is achieved on **turn 2** (1.4 total turns).

---

## 4. The Claude Instability Finding

The primary architectural insight yielded by the probe:
- **Observation**: `claude-sonnet-5` registered clean 4.6k-token cache hits on turns 2 and 3 within 2 seconds of each other, but completely lost the cache on turns 4, 5, and 6 despite the prefix remaining strictly byte-identical and well within the 5-minute TTL.
- **Suspected Causes**:
  1. **OpenRouter Translation Drift**: As multi-turn message history accumulates, OpenRouter's dialect translation from OpenAI/Anthropic structures into upstream Anthropic API payloads may shift the relative position or index of the injected `cache_control` block.
  2. **Breakpoint Collision / Ordering**: Anthropic allows up to 4 explicit breakpoints; if conversation turns inadvertently append markers or shift array boundaries, upstream prefix hashing invalidates.
- **Action for Build / Implementation**:
  - Audit OpenRouter payload serialization as history grows.
  - Verify if pinning explicit breakpoints on both the tools definition block AND the system message (or moving the single breakpoint strictly to the last system block) improves downstream stability across deep multi-turn sessions.

---

## 5. Architectural Implications for Kultivait

1. **Dual-Track Cost Accounting (#77)**:
   - Upstream usage payloads return distinct dialect shapes: OpenRouter/OpenAI emits `cached_tokens` in `usage.prompt_tokens_details`, while native Anthropic emits `cache_read_input_tokens` and `cache_creation_input_tokens`.
   - Backends normalize these into canonical `cache_read_tokens`, `cache_write_tokens`, and `cache_ttl` extras in `ledger.jsonl`.
   - `kept-via-cache` calculates actual cash and notional discounts separately as a third harvest metric.
2. **Provider Route Profiles**:
   - `openai/gpt-4o`: Reliable implicit caching without write surcharges.
   - `anthropic/claude-sonnet-5`: High potential savings (6.5× on hits) subject to breakpoint stability.
   - `meta-llama/llama-3.3-70b-instruct`: Cache-blind anchor; cost accounting records $0 cache discounts.
3. **Route Menu Invariant**:
   - Reaffirms ADR 0005 amendment: cache-effective pricing is purely an observability metric in the harvest. Route menu total order (judge fit $\rightarrow$ capability match $\rightarrow$ notional price $\rightarrow$ target ID) remains strictly based on standard un-discounted notional price.

---

## 6. Caveats & Scope

- **Sample Size**: $n = 6$ turns per target backend across a single session.
- **Cadence**: Turns dispatched at ~2s intervals (rapid agent loop simulation).
- **Prefix Shape**: Single 4.6k-token tool+system prefix tested.
- **Rate Limits**: Upstream provider 429s on Llama 3.3 limited turns 5–6 data collection.
