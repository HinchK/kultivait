# Distillation & local model fine-tuning pipeline — design

Date: 2026-08-23
Branch: main (wayfinder map #44)
Status: approved via wayfinder map #44 (issues #45–#52); prototype validated (#52)

> Historical note (2026-09-03): shipped as designed except the #50 teacher row — superseded the next day by ADR 0016's amendment (local vary model drafts variations, default `qwen3:14b`; neutral API judge `x-ai/grok-4.6` via OpenRouter labels; `opencode` remains the no-argument fallback). See README "Model distillation & shadow cutover" for the shipped shape.

## Problem

Kultivait's preprocessor judge — the local 4B that derives every contested routing verdict — carries a systematic calibration weakness the held-out eval measured: judge fits cluster ≥ 0.85 (emptying the contested band, starving the trolltoll of honest cases; live traffic shows 1 contested in 24 preprocessed), and the `local_sufficient` boolean contradicted its own fits on 10 of 12 cases. The flywheel data to fix this already flows through the proxy — escalations, dual-track ledger verdicts and toll choices, capability-eval transcripts — but nothing closes the loop: no corpus assembly, no training, no evaluation, no safe deployment. Every routing decision is observed and discarded.

## Goal

A **distillation pipeline** that compounds the harvest into better local models:

1. **Corpus & labels** — assemble training pairs from the harvested routing data (real anchors; every real verdict-bearing case permanently held out), scaled by an agreement-filtered synthetic generator taught by two teacher roles.
2. **Training** — mlx-lm QLoRA on the M4 Pro under a hard resource envelope, a two-base bake-off per generation.
3. **Evaluation** — five acceptance gates with two-sided band discipline, a pass-first bake-off winner rule, and a retry→augment→reject failure ladder.
4. **Deployment** — fused export into Ollama as a named distillate, a restart-free config seat, a zero-latency shadow pass on contested traffic, human-flipped cutover with instant rollback.

The compounding flywheel: every harvested prompt improves the local herd itself.

## Decisions made

| Decision / Issue | Choice | Artifact / ADR |
|---|---|---|
| [#47 Fine-tuning landscape](https://github.com/Standard-Pentest/kultivait/issues/47) | mlx-lm QLoRA (4-bit base) + `mlx_lm.fuse` → Ollama is the path on the 24 GB M4 Pro; llama.cpp finetune (FP32/WIP) and torch+peft on mps (no Metal bitsandbytes) ruled out; budgets: 4B easy, 14B QLoRA ~9–10 GB, ~3–4 min/epoch at 100 examples | `experiments/finetune-landscape.md` (branch `research/finetune-landscape`) |
| [#45 Distillation targets](https://github.com/Standard-Pentest/kultivait/issues/45) | v1 distills the **whole preprocessor single-call contract as one model** (judge + analyzer + rewriter); headline metric = **toll-rate reduction vs incumbent** (invariants stay pass/fail); **two-base bake-off** (qwen3.5:4b + challenger); curriculum split deliberately deferred | [ADR 0012](../../adr/0012-distillation-targets.md) |
| [#46 Corpus & labels](https://github.com/Standard-Pentest/kultivait/issues/46) | Serving-shape chat JSONL (system = live contract, user = last user message, assistant = full contract JSON); tiered truth — toll picks gold, outcomes silver, eval bronze, escalations unlabeled pool; **fits regressed from verdict tiers, never copied**; rewrites teacher-written per pair (cross-family rule on judge labels only); synthetic-led ~1–2k with the **anchor set** and a permanent real held-out set | [ADR 0013](../../adr/0013-corpus-and-label-assembly.md) |
| [#48 Training method](https://github.com/Standard-Pentest/kultivait/issues/48) | QLoRA on **both** bases, mlx-lm documented defaults first (search deferred); challenger = **llama-3.2-3b-instruct**; universal **fused export route** with distillate names `kv-judge-<base>-g<gen>`; hard envelope ≤16 GB / ≤45 min per epoch with the **resource ladder** (abort, never swap); serving ≤4 GB; per-epoch checkpoints | [ADR 0014](../../adr/0014-training-method-and-hardware-budget.md) |
| [#49 Eval protocol](https://github.com/Standard-Pentest/kultivait/issues/49) | Five pass/fail gates on the real held-out set (zero dangerous misroutes, 100% parse, p50 ≤ 8s / max ≤ 15s, agreement ≥ incumbent, **two-sided band discipline** floor 50% / ceiling 25% + sweep check); toll-rate headline = telemetry until n ≥ 50 then auto-gate; **pass-first** bake-off (agreement → latency → parse); failure ladder **retry → augment → reject** | [ADR 0015](../../adr/0015-distillation-eval-protocol.md) |
| [#50 Teachers & synthetic policy](https://github.com/Standard-Pentest/kultivait/issues/50) | Judge teacher = **GLM via opencode CLI** (neutral family; re-select if GLM enters the menu); rewriter teacher = **claude CLI**; Gate-clone generator with the **agreement filter** (independent second-pass tier label); strata 40/30/30 contested-heavy with per-pair metadata; 3-stage filter (dedup hash+embedding 0.92 → schema → planted-fact recall); personal-use ToS, provenance per pair, never redistributed | [ADR 0016](../../adr/0016-teacher-selection-and-synthetic-policy.md) |
| [#51 Deployment & shadow](https://github.com/Standard-Pentest/kultivait/issues/51) | Distillates = plain Ollama models; **`[distill]` config seat** resolved per-call (restart-free); **shadow pass** = post-response fire-and-forget on contested traffic only, zero latency; cutover = shadow agreement ≥ 90% over ≥ 30 contested requests AND zero anomalies, **human-flipped**; rollback instant; ledger tags `preprocess_model`; separate `shadow.jsonl` + `kultivait shadow` | [ADR 0017](../../adr/0017-distillate-deployment-and-shadow-rollout.md) |
| [#52 Prototype probe](https://github.com/Standard-Pentest/kultivait/issues/52) | Full round-trip PASS at toy scale: 90 pairs (10 real anchors, 40/30/30), real QLoRA on Llama-3.2-1B-4bit in 4.0 min; distilled **100% parse / 83% agreement / 0 dangerous / 17% band / 1.2s**; fuse + Modelfile emitted; incumbent-baseline serving-mode discovery recorded | branch `prototype/distill-probe` (`69bb55e`) |

## Research & empirical findings

1. **mlx-lm is the Apple-Silicon trainer** (#47): LoRA/QLoRA first-class, chat JSONL auto-format, `--mask-prompt` for completion-only loss, memory knobs (`--batch-size`, `--num-layers`, `--grad-checkpoint`, `iogpu.wired_limit_mb`), fuse + GGUF export built in; llama.cpp finetune is a full-weight FP32 PoC (validated at 1B); torch+peft on mps loses bitsandbytes (CPU-only wheels) to op fallbacks.
2. **Ollama import constraints**: direct `ADAPTER` import covers Llama/Mistral/Gemma — **not Qwen** — and is documented-safe only for non-QLoRA adapters; the universal route is fuse → safetensors/GGUF → `FROM`, with `--quantize q4_K_M` at import (deployed distillate ≈ 2.5 GB at 4B).
3. **Envelope projections** (#47, [derived]): 4B QLoRA 2.5–3 GB working set; 14B QLoRA ~9–10 GB at batch 1 + grad checkpoint; ~3–4 min/epoch at 100 examples, ~35 min at 1k — the ≤45-min cap holds with margin.
4. **The contract is trainable** (#52): 120 QLoRA iterations on 90 toy pairs taught a 1B base perfect JSON discipline (100% parse), 83% verdict agreement, honest band population (17%), at 1.2 s average latency — 4.0 training minutes on the M4 Pro. Directional, not calibration-grade: teacher stages were stubbed.
5. **Serving-mode discovery** (#52): the incumbent qwen3.5:4b through the raw Ollama chat path scores 25% parse / 58 s average (thinking-mode output + timeouts); the production preprocessor path uses a different generate framing. **Incumbent baselines must be measured through the production path** — the eval harness inherits this or every comparison lies.
6. **Harvest volume today**: 152 ledger entries (128 fat-margin skips, 24 preprocessed), 29 escalations, 12 compost briefs — real data seeds and evaluates, synthetic carries training volume (per ADR 0013).

## Architecture

```
HARVEST (~/.kultivait: ledger.jsonl, escalations/, capability-eval artifacts)
  │
  ├─ 1. Corpus Builder (distill/corpus.py)
  │      ├─ Anchor extraction (real prompts; tier labels from toll picks)
  │      ├─ Permanent held-out set (real verdict-bearing cases — never trained on)
  │      └─ Emit: anchor seeds + labels → Generator
  │
  ├─ 2. Synthetic Generator (distill/generator.py — the Gate-clone)
  │      ├─ Judge teacher (GLM/opencode CLI): band-targeted variations (40/30/30)
  │      ├─ Agreement filter: independent 2nd-pass tier label; intended==labeled or dropped
  │      ├─ Rewriter teacher (claude CLI): per-pair rewrite given prompt + tier
  │      └─ 3-stage filter: dedup (hash + embedding 0.92) → schema → planted-fact recall
  │      → train.jsonl / valid.jsonl (serving-shape chat pairs + stratum metadata)
  │
  ├─ 3. Trainer (distill/trainer.py)
  │      ├─ mlx_lm.lora QLoRA — both bases (qwen3.5:4b, llama-3.2-3b-instruct)
  │      ├─ Documented defaults; iters scaled to epochs; resource ladder enforced
  │      └─ Per-epoch checkpoints → adapters/ per base
  │
  ├─ 4. Eval Harness (distill/eval.py)
  │      ├─ Held-out set through the PRODUCTION generate path (per finding 5)
  │      ├─ Five gates + band discipline + sweep; incumbent baseline recomputed
  │      └─ Bake-off winner bookkeeping; failure-ladder rungs (retry/augment/reject)
  │
  ├─ 5. Fused Export (distill/export.py)
  │      ├─ mlx_lm.fuse → safetensors; Modelfile; ollama create kv-judge-<base>-g<gen>
  │      └─ --quantize q4_K_M at import (serving ≤ 4 GB)
  │
  └─ 6. Shadow Serving (server.py hook + distill/shadow.py)
         ├─ [distill] seat: model resolved per-call (restart-free swap)
         ├─ Post-response fire-and-forget on contested traffic (zero latency)
         ├─ shadow.jsonl per-case log; kultivait shadow summary
         └─ Cutover (human flip) → ledger tags preprocess_model per entry
```

## Module design

New package `src/kultivait/distill/` (plus config/server/cli extensions). Signatures are decision-shapes, not final APIs.

**`corpus.py`** — data foundations:

```python
@dataclass(frozen=True)
class Anchor:
    prompt: str            # last user message of a real harvested case
    tier: str              # gold/silver/bronze label source ("local"|"contested"|"frontier" + trust tier)
    origin: str            # "toll_pick" | "counterfactual" | "escalation" | ...

@dataclass(frozen=True)
class TrainingPair:
    messages: list[dict]   # serving shape: system=contract, user=prompt, assistant=contract JSON
    stratum: str           # "contested" | "local" | "frontier"
    provenance: dict       # teacher family, channel, seed anchor id

def harvest_anchors(...) -> tuple[list[Anchor], list[Anchor]]   # (train-seed anchors, held-out eval anchors)
def regress_fits(tier: str, rng) -> list[dict]                  # band placement + spread, never copied
def write_corpus(pairs, path) -> None                            # train.jsonl / valid.jsonl
```

**`generator.py`** — the Gate-clone (template-driven, generate-fn injected for hermetic tests):

```python
def generate_corpus(anchors, *, judge_generate, rewriter_generate, strata=(0.4, 0.3, 0.3),
                    target_pairs=1500, rng) -> list[TrainingPair]
# judge_generate: band-targeted variation -> prompt
# judge_generate (2nd pass, independent): prompt -> tier label   [agreement filter]
# rewriter_generate: (prompt, tier) -> rewrite
# then dedup (hash + embedding > 0.92 drop) -> schema validate -> planted-fact recall
```

**`trainer.py`** — mlx-lm driver (subprocess; no ML deps in the serving package):

```python
def train(base: str, corpus_dir: Path, *, iters, adapter_path, on_budget_event) -> TrainReport
# enforces the resource ladder: batch 4→2→1, layers 16→8→4, grad-checkpoint,
# wired-limit last resort, ABORT never swap; peak-mem + wall-clock recorded
```

**`eval.py`** — gates + bake-off:

```python
@dataclass(frozen=True)
class GateReport:
    gates: dict            # dangerous: 0, parse: 1.0, latency_p50/max, agreement_vs_incumbent,
                           # band_floor >= 0.5, band_ceiling <= 0.25, sweep_ok
    passed: bool

def run_gates(model, heldout, *, generate_via_production_path) -> GateReport
def bake_off(reports: dict[str, GateReport]) -> str | None      # pass-first; None => ladder runs
```

**`export.py`** — fused route:

```python
def export_distillate(base, adapter_path, generation: int, *, quantize="q4_K_M") -> str
# mlx_lm.fuse -> Modelfile -> `ollama create kv-judge-<base>-g<gen>`; returns the distillate name
```

**`shadow.py`** — writer + summary (the server hook calls in; the log lives outside the main ledger):

```python
def record_shadow(incumbent: ShadowResult, shadow: ShadowResult, fingerprint) -> None  # -> shadow.jsonl
def shadow_summary() -> ShadowSummary
# agreement_rate, anomaly counts, n, cutover_ready: bool  (>=90% agreement over >=30, zero anomalies)
```

**`cli.py`** — the command surface: `kultivait distill corpus|train|eval|export` (pipeline ops) and `kultivait shadow` (summary + cutover-readiness).

**Extensions**: `config.py` gains the `[distill]` section; `server.py` resolves the preprocess model from the seat per-call and gains the exception-isolated post-response shadow hook on the contested path; `ledger.py` tags `preprocess_model`.

## Ledger & shadow telemetry extensions

- **Ledger** (additive): every preprocessed entry records `preprocess_model` (the live seat's model at dispatch time; legacy entries imply `qwen3.5:4b`). The harvest may slice seasons by generation without schema change.
- **Shadow log** (`~/.kultivait/shadow.jsonl`, append-only, outside the main ledger by design — never polluting toll stats, routing analytics, or the cost lenses): `{ts, fingerprint, prompt_hash, incumbent: {model, verdict, max_fit, latency_s, parse_ok}, shadow: {model, verdict, max_fit, latency_s, parse_ok}, agree}`.
- **Cutover-readiness** derives from the log (agreement ≥ 90% over ≥ 30 shadowed contested requests AND zero gate-failing anomalies: parse failures < 10%, no dangerous local verdicts on escalatory prompts); `kultivait shadow` prints it.
- **Provenance chain**: eval records (per base per generation) → shadow log → ledger `preprocess_model` — every generation's journey auditable end to end.

## Config schema

```toml
[distill]
model = "qwen3.5:4b"            # the live preprocessor seat; per-call resolution (restart-free)
shadow_model = ""               # gate-passing distillate name (e.g. "kv-judge-llama32-3b-g1"); empty = none
shadow_mode = "off"             # "off" | "on"
shadow_sample_rate = 1.0        # contested-path sampling (1.0 while contested traffic is scarce)
```

Round-trips through save/load; `init`/setup untouched — the distill CLI writes it. The incumbent default stands until a cutover writes the knob. Curriculum strata, envelope caps, and teacher identities are code-first constants (per the house pattern), not TOML.

## Build slices (tracer-bullet decomposition, D1–D7)

The `/to-tickets` pass will publish these with native edges; the shape:

- **D1 — Config seat & corpus foundations**: `[distill]` section round-trip; `corpus.py` (anchor extraction, tiered labels, held-out split, fit regression); first real anchor set + held-out set materialized from the live harvest. *Demoable: `kultivait distill corpus --dry-run` prints anchors/strata.*
- **D2 — Synthetic generator**: `generator.py` with both teacher roles via CLI dispatch, agreement filter, 3-stage filtering; a ~1.5k-pair corpus build (on-subscription). *Demoable: corpus build + filter stats.*
- **D3 — Trainer**: `trainer.py` mlx-lm QLoRA driver, resource ladder, checkpointing; first real 2-base training runs within envelope. *Demoable: adapters + train reports per base.*
- **D4 — Eval harness**: `eval.py` gates via the production generate path; incumbent baseline recomputed; bake-off + ladder bookkeeping. *Demoable: first full GateReport set on real adapters.*
- **D5 — Fused export**: `export.py` fuse → Modelfile → `ollama create kv-judge-<base>-g<gen>`; distillate serving smoke. *Demoable: distillate answers a contract prompt through Ollama.*
- **D6 — Shadow serving**: seat resolution in the server generate path, post-response contested-only hook, `shadow.jsonl`, `kultivait shadow`, ledger `preprocess_model` tagging. *Demoable: live shadow log + summary + cutover-readiness.*
- **D7 — First generation flywheel**: end-to-end run on the real harvest — corpus → both bases → gates → winner export → shadow → the human's first cutover decision with the runbook. *Demoable: the flywheel turns once, auditable end to end.*

## Verification & acceptance criteria

- **Testing discipline**: hermetic tests at the highest seams — the distill CLI commands, the generator with injected generate fns (agreement-filter and 3-stage-filter behavior verified without teachers), gate computation on fixture outputs, config round-trip, shadow hook isolation (a shadow crash never touches serving; the ledger stays clean of shadow rows). Live/real checks stay in the slices' demo steps and the probe pattern (`experiments/`), not the unit suite. Prior art: tollbooth's 26 hermetic tests; the probe's fixture discipline; ledger migration tests from R3.
- **Acceptance** (the build effort is done when): a D7 run completes within the ADR 0014 envelope; gates compute on both bases with the incumbent baselined through the production path; a winner (if any) exports, registers, shadows on live contested traffic with zero request-latency impact; `kultivait shadow` reports cutover-readiness; the ledger tags generations; rollback is demonstrated (revert the knob, next request serves the incumbent).
- **Quality floors that are not negotiable**: zero dangerous misroutes on the held-out set for any deployed distillate; the corpus never contains a real verdict-bearing case; shadow outcomes never enter the main ledger; key material and teacher outputs carry provenance and never leave the machine.

## Out of scope

- Multi-model curriculum split (specialists) — deferred with ADR 0012's standing fog; reopens after the flywheel proves out.
- Retraining cadence automation / continuous triggers — batch runs per generation in v1; automation is a later effort.
- Dataset versioning infrastructure beyond per-pair provenance + stratum metadata — the release format firms up when the augment rung produces deltas.
- Distilling behaviors beyond the preprocessor contract (router classifier, dedicated rewriter) — v1 target scope per ADR 0012.
- GPU/cloud training off the M4 Pro.

## Further notes

- The probe (`prototype/distill-probe`, `69bb55e`) is the copy-ready seed for corpus/trainer/eval/export shapes; its incumbent-baseline discovery (raw chat path vs production path) is binding on D4.
- Teacher neutrality is time-bound: if a GLM-family target ever enters the route menu, the judge teacher must be re-selected (ADR 0016).
- The toll-rate headline auto-promotes from telemetry to sixth gate at n ≥ 50 real held-out cases — the promotion is recorded in the eval report, not re-decided (ADR 0015).
- Map #44's fog-out items (curriculum, cadence, dataset versioning) are tracked above as deferred, each with its reopen condition.
