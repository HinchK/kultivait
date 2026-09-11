# Distillation and shadow cutover

kultivait's preprocessor looks at contested prompts and judges whether a
local model can handle them. The distillation pipeline trains that judge on
your own harvest (toll choices, escalations, ledger entries) and produces a
fine-tuned local model, a `qwen3.5:4b` or `llama-3.2-3b-instruct`
distillate. The goal is better local judgment, fewer unnecessary tolls, and
no misroutes.

```
Harvest (~/.kultivait)
  │
  ├── 1. Corpus (distill corpus) ─── Preview anchors & split held-out eval set
  ├── 2. Generate (distill generate) ─ Dual-teacher synthesis + agreement filter
  ├── 3. Train (distill train) ────── mlx-lm QLoRA on Apple Silicon under resource ladder
  ├── 4. Eval (distill eval) ──────── 5-gate validation against permanent held-out set
  ├── 5. Export (distill export) ──── Fuse QLoRA weights & register kv-judge-<base>-g<gen> in Ollama
  ├── 6. Shadow (shadow) ──────────── Zero-latency background shadow pass on contested traffic
  └── 7. Cutover (cutover) ────────── Human-confirmed flip to live preprocessor seat + instant rollback
```

## The pipeline

```bash
kultivait distill corpus [--dry-run]              # preview anchor set & held-out roster
kultivait distill generate --live                 # dual-teacher synthetic data generation
kultivait distill train --base <base> --corpus-dir <dir>  # train QLoRA under resource ladder
kultivait distill eval --model <model> --heldout <path>   # 5-gate held-out validation
kultivait distill export --base <base> --adapter-path <path> # fuse & register with Ollama
kultivait shadow [--log <path>]                   # shadow log summary & cutover readiness
kultivait cutover --model <distillate> [--yes]    # flip live preprocessor + print rollback
```

`distill corpus [--dry-run]` prints a preview of the anchor set and the
permanent held-out roster. The corpus files themselves are written by
`distill generate`. Tier labels follow a strict order of trust: human toll
choices are gold, execution outcomes silver, and eval records bronze. Real
cases that carry a verdict are held out permanently and never trained on.

`distill generate [--live]` builds synthetic training data from two
teachers, aiming for balanced strata of 40% contested, 30% local, and 30%
frontier prompts.

- The judge teacher is a model from a neutral family (by default
  `--judge-model x-ai/grok-4.6` through OpenRouter, with `opencode` as the
  fallback when no model is given). It classifies each example's tier
  independently, and examples where the teachers disagree are filtered out.
- The rewriter teacher, the `claude` CLI, writes prompt rewrites. The local
  vary model (`qwen3:14b` by default) drafts variations aimed at each band.
- Every example passes a three-stage filter: deduplication by exact hash
  and then by embedding (cosine < 0.92), JSON contract validation, and
  planted-fact recall checks.
- `--live` is required before the generator will call the real
  subscription CLI teachers, and it refuses to generate from unverified
  stubs.

`distill train --base <base>` trains a QLoRA adapter with `mlx-lm` and
stays inside a resource ladder on unified memory: batch size 4→2→1, adapted
layers 16→8→4, then gradient checkpointing. If that still doesn't fit, it
aborts instead of swapping.

`distill eval --model <model>` runs the candidate against the permanent
held-out set through the production generate path. It has to pass five
gates:

- zero dangerous misroutes
- a 100% parse rate
- latency p50 ≤ 8.0 s and max ≤ 15.0 s
- agreement at least as high as the incumbent's
- two-sided band discipline across temperature sweeps (contested floor
  ≥ 50%, flood ceiling ≤ 25%)

`distill export` fuses the QLoRA weights with `mlx_lm.fuse`, writes an
Ollama `Modelfile`, and registers the model as `kv-judge-<base>-g<gen>`
(quantized to `q4_K_M`, at most 4 GB resident).

## Shadow serving

A distillate that passes the gates can shadow live traffic before it serves
real routing verdicts:

```toml
# ~/.kultivait/config.toml
[distill]
model = "qwen3.5:4b"                     # live preprocessor seat
shadow_model = "kv-judge-llama32-3b-g1"  # candidate distillate
shadow_mode = "on"                       # "off" | "on"
shadow_sample_rate = 1.0                 # 100% of contested requests
```

The shadow pass runs after the live response has been sent, so it adds no
latency, and its errors can't affect the request. It logs to
`~/.kultivait/shadow.jsonl`, outside the main ledger, so harvest cost
figures stay clean. `kultivait shadow` reports readiness against ADR 0017's
cutover bar: at least 30 shadowed requests, at least 90% agreement with the
incumbent, and zero anomalies.

## Cutover

kultivait never cuts over on its own. Deploying a model is always a human
decision:

```bash
kultivait cutover --model kv-judge-llama32-3b-g1   # [y/N] confirm, atomic config update
```

`DistillSeat` reads `[distill] model` on every request, so rolling back is
instant and doesn't need a server restart.

Learned routing centroids (`kultivait centroids learn|status|cutover`)
follow the same pattern of shadow, eval, and human cutover; see
[ADR 0021](../adr/0021-learned-centroids.md).

## Related

- [ADR 0012](../adr/0012-distillation-targets.md) through [ADR 0017](../adr/0017-distillate-deployment-and-shadow-rollout.md): targets, corpus, training, eval protocol, teachers, and rollout
- [Distillation pipeline design](../superpowers/specs/2026-08-23-distillation-pipeline-design.md) (historical)
