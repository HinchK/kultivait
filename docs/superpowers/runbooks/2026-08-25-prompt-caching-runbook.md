# Prompt Caching Operational Runbook & Telemetry Guide

**Date**: 2026-08-25  
**Scope**: Proxy-owned prompt caching architecture, live proxy verification (Map #74 Issue #85), and harvest telemetry reading.  
**Relevant ADRs**: [ADR 0018](../../adr/0018-cache-breakpoints.md), [ADR 0005](../../adr/0005-cost-model-duality.md).

---

## 1. Overview & Architectural Principles

Kultivait provides automatic, proxy-owned prompt caching for pay-per-token API frontier providers without requiring manual client prompt adjustments or tool modifications.

### Core Principles
1. **Proxy as Sole Policy Owner**: Clients may send arbitrary `cache_control` annotations. The proxy recursively strips all incoming client cache markers and injects canonical breakpoints deterministically.
2. **Dual-Level Breakpoint Placement**: Injects explicit breakpoints at two stable boundaries:
   - **Level 1 (Tools)**: Attached to the last tool definition (`tools[-1]`).
   - **Level 2 (System)**: Attached to the hoisted system prompt block.
3. **Session Stickiness**: For OpenRouter dispatches, the `conversation fingerprint` (hash of system prompt and initial user message) is forwarded as upstream `session_id` to route requests to the same physical cache worker.
4. **Presence Probe Bypass**: Cache-bearing dispatches skip presence probes to preserve sticky session continuity.
5. **Silent Sub-Minimum Skip**: Prompts below `MIN_CACHE_PREFIX_TOKENS` (1,024 tokens) bypass caching silently without error.

---

## 2. Live Proxy Verification Results (Issue #85 C4)

The end-to-end proxy pipeline was validated live against OpenRouter (`anthropic/claude-sonnet-5`) over a 6-turn multi-turn agent conversation with a stable ~2.4k-token prefix.

### Execution Summary
- **Total Spend**: ~$0.05 (account balance remaining: $7.67).
- **Dispatches**: 6 cache-bearing dispatches through `kultivait serve`.
- **Live Harvest Telemetry**:
  ```
  cache economics
    kept via cache     $0.0093
    hit rate           40%  (6 cache-bearing dispatches)
    reads per write    1.0
    ttl cohorts        5m: 6 dsp $0.0093
  ```

---

## 3. Placement Settlement: Dual-Level vs. System-Only

The live proxy run settled the cache stability anomaly discovered during the Issue #78 probe:

| Placement Strategy | Multi-Turn Cache Behavior | Observed Pattern | Architectural Verdict |
|---|---|---|---|
| **System-Only** (Issue #78) | t1: write, t2: **HIT**, t3: **HIT**, t4: miss, t5: miss, t6: miss | **Terminal Collapse**: Cache permanently lost after turn 3 despite unchanged prefix. | **Rejected**: Left agent paying full input price indefinitely. |
| **Dual-Level** (Issue #85) | t1: write, t2: write, t3: **HIT**, t4: write, t5: **HIT**, t6: **HIT** | **Sustained Hits**: Cache hits persist through turn 6; occasional re-writes at cheap 1.25x surcharge. | **Adopted**: Completely prevents terminal collapse; bounds costs. |

Dual-level placement anchors both the tool schemas and system instructions independently. As conversation history grows, upstream translation shifts cannot displace the tool schema cache boundary.

---

## 4. Harvest Telemetry Reading Guide

Kultivait maintains three **orthogonal** cost accounting lenses:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ 1. Kept-in-Pocket (Routing Lens)                                            │
│    baseline_usd - notional_usd                                              │
│    Value preserved by routing trivial/reasoning work to local models.       │
├─────────────────────────────────────────────────────────────────────────────┤
│ 2. Metered Cash Out (Cash Lens)                                             │
│    cost_usd (from provider usage.cost or pinned price math)                 │
│    Actual dollar bills owed to pay-per-token API providers.                 │
├─────────────────────────────────────────────────────────────────────────────┤
│ 3. Kept-via-Cache (Caching Lens)                                            │
│    Σ (reads * 0.9 * price - writes * (mult - 1.0) * price) / 1,000,000      │
│    Net dollars saved exclusively from upstream prompt cache hits.           │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Telemetry Field Definitions

1. **`kept via cache` ($)**:
   - Net dollar savings from prompt caching across all cache-bearing dispatches.
   - Calculates the 90% read discount minus the TTL write surcharge (1.25× for 5m, 2.0× for 1h).
   - If writes exceed reads, negative nets are reported honestly.
2. **`hit rate` (%)**:
   - `total_cache_read_tokens / total_tokens_in` over cache-bearing dispatches.
   - Uses total input tokens (`tokens_in`) as denominator without double-counting reads.
3. **`reads per write`**:
   - `total_cache_read_tokens / total_cache_write_tokens`.
   - Indicates cache amortization efficiency. At 5m TTL (1.25× write surcharge and 0.10× read rate), break-even occurs at **1.4 reads per write**.
4. **`ttl cohorts`**:
   - Splits dispatches and `kept-via-cache` dollars by retention window (`5m` vs `1h`).

---

## 5. Configuration & Operational Runbook

### Configuring Caching on API Tiers
Add `cache_ttl` to your API tier in `~/.kultivait/config.toml`:

```toml
[[tiers]]
name = "claude-frontier"
role = "architect"
kind = "api"
model = "anthropic/claude-3.7-sonnet"
price_in = 3.0
price_out = 15.0
cache_ttl = "5m"      # "5m" (1.25x write surcharge) or "1h" (2.0x write surcharge)
```

### Verifying Cache Operation in Production
1. **Check Live Harvest**:
   ```bash
   kultivait harvest
   ```
   Confirm the `cache economics` block appears once multi-turn agent activity commences.

2. **Inspect Structured JSON**:
   ```bash
   kultivait harvest --json | jq .cache
   ```
   Expected JSON schema:
   ```json
   {
     "dispatches": 6,
     "kept_via_cache_usd": 0.0093,
     "cache_hit_rate": 0.4,
     "cache_reads_per_write": 1.0,
     "cache_ttl_cohorts": {
       "5m": {
         "dispatches": 6,
         "kept_via_cache_usd": 0.0093
       }
     }
   }
   ```

3. **Inspect Ledger Records**:
   ```bash
   tail -n 10 ~/.kultivait/ledger.jsonl | jq 'select(.cache_read_tokens != null or .cache_write_tokens != null)'
   ```
   Verify entries carry `cache_read_tokens`, `cache_write_tokens`, `cache_ttl`, and `cache_price_in`.

### Troubleshooting

- **No Cache Section in Harvest**:
  - Check prompt length: prompts under 1,024 tokens bypass caching silently (`MIN_CACHE_PREFIX_TOKENS`).
  - Verify tier kind: only `api`-kind tiers support provider prompt caching.
- **Low Hit Rate / Frequent Re-Writes**:
  - Verify that tool definitions remain stable across turns. Changing a tool schema invalidates level 1 cache.
  - Verify turn cadence: turns separated by >5 minutes require `cache_ttl = "1h"`.
