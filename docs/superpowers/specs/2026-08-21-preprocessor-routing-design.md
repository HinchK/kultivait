# Preprocessor routing, hybrid route menu, and orchestration — design

Date: 2026-08-21
Branch: main (wayfinder map #4)
Status: approved via wayfinder map #4 (issues #5–#14)

> Historical note (2026-09-03): shipped via maps #4/#25 with a drifted tail — Anthropic `/v1/messages` tool calling has since SHIPPED, and `docs/API.md` plus the `[preprocess]`/`[effort]` sections were never created (config is documented in the README). Kept as the design record.

## Problem

Kultivait currently resolves tiers statically using embedding distance calculations against role centroids (`server.py:_classify`, `server.py:_resolve_tier`). This approach has three key limitations:
1. **Coarse routing decisions**: Thin-margin requests cannot evaluate prompt nuances (task complexity, specific tool needs, documentation freshness requirements) before routing, risking silent local downgrades or unnecessary frontier spends.
2. **Missing interactive human agency**: When routing is ambiguous (contested between local and frontier capacity), the proxy cannot hold the turn to present a route choice with fitted model effort across installed CLIs.
3. **Compound prompt friction**: Multi-step, compound, and tool-bearing prompts lack structured decomposition into sub-task candidates, forcing the caller's agent loop to either manage orchestration without guidance or bear full frontier cost for simple intermediate steps.

## Goal

Extend kultivait into a three-layer intelligent routing architecture:
1. **Local Preprocessor**: A single-call analyze $\to$ rewrite $\to$ judge pass running on the simple local tier (`preprocess_model`, default `qwen3.5:4b`) gated by embedding margin, deriving structured verdicts and per-target prompt rewrites.
2. **Hybrid Route Menu & Tollbooth**: When a routing verdict is contested, hold the HTTP request via a **trolltoll** (up to 60s, presence-gated), presenting a **route menu** of the top three installed frontier CLI targets (ranked by fit, capability, price) plus a keep-it-local anchor, with canonical effort projected onto per-CLI adapters. In headless mode or on timeout, dispatch via local-first **auto-policy** and archive missed choices escalation-style.
3. **In-Band Orchestration**: Fit model selection and effort at request and sub-task boundaries as calls cross the proxy, decomposing compound prompts into in-band **sub-task candidates** (`kultivait_meta`), managing context fluctuation via `gates.py` compost briefs, and maintaining the caller's agent loop as the orchestrator without autonomous CLI worker dispatch.

## Decisions made

| Decision / Issue | Choice | Artifact / ADR |
|---|---|---|
| [#5 CLI capabilities](https://github.com/Standard-Pentest/kultivait/issues/5) | 5 CLIs drivable non-interactively; `codex exec` and `opencode run` subcommands; 4 effort projection mechanisms; real-usage reporting for Claude/Codex | `experiments/cli-capability-matrix.md` |
| [#6 Trolltoll hold](https://github.com/Standard-Pentest/kultivait/issues/6) | Contested+boundary triggers only; 60s presence-gated hold; pending-tolls queue with 2 faces (TTY tollbooth, `kultivait choose`); sticky per conversation fingerprint; late answers as ledger counterfactuals | [ADR 0001](../../adr/0001-trolltoll-holds-requests.md) |
| [#7 Preprocessor contract](https://github.com/Standard-Pentest/kultivait/issues/7) | Single-call analyze/rewrite/judge; simple-tier default; verdict derived structurally (local < 0.65, frontier ≥ 0.85, contested between); per-target rewrite; latency budget p50 ≤ 8s, cap 15s; parse failure fails open to trolltoll | [Decision #7](https://github.com/Standard-Pentest/kultivait/issues/7) |
| [#8 Preprocessor probe](https://github.com/Standard-Pentest/kultivait/issues/8) | Live probe validated 12/12 parse on both tiers; `local_sufficient` boolean untrusted; margin skip-gate validated | `experiments/preprocessor_probe.py` |
| [#9 Route menu & targets](https://github.com/Standard-Pentest/kultivait/issues/9) | Top 3 installed CLIs by total order (fit desc $\to$ capability $\to$ price asc) + local anchor; fitted effort per option; keep-it-local archives escalation-style; local-first auto-policy on toll expiry; codex/opencode registered in `KNOWN_CLIS`/`CLI_PRICING` | [ADR 0003](../../adr/0003-route-menu-and-frontier-targets.md) |
| [#10 Orchestration shape](https://github.com/Standard-Pentest/kultivait/issues/10) | Fit at boundaries, plan in-band, never dispatch; client loop stays orchestrator; compound prompts emit sub-task candidates in `kultivait_meta`; boundary re-fit via pipeline re-entry; context fluctuation via `gates.py` compost briefs; ledger gains orchestrator/worker fields | [ADR 0002](../../adr/0002-orchestration-fit-at-boundaries.md) |
| [#13 Effort mapping](https://github.com/Standard-Pentest/kultivait/issues/13) | Effort = complexity band (1–3/4–6/7–9 $\to$ fast/balanced/deep) $\times$ task_type modifier; fit/confidence excluded from effort; no-signal default balanced; code-first in `effort.py` with TOML overrides | [Decision #13](https://github.com/Standard-Pentest/kultivait/issues/13) |
| [#14 Threshold eval](https://github.com/Standard-Pentest/kultivait/issues/14) | Held-out 12-case eval: KEEP provisional $[0.65, 0.85)$ thresholds; 0 dangerous errors in 24 runs; `qwen3.5:4b` latency (p50 6.89s, max 8.94s) validates simple-tier default (`qwen3:14b` p50 15.43s breaches); calibration caveat noted for build | `experiments/verdict-eval-report.md` |

## Research & empirical findings

1. **CLI Capability Matrix (#5)**:
   - `claude`: `claude -p <prompt>`, `--effort low|medium|high|xhigh`, real token/cost reporting in JSON mode.
   - `agy`: `agy -p <prompt>`, `--effort low|medium|high` (and effort-suffixed model aliases), token estimation fallback.
   - `gemini`: `gemini -p <prompt>`, effort mapped via custom model aliases in `settings.json` (`thinkingLevel`/`thinkingBudget`), token estimation fallback.
   - `codex`: `codex exec <prompt>` (no `-p` — `-p` means `--profile`), `-c model_reasoning_effort="minimal|low|medium|high|xhigh"`, real token reporting in JSONL events.
   - `opencode`: `opencode run <prompt>` (no `-p` — `--prompt` opens TUI), `--variant <effort>`, multi-provider credentials.
2. **Preprocessor Probe & Held-Out Eval (#8, #14)**:
   - Evaluated against live local Ollama across 12 cases (6 probe + 6 held-out):
     - `qwen3.5:4b` (simple tier): 100% parse ok (12/12), 0 dangerous errors, 0 toll rate at $[0.65, 0.85)$, p50 latency 6.89s ($\le 8.0\text{s}$ budget), max latency 8.94s ($\le 15.0\text{s}$ cap).
     - `qwen3:14b` (reasoning tier): 100% parse ok (12/12), 0 dangerous errors, 25% toll rate, p50 latency 15.43s (breaches budget), max latency 18.86s.
   - Diagnostic validation: `local_sufficient` boolean contradicted target fits on 10 of 12 cases on `qwen3.5:4b`, proving that deriving verdicts structurally from target fits is mandatory.
   - Build-effort calibration note: Small local models score target capabilities generously (fits clustering $\ge 0.85$); prompt fit scale calibration is flagged for the build effort.

## Architecture

```
HTTP Request (/v1/chat/completions)
  │
  ├─ 1. Embed last user message & compute margin (router.py)
  │      ├─ Fat margin (uncontested) ──► Skip Preprocessor ──► Router Verdict
  │      └─ Contested / Boundary ─────► 2. Preprocessor Pass (preprocessor.py)
  │                                           │ (qwen3.5:4b, single call, ≤8s p50)
  │                                           ├─ Parse fail / Timeout ──► Fail open
  │                                           └─ Structured output:
  │                                                ├─ Sub-task candidates (for compound)
  │                                                ├─ Per-target prompt rewrites
  │                                                └─ Derived Verdict (max fit)
  │
  ├─ 3. Route Resolution & Trolltoll (server.py / tollbooth.py)
  │      ├─ Verdict == "local" ───► Dispatch Local Backend (backends.py)
  │      ├─ Verdict == "frontier" ─► Dispatch Top Frontier CLI (CLIBackend)
  │      └─ Verdict == "contested" ──► Trolltoll Triggered (Hold request ≤60s)
  │                                         │
  │                                         ├─ Presence active (TTY tollbooth / `kultivait choose`):
  │                                         │    ├─ Option 1..3: Top installed CLIs (fitted effort + rewrite)
  │                                         │    └─ Option 4: Keep-it-local (original prompt, escalation archive)
  │                                         │
  │                                         └─ Headless / Timeout (Auto-Policy):
  │                                              ├─ Local serving-capable ──► Dispatch Local
  │                                              └─ Local incapable ────────► Dispatch Top Frontier
  │
  └─ 4. Ledger & In-Band Metadata Response
         ├─ Append `kultivait_meta` (verdict, margin, subtask_candidates, fitted effort)
         └─ Record enriched entry in ~/.kultivait/ledger.jsonl
```

### Module Layout & Dataclass Shapes

#### `src/kultivait/preprocessor.py` (New Module)

Clones the template-driven local generation pattern from `cli.py:_distill_generate_for` and `gates.py:Gate`.

```python
@dataclass(frozen=True)
class TargetFit:
    target: str          # "claude" | "agy" | "gemini" | "codex" | "opencode"
    fit: float           # 0.0 - 1.0
    effort: str          # "low" | "medium" | "high"

@dataclass(frozen=True)
class AnalysisResult:
    task_type: str       # "simple_edit" | "debugging" | "architecture" | "docs_lookup" | "compound" | "underspecified"
    complexity: int      # 1 - 9
    signals: list[str]
    subtask_candidates: list[str] = field(default_factory=list)

@dataclass(frozen=True)
class PreprocessResult:
    analysis: AnalysisResult
    rewrite: str
    target_fits: list[TargetFit]
    max_fit: float
    derived_verdict: str   # "local" | "frontier" | "contested"
    confidence: float
    raw_output: dict | None
    latency_s: float
    mark: str              # "ok" | "preprocess_timeout" | "preprocess_fail" | "skipped"
```

#### `src/kultivait/effort.py` (New Module)

Pure function resolving abstract effort from preprocessor complexity and task type, with projection onto per-CLI mechanisms.

```python
@dataclass(frozen=True)
class EffortPlan:
    canonical: str         # "fast" | "balanced" | "deep"
    cli_flags: list[str]   # e.g. ["--effort", "high"] or ["-c", "model_reasoning_effort=high"]
    model_override: str | None = None  # e.g. for agy/gemini alias selection

def resolve_effort(
    complexity: int,
    task_type: str,
    target_cli: str,
    overrides: dict | None = None,
) -> EffortPlan:
    """Complexity band (1-3: fast, 4-6: balanced, 7-9: deep) scaled by task_type modifier,
    projected through target CLI adapter."""
    ...
```

#### `src/kultivait/tollbooth.py` (New Module)

Manages the in-flight pending tolls queue, presence detection, TTY tollbooth chooser rendering, and headless auto-policy drain.

```python
@dataclass(frozen=True)
class RouteOption:
    target: str            # "claude" | "agy" | "codex" | "opencode" | "gemini" | "local"
    display_name: str
    fit: float
    effort: EffortPlan
    estimated_cost_usd: float
    prompt_to_send: str    # rewritten prompt for frontier, original for local

@dataclass(frozen=True)
class TollTicket:
    ticket_id: str
    fingerprint: str
    created_at: float
    timeout_s: float
    options: list[RouteOption]
    default_auto_choice: str
```

### Per-CLI Adapter Table

| CLI Target | Role Class | Dispatch Command Template | Effort Mechanism | Real Usage Reported | Pricing Baseline (In / Out per Mtok) |
|---|---|---|---|---|---|
| `claude` | `architect` | `["claude", "-p", "{prompt}"]` | `--effort low\|medium\|high\|xhigh` | Yes (`usage`, `total_cost_usd`) | $3.00 / $15.00 |
| `agy` | `docs` | `["agy", "-p", "{prompt}"]` | `--effort low\|medium\|high` / model suffix | No (~4 chars/token) | $1.25 / $10.00 |
| `gemini` | `docs` | `["gemini", "-p", "{prompt}"]` | Config aliases (`thinkingLevel`/`thinkingBudget`) | No (~4 chars/token) | $1.25 / $10.00 |
| `codex` | `architect` | `["codex", "exec", "{prompt}"]` | `-c model_reasoning_effort="minimal\|low\|medium\|high\|xhigh"` | Yes (`turn.completed` usage) | $1.25 / $10.00 |
| `opencode` | `architect` | `["opencode", "run", "{prompt}"]` | `--variant <effort>` | No (~4 chars/token) | $3.00 / $15.00 *(multi-provider default)* |

### Tollbooth Chooser Surfaces
1. **Interactive TTY Chooser (`serve` TTY)**: When `kultivait serve` runs connected to an active TTY, the tollbooth renders inline rich cards showing the route menu: top 3 installed CLIs ranked by total order (fit desc $\to$ capability match $\to$ price asc) with fitted effort, plus the keep-it-local anchor. Keys `[1-4]` select; `[e]` overrides effort.
2. **Out-of-Band Chooser (`kultivait choose`)**: When headless, a detached TTY client connects to the shared pending queue file (`~/.kultivait/pending_tolls.jsonl`), providing a heartbeat signal within 5 minutes.
3. **Headless Auto-Policy**: If no reachable human is present or the 60s hold expires, auto-policy selects local if serving-capable, else the top-ranked frontier option. The missed route menu, selected choice, and reason archive escalation-style. Late responses record counterfactual records in the ledger and never re-dispatch.

### Ledger & Harvest Schema Extensions

Additive optional fields on `Ledger.record(..., **extra)` in `~/.kultivait/ledger.jsonl` (note: `ts` from `ledger.py` and `fingerprint` form the identity pair for correlating re-fits within a conversation):

```json
{
  "ts": 1755864120.5,
  "fingerprint": "a1b2c3d4e5f6",
  "tier": "claude",
  "local": false,
  "tokens_in": 1250,
  "tokens_out": 450,
  "cost_usd": 0.0105,
  "preprocess_mark": "ok",
  "verdict": "contested",
  "max_fit": 0.82,
  "target_fits": {
    "claude": 0.82,
    "codex": 0.75,
    "agy": 0.60
  },
  "canonical_effort": "balanced",
  "cli_effort_flags": ["--effort", "medium"],
  "toll": "answered",
  "route_choice": "human:frontier:claude",
  "subtask_candidates": 3,
  "orchestrator": "claude-code",
  "worker": "agy-gemini-3.7-flash",
  "experiment_id": "exp_2026-08-21_coding_v1",
  "task_type": "coding",
  "duration_seconds": 18.4,
  "test_passed": true,
  "estimated_cost_usd": 0.038,
  "actual_cost_usd": 0.0105,
  "savings_usd": 0.0275
}
```

`kultivait harvest` extensions:
- Outputs a **Toll Activity** summary: total contested requests, toll rate %, human answered count vs auto-policy expired count, and route-choice breakdown (`human:local`, `human:frontier`, `auto:local`, `auto:frontier`).
- Preserves cumulative financial savings and escalation brief tallies.

## Error handling summary

| Failure Condition | System Behavior |
|---|---|
| Preprocessor timeout (>15s) | Falls back immediately to embedding router verdict; marks `preprocess_mark: "preprocess_timeout"`; balanced effort default. |
| Preprocessor JSON parse failure | Fails open to the human via trolltoll hold; marks `preprocess_mark: "preprocess_fail"`; balanced effort default. |
| Ollama / simple tier offline | Margin skip-gate bypasses preprocessor; falls through directly to router tier resolution. |
| Tollbooth hold expires (60s) | Dispatches via auto-policy (local-first); archives missed route menu escalation-style; marks `toll: "expired"`. |
| CLI subprocess dispatch failure | Catches execution error, returns structured 502/500 error response to caller; preserves standard `CLIBackend` error path. |
| Judge fit fields missing/invalid | Treats target fit as 0.0 (router fallback); effort defaults to canonical balanced. |
| Server shutdown with pending tolls | In-flight held requests terminate with connection close; queue file is cleaned statelessly on next startup (no lingering stale holds). |

## Testing

Per the repository's convention, all tests execute hermetically without live subprocess, network, or Ollama requirements (mocked backends, injected fakes, `tmp_path` fixtures).

- `tests/test_preprocessor.py`:
  - Fixture testing for analyze $\to$ rewrite $\to$ judge prompt generation.
  - JSON extraction edge cases: fenced markdown, leading/trailing prose blurts, malformed syntax.
  - Derived verdict computation: local (<0.65), frontier ($\ge 0.85$), contested.
  - Timeout and fail-open paths (`preprocess_timeout`, `preprocess_fail`).
- `tests/test_effort.py`:
  - Pure function testing of `resolve_effort()` across all complexity bands and task type modifiers.
  - Per-CLI adapter projection for `claude`, `agy`, `gemini`, `codex`, `opencode`.
  - TOML configuration override parsing.
- `tests/test_tollbooth.py`:
  - Queue operations: push, drain, timeout expiration.
  - Route menu ranking order: fit desc $\to$ capability match $\to$ price asc.
  - Presence gating logic (serve TTY vs heartbeat client).
  - Headless auto-policy selection (local-first vs fallback to top frontier).
  - Sticky fingerprint cache hits and TTL expirations.
- `tests/test_backends_cli.py`:
  - Verification of per-CLI dispatch shapes (`codex exec`, `opencode run`, `claude -p`).
  - Real token usage parsing from JSON output (`claude`, `codex`).
  - Token estimation fallback for `agy`, `gemini`, `opencode`.
- `tests/test_ledger_schema.py`:
  - Serialization of new optional fields (`preprocess_mark`, `verdict`, `max_fit`, `target_fits`, `route_choice`, `orchestrator`, `worker`).
  - `kultivait harvest` rendering with the new toll summary section.

## Docs

- Update `README.md` to introduce the Preprocessor, Tollbooth, and Route Menu concepts.
- Document `[preprocess]` and `[effort]` configuration sections in `docs/API.md` (or configuration guide). *(Not done: no `docs/API.md` exists; configuration is documented in the README instead.)*
- Maintain all canonical terms in `CONTEXT.md`.

## Out of scope

- Direct implementation of any layer (this design spec concludes wayfinder map #4; implementation is scheduled for a dedicated build effort).
- Autonomous CLI worker supervision or spawning (kultivait is a proxy, not an orchestrator; client agent loops retain control).
- Anthropic `/v1/messages` tool calling support. *(Has since shipped — see README "Endpoints & clients".)*
- Altering verdict derivation thresholds ($[0.65, 0.85)$ confirmed by held-out eval #14).
- System-level daemon management (LaunchAgent / systemd process supervision).
- Learned-from-ledger automated dynamic threshold tuning.
