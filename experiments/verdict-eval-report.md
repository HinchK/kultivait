# Held-Out Evaluation Report: Verdict Threshold Validation (Ticket #14)

Held-out evaluation of kultivait's provisional verdict derivation thresholds ($[0.65, 0.85)$) across 12 representative cases (6 probe baseline + 6 fresh held-out prompts) evaluated against live local Ollama models (`qwen3.5:4b` headline simple tier and `qwen3:14b` reference tier).

---

## 1. Method

### Evaluation Contract
- **Pre-processor Execution**: Single-call pass using `PREPROCESSOR_PROMPT` verbatim from `experiments/preprocessor_probe.py` (`temperature: 0.2`, `num_predict: 700`, `think: false`, Ollama `/api/chat`, non-streaming, timeout 300s).
- **Headline Tier**: `qwen3.5:4b` (the contract's default preprocessor model). Reference comparison: `qwen3:14b`.
- **Verdict Derivation**: 
  $$\text{fit} = \max_{t \in \text{judge.targets}} (t.\text{fit})$$
  $$\text{verdict} = \begin{cases} \text{local} & \text{if fit} < 0.65 \\ \text{frontier} & \text{if fit} \ge 0.85 \\ \text{contested} & \text{otherwise} \end{cases}$$
- **Judge Diagnostic**: The judge's `local_sufficient` boolean is recorded strictly for diagnostics; it is not trusted and not used for routing decisions (decisions #7 and #8).
- **Latency Budget**: Target p50 $\le 8.0\text{s}$, maximum cap $\le 15.0\text{s}$.

### Test Cases & Ground Truth Labels

| Slug | Label | Prompt Rationale |
|---|---|---|
| `01-simple-edit` | `local` | Mechanical rename across a single config file and its imports |
| `02-debug` | `local` | In-repo diagnostic on known codebase timeout parameter |
| `03-architecture` | `frontier` | Cross-file design reasoning comparing server lifecycle and archiving architectures |
| `04-docs-lookup` | `frontier` | Freshness-dependent lookup of specific external CLI version documentation |
| `05-compound` | `frontier` | Orchestration-worthy compound multi-component feature and documentation update |
| `06-adversarial-truncated` | `borderline` | Adversarially truncated context where missing information creates genuine ambiguity |
| `h01-local-constant` | `local` | Single-file mechanical refactoring of test constants |
| `h02-inrepo-lookup` | `local` | Static code extraction and lookup within a single repository file |
| `h03-flaky-debug` | `borderline` | Open-ended concurrency debugging with incomplete context and no reproduction repository |
| `h04-middleware-arch` | `frontier` | Deep architectural analysis of HTTP request lifecycle, holding semantics, and headless client tradeoffs |
| `h05-freshness-cite` | `frontier` | External documentation verification requiring fresh citations on recent version changes |
| `h06-small-feature` | `borderline` | Multi-step feature spanning CLI argument parsing, serialization, and documentation |

### Known Limitations
- Single pass execution (deterministic sampling at temperature 0.2).
- Fixed 12-case benchmark suite.
- Local execution on Apple Silicon (`darwin/arm64`) with shared GPU memory.

---

## 2. Results

### Headline Tier: `qwen3.5:4b` (Simple Tier Default)

| Case | Label | Max Fit | Verdict | Outcome | Latency | `local_sufficient` (diag) | Task Type | Complexity |
|---|---|---|---|---|---|---|---|---|
| `01-simple-edit` | `local` | 0.90 | `frontier` | Wasteful | 8.94s | `true` | `simple_edit` | 3 |
| `02-debug` | `local` | 0.90 | `frontier` | Wasteful | 5.83s | `true` | `debugging` | 4 |
| `03-architecture` | `frontier` | 0.90 | `frontier` | Agreement | 5.11s | `true` | `architecture` | 6 |
| `04-docs-lookup` | `frontier` | 1.00 | `frontier` | Agreement | 4.54s | `true` | `docs_lookup` | 4 |
| `05-compound` | `frontier` | 0.85 | `frontier` | Agreement | 6.89s | `true` | `compound` | 7 |
| `06-adversarial-truncated` | `borderline` | 0.85 | `frontier` | Miss | 7.06s | `false` | `debugging` | 4 |
| `h01-local-constant` | `local` | 0.95 | `frontier` | Wasteful | 6.36s | `true` | `simple_edit` | 2 |
| `h02-inrepo-lookup` | `local` | 0.90 | `frontier` | Wasteful | 6.81s | `true` | `docs_lookup` | 3 |
| `h03-flaky-debug` | `borderline` | 0.90 | `frontier` | Miss | 7.78s | `false` | `debugging` | 6 |
| `h04-middleware-arch` | `frontier` | 0.90 | `frontier` | Agreement | 7.40s | `true` | `compound` | 6 |
| `h05-freshness-cite` | `frontier` | 0.90 | `frontier` | Agreement | 6.20s | `true` | `docs_lookup` | 4 |
| `h06-small-feature` | `borderline` | 0.90 | `frontier` | Miss | 7.42s | `true` | `simple_edit` | 2 |

### Reference Tier: `qwen3:14b` (Reasoning Tier)

| Case | Label | Max Fit | Verdict | Outcome | Latency | `local_sufficient` (diag) | Task Type | Complexity |
|---|---|---|---|---|---|---|---|---|
| `01-simple-edit` | `local` | 0.85 | `frontier` | Wasteful | 17.67s | `true` | `simple_edit` | 3 |
| `02-debug` | `local` | 0.90 | `frontier` | Wasteful | 8.89s | `false` | `debugging` | 6 |
| `03-architecture` | `frontier` | 0.90 | `frontier` | Agreement | 9.63s | `true` | `debugging` | 5 |
| `04-docs-lookup` | `frontier` | 0.90 | `frontier` | Agreement | 7.54s | `false` | `docs_lookup` | 3 |
| `05-compound` | `frontier` | 0.90 | `frontier` | Agreement | 14.76s | `true` | `simple_edit` | 5 |
| `06-adversarial-truncated` | `borderline` | 0.80 | `contested` | Agreement | 12.76s | `false` | `debugging` | 5 |
| `h01-local-constant` | `local` | 0.90 | `frontier` | Wasteful | 15.43s | `true` | `simple_edit` | 3 |
| `h02-inrepo-lookup` | `local` | 0.70 | `contested` | Miss | 13.46s | `false` | `docs_lookup` | 4 |
| `h03-flaky-debug` | `borderline` | 0.85 | `frontier` | Miss | 18.86s | `false` | `debugging` | 5 |
| `h04-middleware-arch` | `frontier` | 0.85 | `frontier` | Agreement | 18.23s | `false` | `architecture` | 6 |
| `h05-freshness-cite` | `frontier` | 0.80 | `contested` | Miss | 18.55s | `false` | `docs_lookup` | 5 |
| `h06-small-feature` | `borderline` | 0.85 | `frontier` | Miss | 18.56s | `true` | `simple_edit` | 3 |

---

## 3. Aggregate Metrics

| Metric | `qwen3.5:4b` (Headline Simple) | `qwen3:14b` (Reference) | Constraint / Target |
|---|---|---|---|
| **Parse Success Rate** | **12/12 (100.0%)** | 12/12 (100.0%) | 100% parse integrity |
| **Dangerous Errors** (frontier $\to$ local) | **0 / 12 (0.0%)** | 0 / 12 (0.0%) | **0 allowed** |
| **Wasteful Errors** (local $\to$ frontier) | **4 / 12 (33.3%)** | 3 / 12 (25.0%) | Minimize |
| **Verdict Agreement** | **5 / 12 (41.7%)** | 5 / 12 (41.7%) | Baseline benchmark |
| **Toll Rate** (contested fraction) | **0 / 12 (0.0%)** | 3 / 12 (25.0%) | $\le 25.0\%$ |
| **Latency p50** | **6.89s** | 15.43s | $\le 8.0\text{s}$ budget |
| **Latency Maximum** | **8.94s** | 18.86s | $\le 15.0\text{s}$ cap |

---

## 4. Threshold Sweep

We recomputed verdicts across the collected fits for candidate cutpoint pairs $(T_{\text{low}}, T_{\text{high}})$:

### `qwen3.5:4b` (Headline Tier)
| $(T_{\text{low}}, T_{\text{high}})$ | Agreement | Dangerous | Wasteful | Toll Rate | Status |
|---|---|---|---|---|---|
| `(0.60, 0.80)` | 5/12 (41.7%) | 0 | 4 | 0.0% | No delta |
| `(0.60, 0.85)` | 5/12 (41.7%) | 0 | 4 | 0.0% | No delta |
| `(0.65, 0.80)` | 5/12 (41.7%) | 0 | 4 | 0.0% | No delta |
| **`(0.65, 0.85)`** | **5/12 (41.7%)** | **0** | **4** | **0.0%** | **Current Provisional** |
| `(0.65, 0.90)` | 5/12 (41.7%) | 0 | 4 | 16.7% | Introduces 2 tollholds with no agreement gain |
| `(0.70, 0.85)` | 5/12 (41.7%) | 0 | 4 | 0.0% | No delta |
| `(0.70, 0.90)` | 5/12 (41.7%) | 0 | 4 | 16.7% | Introduces 2 tollholds with no agreement gain |

### `qwen3:14b` (Reference Tier)
| $(T_{\text{low}}, T_{\text{high}})$ | Agreement | Dangerous | Wasteful | Toll Rate | Status |
|---|---|---|---|---|---|
| `(0.60, 0.80)` | 5/12 (41.7%) | 0 | 3 | 8.3% | Reduces tollholds |
| `(0.60, 0.85)` | 5/12 (41.7%) | 0 | 3 | 25.0% | No delta vs provisional |
| `(0.65, 0.80)` | 5/12 (41.7%) | 0 | 3 | 8.3% | Reduces tollholds |
| **`(0.65, 0.85)`** | **5/12 (41.7%)** | **0** | **3** | **25.0%** | **Current Provisional** |
| `(0.65, 0.90)` | 6/12 (50.0%) | 0 | 2 | 58.3% | Breaches $\le 25\%$ toll rate ceiling |
| `(0.70, 0.85)` | 5/12 (41.7%) | 0 | 3 | 25.0% | No delta vs provisional |
| `(0.70, 0.90)` | 6/12 (50.0%) | 0 | 2 | 58.3% | Breaches $\le 25\%$ toll rate ceiling |

---

## 5. Key Findings & Diagnostic Observations

1. **Safety Guarantee (Zero Dangerous Errors)**: Across all 24 evaluations, **zero dangerous misroutes occurred**. Every single frontier task (`03-architecture`, `04-docs-lookup`, `05-compound`, `h04-middleware-arch`, `h05-freshness-cite`) received target fits $\ge 0.80$, preventing any cloud-worthy prompt from being silently served locally.
2. **`local_sufficient` Diagnostic Vindicated**: On `qwen3.5:4b`, the judge marked `local_sufficient: true` on 10 of 12 cases (including cases where it assigned Claude a fit of $0.90$ to $1.00$). On `qwen3:14b`, it marked `local_sufficient: false` for simple local documentation lookups. This confirms the wisdom of decisions #7/#8: the judge's boolean cannot be trusted, and derived structural verdicts are essential.
3. **Latency Profile Confirms Tier Choice**: 
   - `qwen3.5:4b` achieved $\text{p50} = 6.89\text{s}$ and $\text{max} = 8.94\text{s}$, completely within the request-path budget ($\text{p50} \le 8\text{s}, \text{cap} \le 15\text{s}$).
   - `qwen3:14b` registered $\text{p50} = 15.43\text{s}$ and $\text{max} = 18.86\text{s}$, violating the latency budget. This empirically confirms `qwen3.5:4b` as the mandatory default for `preprocess_model`.

---

## 6. Threshold Recommendation

Applying the architect's fixed recommendation rule:
> *KEEP a threshold unless the sweep shows a setting with fewer dangerous errors or higher agreement that does NOT push toll rate above 25%.*

- On `qwen3.5:4b`, dangerous errors are already at **0**. Agreement is constant ($41.7\%$) across all sweep cutpoints because small models score target capability generously. Alternative cutpoints (such as $(0.65, 0.90)$) add toll rate without increasing agreement.
- On `qwen3:14b`, while $(0.65, 0.90)$ marginally raises agreement ($50.0\%$), it forces the toll rate to $58.3\%$, severely violating the $25\%$ ceiling.

**Recommendation**: **KEEP the provisional thresholds unchanged at $[0.65, 0.85)$**.

---

## 7. Artifacts Pointer
All per-case artifacts and complete machine-readable evaluation outputs reside in:
- `experiments/verdict_eval/summary.json`
- `experiments/verdict_eval/qwen3.5-4b/` (12 case JSON artifacts)
- `experiments/verdict_eval/qwen3-14b/` (12 case JSON artifacts)
- Harness script: `experiments/verdict_eval.py`
