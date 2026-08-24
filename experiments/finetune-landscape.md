# Local fine-tuning landscape on Apple Silicon (4B–14B, 24 GB M4 Pro)

Research ticket: Standard-Pentest/kultivait#47 (Map #44). Date: 2026-08-23.
Method: primary documentation only — official repo docs and source files read directly. Every claim links its source. Derived arithmetic is labeled **[derived]**.

## TL;DR verdict

| Path | Verdict for 4B–14B chat fine-tunes on 24 GB |
|---|---|
| **mlx-lm LoRA/QLoRA** | **The default path.** First-class, documented, quantized training supported, fuse + GGUF/safetensors export built in. 8B-class LoRA documented on 32 GB; on 24 GB use QLoRA (4-bit base) for 8B and 14B. |
| llama.cpp `llama-finetune` | **Not for this.** Experimental full-weight (FP32) text trainer; upstream validates only Stories-260K and Llama-3.2-1B on 24 GB. No chat/instruct workflow. |
| PyTorch + peft on `mps` | **Second choice.** Officially supported but the mps notes page is thin; bitsandbytes has a macOS arm64 build only as a **CPU** backend (no Metal), so bnb-QLoRA doesn't accelerate on mps. Fine for small LoRA if you're already in the HF stack; MLX is faster and lighter here. |
| Ollama import | **Serving target, not a trainer.** `ADAPTER` accepts Safetensors adapters (Llama/Mistral/Gemma families — MLX is listed as a producer) and GGUF adapters; recommended path is `mlx_lm.fuse` then import fused safetensors or GGUF. |

## (a) MLX / mlx-lm LoRA + QLoRA

