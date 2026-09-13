# The time ledger: cents-and-minutes duality, length rule routing policy, and season-pinned frontier latency yardsticks

Following Map #212 and the resolution of issues #215 and #216, kultivait extends its cost model beyond financial metrics to a **cents-and-minutes duality**: local dollar savings (ADR 0005) are never complete without disclosing the wall-clock time paid to achieve them. The ledger captures wall-clock duration across all dispatches; the harvest reports time-versus-savings side-by-side against a season-pinned **frontier-latency reference table**; and a structural **length rule** bounds local prefill exposure by rerouting long payloads to frontier models before dispatch.

## Context & Decision

### 1. The Cents-and-Minutes Duality
ADR 0005 separated metered cash from notional value to prevent subscription and free tiers from inflating savings figures. However, routing prompts to local models exchanges dollar spend for developer time: empirical benchmarks (#208) on Apple Silicon revealed 20–89s first-token latency on multi-thousand-token prompts across both Ollama and llama.cpp runtimes. Reporting dollar savings in isolation conceals this operational drag. The ledger therefore introduces a dual-lens accounting model: local financial savings are paired with a signed minutes delta representing the time paid or saved relative to frontier execution. Time is never converted into dollars or blended into financial aggregates; both truths are displayed side-by-side.

### 2. Wall-Clock Ledger Fields
The ledger schema incorporates two wall-clock timing fields across all dispatch paths (OpenAI and Anthropic endpoints, streaming and non-streaming):
- `first_token_ms` (integer milliseconds): Timestamped at the receipt of the first streamed delta chunk. For non-streaming and single-blob CLI dispatches where progressive streaming is unavailable, `first_token_ms` equals the total elapsed time (disclosed in documentation).
- `latency_s` (float seconds): Total wall-clock elapsed duration from request dispatch to final byte transfer.

Existing ledger history is preserved without lossy migration: historical records default `first_token_ms = None` while retaining recorded `latency_s`.

### 3. Frontier-Latency Reference Table
Following the season-wide reference price pattern established in ADR 0005, time comparisons are evaluated **at harvest time** against a stable, season-pinned reference table (`time-v1-20260913-<target>`), rather than baking ephemeral network weather into individual ledger entries at write time (honoring ADR 0020's rule against read-time mutation of historical records).
- **Token Bands**: Requests are partitioned into three prompt token cohorts based on `tokens_in` (lower-inclusive, upper-exclusive): `0–2k`, `2–8k`, and `8k+`.
- **Metrics**: The reference table records median first-token and total durations per band, derived from a committed probe harness (`experiments/latency_probe/`) executing against a named stable reference model class (`claude-sonnet-5`).
- **Configuration & Provenance**: Default medians are shipped in `src/kultivait/time_reference.py` with raw probe samples committed under `experiments/latency_probe/`. Values are overridable via `[time_reference]` in `config.toml`; provenance is immutable.
- **Honest Degradation**: If no frontier credentials or reference values are configured, the harvest outputs `"no reference — local medians only"` without fabricating synthetic baselines (ADR 0017 honesty invariant).

### 4. Time-Never-Ranks Principle
The cash-never-ranks rule (ADR 0005 amendment) extends by name: **time-never-ranks**. Latency metrics, wall-clock fields, and reference tables serve exclusively for observability, reporting, and post-hoc auditing. They are **never** used as inputs to model scoring, candidate ranking, or routing heuristics. Dynamic routing based on transient latency violates the deterministic price-ascending ordering of the route menu (ADR 0003). Any introduction of dynamic latency reranking requires a dedicated ADR. The sole permitted time-derived routing mechanism is the structural length rule defined below.

### 5. Length Rule Routing Policy
To prevent catastrophic prefill stalls, a deterministic routing rule is enforced after verdict resolution but prior to dispatch:
- **Threshold**: `length_rule_max_tokens` (default: **8192** tokens), configured under `[routing]`.
- **Payload Calculation**: Evaluated as `chars // 4` over the **full request payload** (system prompt + user/assistant messages + tool schemas). Tool definitions contribute directly to local attention computation and cannot be omitted.
- **Enforcement**: When an incoming prompt exceeds the threshold, dispatch is forced to the most capable configured **frontier tier regardless of the local verdict**.
- **Operational Invariants**:
  - *No Trolltoll*: The length rule is an invariant structural policy, not a contested human judgment; no trolltoll pause is triggered.
  - *Menu Truncation*: The route menu suppresses its keep-it-local anchor (`local_available=False`), adhering to the capability filter pattern (ADR 0006/0007: drop broken options rather than presenting invalid choices).
  - *Suppressed Escalation*: Because the request was fulfilled by a frontier model, no escalation archive is generated. The record carries `fallback_reason: "length_rule"`.
  - *Local-Only Degradation*: In environments where no frontier provider keys are configured, the system gracefully falls back to local execution with `fallback_reason: "length_rule_no_frontier"`, tracked as an operational counter in harvest metrics.
  - *Policy, Not Tuning*: The 8192-token threshold represents an explicit operational boundary grounded in empirical prefill bounds (14B parameter prefill latency scaling past 30s), not an ad-hoc performance tuning parameter. Default modifications require pre-registered benchmark evidence.

## Considered Options

- **Economic time-value conversion (monetizing minutes into dollars)**: rejected — imputing an hourly dollar rate to developer time is arbitrary, user-dependent, and confounds two distinct physical quantities. Displaying signed minutes paid alongside dollar savings presents both truths orthogonally.
- **Dynamic latency-based route selection (time-ranks)**: rejected — live network and local CPU jitter would cause unstable thrashing between local and cloud providers, breaking the reproducible cost-optimizing guarantees of the routing contract.
- **Per-entry record-time latency reference tagging**: rejected — stamping reference deltas at dispatch time permanently entangles ledger records with transient cloud conditions. Harvest-time evaluation against a season yardstick ensures consistent comparisons across long periods.
- **Excluding tool schemas from length estimation**: rejected — tool definitions in agentic workflows (e.g. Claude Code, Aider) often consume several thousand tokens. Ignoring them led directly to observed multi-minute local hangs.
- **Multi-tier parameter-dependent length caps**: rejected — while smaller local models (e.g. 4B) prefill faster than 14B models, the default local serving target is 14B. A single predictable fleet cap simplifies operational guarantees without creating opaque routing behavior.
- **Synthesizing mock frontier latency when unmeasured**: rejected — violating ADR 0017 to populate display tables with ungrounded numbers compromises project credibility (echoing #139 energy claim removal). The table ships empty until measured; the harvest reports local medians honestly.

## Consequences

- The ledger schema (`src/kultivait/ledger.py`) records `first_token_ms` and `latency_s` on all dispatches; harvest renders the time section with local median/p95 and reference deltas per token band.
- Routing engine (`src/kultivait/server.py`) checks `length_rule_max_tokens` against total payload characters, forcing frontier routing and tagging `fallback_reason = "length_rule"` when tripped.
- Tollbooth UI (`src/kultivait/tollbooth.py`) accepts `local_available=False` to drop the local choice when the length cap is exceeded.
- Configuration (`src/kultivait/config.py`) exposes `length_rule_max_tokens` (default 8192) and `[time_reference]` overrides.
- Reference module (`src/kultivait/time_reference.py`) provides band definitions (`0–2k`, `2–8k`, `8k+`) and reference table storage; probe harness lives in `experiments/latency_probe/`.
- CONTEXT.md canonizes **Time ledger**, **Length rule**, and **Frontier-latency reference table**.
- Test suite verifies length rule routing, ledger recording, and harvest invariants across 16 dedicated hermetic tests (`tests/test_time_ledger.py`).