Source: [mlx_lm/LORA.md](https://github.com/ml-explore/mlx-lm/blob/main/mlx_lm/LORA.md), [mlx-lm README](https://github.com/ml-explore/mlx-lm/blob/main/README.md) (read 2026-08-23).

- **Command**: `mlx_lm.lora --model <hf-repo-or-path> --train --data <dir> --iters 600`; YAML config via `--config`. Fine-tune types: `lora` (default), `dora`, `full`. Training deps: `pip install "mlx-lm[train]"`.
- **QLoRA**: "If `--model` points to a quantized model, then the training will use QLoRA, otherwise it will use regular LoRA." Build a 4-bit base with `mlx_lm.convert --model <repo> -q` (README "Command Line" section). Thousands of pre-quantized bases exist under [mlx-community](https://huggingface.co/mlx-community).
- **Documented model families** (LORA.md): Mistral, Llama, Phi2, Mixtral, Qwen2, Gemma, OLMo, MiniCPM, InternLM2. (The `mlx_lm/models/` tree is far broader — qwen3, gemma3, glm4, etc. — so the doc list lags the code; any model with an mlx-lm implementation is trainable.)
- **Dataset format**: `--data` dir with `train.jsonl` (+ optional `valid.jsonl`, `test.jsonl`), one example per line. Formats auto-detected: `chat` (`{"messages":[{"role":...,"content":...}]}` — HF chat template applied automatically), `tools`, `completions` (`{"prompt":...,"completion":...}`), `text`. `--mask-prompt` computes loss on completion only (chat/completions). Hugging Face datasets usable via YAML `hf_dataset:` mapping.
- **Memory knobs** (LORA.md "Memory Issues"): QLoRA; `--batch-size` (default 4) down to 1 with `--grad-accumulation-steps` to keep effective batch; `--num-layers` (default 16, try 8/4); shorter sequences; `--grad-checkpoint`.
- **Documented anchors**: "for a machine with 32 GB the following should run reasonably fast": Mistral-7B LoRA, batch 1, 4 layers → **~250 tokens/s on M1 Max 32 GB**. Historical mlx-examples lora README: Llama-7B trains at **~475 tokens/s on M2 Ultra**; same 7B/batch-1/4-layer recipe cited for 32 GB ([archived mlx-examples/lora README](https://github.com/ml-explore/mlx-examples/tree/main/lora)).
- **Fuse / export**: `mlx_lm.fuse --model <path> [--adapter-path adapters/]` → fused model; optional `--upload-repo`; **`--export-gguf`** → `ggml-model-f16.gguf` — "GGUF support is limited to Mistral, Mixtral, and Llama style models in fp16 precision" (LORA.md). Adapters resume via `--resume-adapter-file`.
- **macOS memory wiring** (README "Large Models", macOS 15+): raise wired limit with `sudo sysctl iogpu.wired_limit_mb=N` when the model + working set approach RAM — directly relevant to a 24 GB machine.
- **Distributed**: `mx.distributed` supported for fine-tuning (README).

## (b) llama.cpp finetune path

Sources: [examples/training/README.md](https://github.com/ggml-org/llama.cpp/blob/master/examples/training/README.md), [examples/training/finetune.cpp](https://github.com/ggml-org/llama.cpp/blob/master/examples/training/finetune.cpp) (read 2026-08-23).

- Upstream's own words: "So far finetuning is **technically functional (for FP32 models and limited hardware setups) but the code is very much WIP**. Finetuning of Stories 260K and **LLaMA 3.2 1b seems to work with 24 GB of memory**." CPU build recommended for CPU training; CUDA builds use `-ngl 999`.
- Current `finetune.cpp` is a minimal **full-parameter** trainer over the new `ggml_opt` API: tokenize one raw text file, run `llama_opt_epoch`, `llama_model_save_to_file`. The PoC is a perplexity reduction on wikitext-2 (2 epochs). No chat-template handling, no instruction dataset loader, no LoRA saving in the current example (the old `--lora-*` flags are gone from the current file). KV cache forced to F32 "due to a lack of f16 support for OUT_PROD".
- **Verdict**: memory behavior (FP32 weights + full optimizer state) means 4B–14B is out of reach on 24 GB (FP32 4B ≈ 16 GB weights alone **[derived]**, before gradients/optimizer). It retains a legacy/PoC role; do not plan chat instruction-tuning here. llama.cpp remains relevant *around* training: `convert_hf_to_gguf.py` and **`convert_lora_to_gguf.py`** convert models and adapters to GGUF for Ollama import ([repo root](https://github.com/ggml-org/llama.cpp)).

## (c) PyTorch + peft on Metal (mps)

Sources: [PyTorch MPS backend notes](https://docs.pytorch.org/docs/stable/notes/mps.html) (v2.13), [bitsandbytes installation docs](https://huggingface.co/docs/bitsandbytes/main/en/installation), [peft docs index](https://huggingface.co/docs/peft/main/en/index), [PyTorch dispatcher/A-Ten structure](https://zread.ai/pytorch/pytorch/10-operator-dispatch-mechanism) (read 2026-08-23).

- PyTorch officially positions `mps` for "high-performance **training** on GPU for macOS devices"; requires macOS 14+ and an MPS-enabled device (notes page). The official notes page is otherwise minimal — no training-specific tuning guidance, unlike CUDA's ecosystem.
- **Op coverage**: MPS kernels live in `aten/src/ATen/native/mps/`; the dispatcher routes per-backend and has CPU **fallback kernels** for ops without a backend kernel. In practice mps training loops emit "not currently implemented on the MPS backend and will fall back to run on the CPU" warnings for uncovered ops (community-observed behavior consistent with the fallback mechanism; not stated on the notes page itself).
- **bitsandbytes**: the install guide lists "official support for NVIDIA GPUs, AMD GPUs, Intel XPUs, **Apple Silicon**, and Intel Gaudi" — but the macOS arm64 wheel is published under the **CPU** section, and source builds on macOS "will be built for CPU only at this time". I.e., there is **no Metal backend** for bnb; NF4/int8 bnb-QLoRA does not accelerate on `mps`. macOS bnb preview wheel: `bitsandbytes-...-macosx_14_0_arm64.whl`.
- **peft**: method library (LoRA etc.) integrated with Transformers/Accelerate; device-agnostic by design — no mps-specific features or caveats documented.
- **Verdict [derived from the above]**: plain bf16/fp16 LoRA on mps works for small runs but you lose bnb quantization (falls back to CPU or is unavailable), lose paged CUDA-only optimizers, and eat op-fallback stalls. On Apple Silicon, MLX occupies this niche natively. Use torch+peft on mps only when a required HF-library dependency dictates it.

## (d) Ollama import

Sources: [docs.ollama.com/import](https://docs.ollama.com/import), [docs.ollama.com/modelfile](https://docs.ollama.com/modelfile) (read 2026-08-23).

- **Safetensors adapter** — `Modelfile`: `FROM <base model>` + `ADAPTER /path/to/safetensors/adapter/dir`; `ollama create my-model`. Supported adapter architectures: **Llama (2/3/3.1/3.2), Mistral (1/2, Mixtral), Gemma (1/2)**. Docs name MLX among fine-tuning frameworks that can produce importable Safetensors adapters (alongside HF and Unsloth). "Most frameworks use different quantization methods, so **it's best to use non-quantized (i.e. non-QLoRA) adapters**" — i.e., importing adapters directly is supported but the documented-safe case is full-precision LoRA adapters; for QLoRA work the robust path is merge-then-import.
- **Safetensors model**: `FROM /path/to/safetensors/directory` (same architecture list + Phi3). "This includes importing foundation models as well as any fine tuned models which have been **fused** with a foundation model."
- **GGUF model/adapter**: `FROM /path/to/file.gguf`, or `FROM <model>` + `ADAPTER /path/to/lora.gguf`; obtain GGUF via llama.cpp `convert_hf_to_gguf.py` / `convert_lora_to_gguf.py`.
- **MLX → Ollama**: (1) `mlx_lm.fuse --export-gguf` → `FROM fused_model/ggml-model-f16.gguf` (GGUF export limited to Mistral/Mixtral/Llama fp16 per LORA.md); (2) `mlx_lm.fuse` → fused safetensors dir → `FROM /path/to/dir`; (3) direct `ADAPTER` import of the MLX safetensors adapter (Llama/Mistral/Gemma bases). Note Ollama's adapter architecture list does not include Qwen — Qwen fine-tunes should go the fused-model route.
- **Quantize at import**: `ollama create --quantize q4_K_M` supports `q8_0`, `q4_K_S`, `q4_K_M` from FP16/FP32 Modelfile sources — so you can fuse in fp16 on the Mac, then let Ollama quantize.

## (e) Realistic budgets on 24 GB M4 Pro

Documented anchors: 7B LoRA recipe documented "reasonable" on **32 GB** at ~250 tok/s (M1 Max, batch 1, 4 layers, LORA.md); ~475 tok/s on M2 Ultra (mlx-examples); llama.cpp finetune validated only at **1B** on 24 GB (its README). No primary doc states 4B/8B/14B on exactly 24 GB — table below is **[derived]** from those anchors + weight arithmetic (fp16 ≈ 2 bytes/param, 4-bit ≈ 0.5 bytes/param + overheads) and should be confirmed with one pilot run per model size.

| Model | Mode | Est. weights + training working set | Fits 24 GB w/ system headroom (~4–6 GB for macOS)? |
|---|---|---|---|
| 4B (e.g. Qwen3-4B) | LoRA fp16 | ~8 GB weights + LoRA/activations | Yes, comfortably (default knobs) |
| 4B | QLoRA 4-bit | ~2.5–3 GB | Yes, lots of headroom |
| 8B | LoRA fp16 | ~16 GB + activations/optimizer | Marginal — batch 1, `--num-layers 4–8`, `--grad-checkpoint`; QLoRA safer (7B fp16 LoRA is documented at 32 GB, i.e. 8 GB more than this machine) |
| 8B | QLoRA 4-bit | ~5–6 GB | Yes |
| 14B | LoRA fp16 | ~28 GB weights | **No** |
| 14B | QLoRA 4-bit | ~9–10 GB + LoRA/activations | Yes, with batch 1–2 + grad checkpoint; raise `iogpu.wired_limit_mb` if macOS swaps |

**Time-per-run [derived]** at the documented 250 tok/s (M1 Max) — M4 Pro should land at or above this:
- 100 examples × ~500 tok ≈ 50k tokens ≈ **~3–4 min/epoch**
- 1k examples ≈ 500k tokens ≈ **~35 min/epoch**
- 10k examples ≈ 5M tokens ≈ **~5.5 h/epoch** (use fewer epochs/iters; calibration-style fine-tunes converge in 1–3 epochs on small data)

Practical recipe for kultivait judge/classifier fine-tunes: `mlx_lm.lora --model mlx-community/<8B-or-14B>-4bit --train --batch-size 1..4 --num-layers 8..16 --grad-checkpoint --mask-prompt --iters 600..2000`, chat-format JSONL, then `mlx_lm.fuse` → Ollama.

## (f) Prior art: small judge/classifier distillation (brief, doc-grounded)

- **LlamaIndex** ships a documented notebook distilling a GPT-3.5 judge from GPT-4 pairwise preferences (distillation finetuning of judge verdicts): [Knowledge Distillation For Fine-Tuning A GPT-3.5 Judge](https://developers.llamaindex.ai/python/examples/finetuning/llm_judge/pairwise/finetune_llm_judge/).
- **distilabel** (Argilla) — first-party docs frame it as the pipeline tool "to synthesize and judge data" for synthetic datasets that then feed standard fine-tuning stacks ([distilabel docs](https://distilabel.argilla.io/), [repo](https://github.com/argilla-io/distilabel)).
- **mlx-lm itself ships no judge/classifier distillation example** — its `mlx_lm/examples/` contains only generation/tool-use/training-config snippets (per repo tree read 2026-08-23). The pattern (teacher LLM labels → chat-JSONL → LoRA) is fully supported by the documented `chat` dataset format but is assembled by the user.

## Recommendation

Adopt **mlx-lm QLoRA on 4-bit MLX-community bases** as the local fine-tuning path on the M4 Pro: 4B/8B trivially fit; 14B fits in QLoRA with batch 1 + grad checkpoint. Serve via `mlx_lm.fuse` → Ollama (`FROM` fused safetensors/GGUF; let `ollama create --quantize` shrink for serving). Skip llama.cpp finetune (1B/FP32 PoC tier). Keep PyTorch+peft+mps out of the critical path (bnb CPU-only on macOS, op fallbacks). This unblocks #48 (blocked-by this ticket).

## Sources

1. mlx-lm LORA.md — https://github.com/ml-explore/mlx-lm/blob/main/mlx_lm/LORA.md
2. mlx-lm README — https://github.com/ml-explore/mlx-lm/blob/main/README.md
3. mlx-examples lora README (archived) — https://github.com/ml-explore/mlx-examples/tree/main/lora
4. llama.cpp examples/training README — https://github.com/ggml-org/llama.cpp/blob/master/examples/training/README.md
5. llama.cpp finetune.cpp — https://github.com/ggml-org/llama.cpp/blob/master/examples/training/finetune.cpp
6. PyTorch MPS backend notes — https://docs.pytorch.org/docs/stable/notes/mps.html
7. bitsandbytes installation — https://huggingface.co/docs/bitsandbytes/main/en/installation
8. peft docs index — https://huggingface.co/docs/peft/main/en/index
9. Ollama import — https://docs.ollama.com/import
10. Ollama Modelfile reference — https://docs.ollama.com/modelfile
11. LlamaIndex judge-distillation example — https://developers.llamaindex.ai/python/examples/finetuning/llm_judge/pairwise/finetune_llm_judge/
12. distilabel docs — https://distilabel.argilla.io/

Note: `mlctx.github.io/mlx` (MLX docs site named in the ticket) returned 404 at `/`, `/stable/`, and `/latest/` on 2026-08-23; the GitHub repos above (ml-explore/mlx-lm, ml-explore/mlx) are the live primary documentation.
