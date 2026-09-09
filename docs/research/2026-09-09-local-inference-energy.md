# Local-inference energy ground truth + literature bounds

Ticket: [#167](https://github.com/Standard-Pentest/kultivait/issues/167) · map: [#166](https://github.com/Standard-Pentest/kultivait/issues/166)
Date: 2026-09-09 · Subject: Wh-per-1K-token ground truth for 3B–14B dense models via llama.cpp/ollama (Metal) on M-series (M4 Pro-class), non-privileged measurement methods on macOS, and literature-derived sanity bounds for the eval's energy coefficients.

Provenance classes used below: **PEER-REVIEWED** / **PREPRINT** / **VENDOR-DOC** / **TOOL-DOC** / **COMMUNITY-MEASURED** / **LOCAL-VERIFY** (reproduced first-hand on this machine: Apple M4 Pro, macOS, arm64).

---

## 1. Verified-facts register

| # | Figure / fact | Source | URL | Retrieved | Provenance |
|---|---|---|---|---|---|
| F1 | M4 Pro 48 GB, ollama, Q4_K_M, powermetrics @2 s: IOReport "CPU+GPU package" during sustained inference **0.41–0.47 W**; GPU idle 30 mW @338 MHz; GPU during 7B decode 115–167 mW | GreenBench (Red Hat et al.), arXiv 2608.28667v1 | https://arxiv.org/html/2608.28667v1 | 2026-09-09 | PREPRINT |
| F2 | System (whole-machine) power during those workloads **estimated 8–12 W** (thermal-spec estimate, cross-cited to Jareño 6.5–8.2 W); DRAM excluded from package figure — authors themselves flag this and recommend zeus-apple-silicon or wall meters | GreenBench §III-D, §V | same | 2026-09-09 | PREPRINT |
| F3 | System-level per-output-token energy on M4 Pro: **0.09–0.25 J/tok** (Llama-3.2-3B → Gemma-2-9B) = **0.025–0.069 Wh per 1K output tokens**; package-level 4.4–11.6 mJ/tok; 4–12 tok/W | GreenBench Table IV | same | 2026-09-09 | PREPRINT |
| F4 | Decode throughput M4 Pro/ollama/Q4_K_M: llama3.2:3b 175.9 tok/s (short outputs), qwen2.5:7b 59 tok/s, gemma2:9b 42 tok/s; power-law fit θ ≈ 340·N^−0.85 tok/s (R²=0.94); long-generation (code) requests cost 5–8× more energy than short-answer requests | GreenBench §IV-A/B/E | same | 2026-09-09 | PREPRINT |
| F5 | llama.cpp 1B on M4 (base): **6.5–8.2 W system** measured for similar workloads | Jareño et al., "Energy-efficient large language models", Future Generation Computer Systems 182:108483 (2026) — full text paywalled; figure as cited in GreenBench [26] | https://doi.org/10.1016/j.future.2026.108483 | 2026-09-09 | PEER-REVIEWED (figure via citation) |
| F6 | Prefill/decode energy attribution methodology: E_total = E_prefill + E_decode = E_GPU + E_CPU + E_DRAM + E_other; phase-aligned sampling without wall meters | Niu et al., "TokenPowerBench", AAAI 2026 | https://ojs.aaai.org/index.php/AAAI/article/view/40535/44496 | 2026-09-09 | PEER-REVIEWED |
| F7 | Llama-3 family on H100: 1 B → 70 B params (70×) raises energy/token only **7.3×**; energy/token grows steadily with prompt length (bins 0–2 K / 2–5 K / 5–10 K) because prefill must process every input token; engine choice alone moves energy/token 25–40% (vLLM/TRT-LLM vs Transformers) | TokenPowerBench, AAAI 2026 | same as F6 | 2026-09-09 | PEER-REVIEWED |
| F8 | Apple-vs-Nvidia method: powermetrics for Apple SoC power, PyNVML @100 ms on Nvidia, E = ∫P dt, 2 warm-up runs, fixed seed, fixed 256-token outputs, mean of 3 runs; **M3 Ultra up to 23× more tokens/joule than RTX 5090** (Qwen2.5-1.5B, MLX); dense-70B decode: M3 Ultra 13.1 tok/s vs M4 Pro 5.1 tok/s (≈800 vs 273 GB/s UMA bandwidth — decode is bandwidth-bound) | Javat & Kazakov, "Silicon Showdown", arXiv 2605.00519v2 | https://arxiv.org/abs/2605.00519 | 2026-09-09 | PREPRINT |
| F9 | Five-runtimes Apple Silicon study (M2 Ultra 192 GB, Qwen-2.5 family, ≤100 K-token prompts): MLX best sustained decode throughput; llama.cpp efficient single-stream; Ollama lags throughput/TTFT (ergonomics-first); PyTorch MPS memory-limited. (Throughput/latency only — no joules.) | Rajesh et al., arXiv 2511.05502 | https://arxiv.org/abs/2511.05502 | 2026-09-09 | PREPRINT |
| F10 | `powermetrics` **requires root** — error "powermetrics must be invoked as the superuser" reproduced on this M4 Pro | Apple powermetrics; LOCAL-VERIFY | (local) | 2026-09-09 | VENDOR-DOC + LOCAL-VERIFY |
| F11 | zeus-apple-silicon: sudoless C++/Python lib reading Apple **IOReport** "Energy Model" channel group (private framework) — cumulative mJ counters for per-E/P-core, clusters, **DRAM, GPU, GPU SRAM, ANE**; window API around arbitrary code; <1 ms counter updates; 1 mJ resolution; windows <10 ms quantization-noisy; **M4 Pro explicitly in tested-chips table**. Accuracy caveat (their words): "model-based estimates derived from utilization, frequency, and voltage, rather than direct power sensor readings"; powermetrics man page: values "estimated and may be inaccurate" | ml.energy blog (2025-05-17) + repo README | https://ml.energy/blog/energy/measurement/profiling-llm-energy-consumption-on-macs/ · https://github.com/ml-energy/zeus-apple-silicon | 2026-09-09 | TOOL-DOC |
| F12 | Illustrative single window, Llama-3.2-3B Q6_K short prompt+answer on Apple Silicon: CPU 25.6 J, DRAM 16.3 J, **GPU 82.0 J** (GPU ≈ 2/3 of domain energy) | ml.energy blog output example | same blog | 2026-09-09 | COMMUNITY-MEASURED (illustrative, n=1) |
| F13 | macmon: **sudoless** monitor reading the same IOReport power data as powermetrics; JSON `pipe` mode (`-i` ms, `-s` N) with cpu/gpu/ane/**sys**/ram/gpu_ram power in W; documented idle snapshot (M3 Pro): cpu 0.20 W, gpu 0.017 W, **sys 5.88 W**, ram 0.12 W. Sudoless siblings: socpowerbud, NeoAsitop; sudo-requiring: asitop, pumas, mactop; codecarbon tracks macmon as the macOS sudoless option | macmon README; codecarbon issue #731 | https://github.com/vladkens/macmon · https://github.com/mlco2/codecarbon/issues/731 | 2026-09-09 | TOOL-DOC |
| F14 | ollama HTTP API final-response timing fields (ns): `total_duration`, `load_duration`, `prompt_eval_count`, `prompt_eval_cached_count`, `prompt_eval_duration` (uncached prefill), `eval_count`, `eval_duration` (decode); `keep_alive: 0` unloads; `seed`, `temperature`, `num_predict` enable deterministic fixed-length loops | ollama docs/api.md | https://github.com/ollama/ollama/blob/main/docs/api.md | 2026-09-09 | VENDOR-DOC |
| F15 | Battery-gauge cross-check is sudo-free: `ioreg -rn AppleSmartBattery` exposes `InstantAmperage` (mA) and `Voltage` (mV) → whole-device DC watts on battery (reads 0 on AC/charged — reproduced here); `top -stats power` works but is a per-process heuristic score, not watts | LOCAL-VERIFY | (local) | 2026-09-09 | LOCAL-VERIFY |
| F16 | H100-server reference point: ML.ENERGY-fitted model fE = 1.17e-6·P_active + 4.05e-5 Wh per output token (B=64, FP16, vLLM) → **8 B dense ≈ 0.05 Wh per 1K output tokens** on a batched H100 (server+PUE extra) | EcoLogits methodology (JOSS 2025) | https://ecologits.ai/latest/methodology/llm_inference/ | 2026-09-09 | PEER-REVIEWED (methodology) |
| F17 | Edge reference point: Raspberry Pi 4, qwen2.5-0.5B: 2.61 J/token | Husom et al., ACM TIOT 6(4), 2025 — as cited in GreenBench [11] | (via GreenBench) | 2026-09-09 | PEER-REVIEWED (figure via citation) |
| F18 | Server-scale Wh/query context (InferenceMAX-derived, methodology documented): DeepSeek-R1-671B fp8 8k-in/1k-out 0.96–3.74 Wh/query; 1k-in/8k-out 15–16.3 Wh/query; gpt-oss-120B fp4 0.11 and 0.49–0.61 Wh/query respectively — **prefill is far cheaper per token than decode**; laptop 3–14B runs are ~2 orders of magnitude below these | muxup.com analysis of InferenceMAX results | https://muxup.com/2026q1/per-query-energy-consumption-of-llms | 2026-09-09 | COMMUNITY-MEASURED |
| F19 | Decode dominates the energy budget across hardware; cutting generation early saves 44–89% of request energy | Solovyeva & Castor, arXiv 2602.05712 — as cited in GreenBench [12] | (via GreenBench) | 2026-09-09 | PREPRINT (figure via citation) |

Notes and cautions:
- **The GreenBench 0.47 W "package" number is not wall power.** IOReport per-domain counters (CPU/GPU compute domains) sum to well under a watt during decode because decode is memory-bandwidth-bound; DRAM, fabric, and uncore are excluded. Their own limitations section says so. Use their **system-level 0.09–0.25 J/tok** as the load-bearing figure, and expect our IOReport domain sums to look "small" by design (F12 shows GPU+DRAM+CPU ≈ 124 J for a 3B interaction).
- A Semantic Scholar / ResearchGate entry titled "Scaling Behavior of Energy per Token in LLM Inference on Apple Silicon" (Csikai & Borsos) carries an abstract identical to F9's study; it appears to be a duplicate record of arXiv 2511.05502 and could not be independently verified — excluded from the register.
- Engine sensitivity is large (F7: 25–40% on identical hardware; GreenBench quotes Niu at 25–55% for H100 engines; community reports say ollama's newer MLX backend roughly doubles decode tok/s on Apple Silicon). **Our coefficients must pin the runtime + backend version** (e.g., ollama build, llama.cpp commit, GGUF vs MLX) or they are meaningless across time.

## 2. Measurement-method matrix (macOS, Apple Silicon)

| Method | What it measures | Granularity | Privileges | Verdict for coefficient run |
|---|---|---|---|---|
| `powermetrics` (`--samplers cpu_power,gpu_power` etc.) | Apple's own aggregate CPU/GPU/ANE power estimates, per interval | Interval-based (e.g. 500 ms–2 s); aggregate only; must parse stdout | **sudo required** (F10, reproduced) | Gold-standard cross-check only; human types password once, off by default in automation |
| **zeus-apple-silicon** (`pip install zeus-apple-silicon`) | IOReport "Energy Model" cumulative mJ counters: per-core/cluster CPU, **DRAM, GPU, GPU SRAM, ANE** | Window-based around arbitrary code; ~1 mJ, sub-ms counters; windows ≥10 ms | **No sudo** (F11) | **PRIMARY** — in-process windows aligned exactly to prefill/decode phases |
| **macmon** (`brew install macmon`; `macmon pipe -i 500`) | Same IOReport power family incl. **`sys_power`** (W), cpu/gpu/ane/ram/gpu_ram; NDJSON stream | Interval-based, default 1 s, configurable ms; JSON | **No sudo** (F13) | SECONDARY — the only sudoless proxy for whole-SoC system power; log alongside runs |
| `ioreg -rn AppleSmartBattery` (`InstantAmperage`×`Voltage`) | Whole-device DC power from the battery gauge | ~seconds; whole machine only; **battery-only** (0 on AC) (F15) | No sudo | On-battery sanity check of sys_power calibration |
| `top -stats power` / Activity Monitor Energy Impact / NSProcessInfo | Per-process heuristic "power" score (Energy-Impact-style); NSProcessInfo exposes thermal state, not joules | Per-process; unitless heuristic | No sudo | **Rejected** for coefficients — no physical unit |
| Wall plug meter (e.g. Kill-A-Watt) | True AC power incl. efficiency losses | 1 s–1 min, whole machine | Physical access | Optional gold standard; not available in-script |

Key accuracy caveat that applies to every IOReport-derived number (powermetrics included, F11): Apple's counters are **model-based estimates** (utilization × frequency × voltage), not inline sensor readings. They are internally consistent and right for relative coefficients; treat absolute watts as ±(tens of) percent and cross-check with F15 on battery.

## 3. Recommended measurement procedure (coefficient run)

**Tooling.** Primary: `zeus-apple-silicon` windows (sudoless, phase-aligned, mJ, DRAM+GPU split; M4 Pro supported). Secondary: `macmon pipe -i 500` logged for the whole run (sudoless `sys_power` for whole-SoC level). One-off optional human step: `sudo powermetrics --samplers cpu_power,gpu_power -i 500` during a single decode loop to validate macmon/IOReport agreement. Do **not** gate the procedure on sudo.

**Runner.** ollama HTTP API (`stream:false`, `keep_alive` long enough to hold the model; `temperature:0`, fixed `seed`, fixed `num_predict`) — the response gives `prompt_eval_duration`/`prompt_eval_count` (prefill) and `eval_duration`/`eval_count` (decode) directly (F14). Record ollama version + backend (llama.cpp/GGUF vs MLX) per F19's caution.

**Benchmark protocol.**
1. Fixed prompt set: 5 distinct prompts per length class (~50, ~500, ~2000 input tokens), each generating a fixed 256 output tokens (mirrors F8's protocol). Distinct prompts avoid ollama prefix-cache hits (watch `prompt_eval_cached_count` = 0).
2. Warm-up: 2 untimed generations per model before measurement (clock/DFC stabilization, per F8; also fills weight residency).
3. N = 5 repeats per (model × prompt); one model in memory at a time; unload (`keep_alive:0`) between models (mirrors GreenBench's contention protocol).
4. Per request, open two zeus windows: `prefill` around request-dispatch→first-token (validate against `prompt_eval_duration`) and `decode` around generation (validate against `eval_duration`). Windows ≥100 ms are safely above the 10 ms quantization floor.
5. Idle baseline: 60 s zeus cumulative-energy delta before and after each model block → idle J/s for subtraction from system-level accounting (domain counters idle near zero; matters for `sys_power`).
6. Models: llama-3.2-3b, qwen2.5-7b or 8b-class, qwen 14b-class (Q4_K_M default; note quant in table). This machine: M4 Pro — matches F1–F4 hardware class directly.

**Prefill vs decode split.** Derived twice and required to agree: (a) energy windows (zeus) per phase; (b) phase power × ollama's phase durations (power sampled by macmon during the run). Prefill per-token energy = prefill J / `prompt_eval_count`; decode per-token = decode J / `eval_count`.

**Exact table fields to commit** (one CSV row per request, plus a summary table per model):
`model, quant, params_b, runtime_version, backend, chip, phase, n_in, n_out, prompt_cached_count, prefill_s, decode_s, e_cpu_mj, e_gpu_mj, e_gpu_sram_mj, e_dram_mj, e_domains_mj, sys_power_w_avg, idle_power_w, net_energy_mj, tok_per_s, j_per_tok_net, wh_per_1k_tok, tool_versions, timestamp`

## 4. Sanity bounds for the eval (8B-class, laptop-class silicon)

Expected envelope for **decode** (Q4_K_M, M4 Pro-class, single stream):

| Metric | Lower bound | Upper bound | Anchors |
|---|---|---|---|
| System-level J per output token, 3B–14B | 0.06 (3B) | 0.5 (14B, slow) | F3 (0.09–0.25 for 3–9 B), F4 throughput law, 8–12 W envelope (F2/F5) |
| **Wh per 1K output tokens, 8B-class, full system** | **≈ 0.03** | **≈ 0.08** | 0.13–0.19 J/tok × 1000 / 3600 (F3+F4 for 7–9 B) |
| Wh per 1K output tokens, 3B–14B range | ≈ 0.015 | ≈ 0.14 | F3 × F4 extrapolation |
| IOReport domain-sum (CPU+GPU+DRAM) share of system | ~⅓–⅔ | | F12 |
| Prefill vs decode per-token energy | prefill ≈ ⅒–⅕ of decode per token (but scales with input length) | | F7, F18 |

Acceptance gates for our measured coefficients:
- 8B-class net decode outside **0.01–0.3 Wh/1K output tokens** ⇒ measurement bug (unit error, idle not subtracted for sys-level, or phase misallocation).
- Anything ≥ 0.5 Wh/1K for ≤14B on M-Pro-class ⇒ almost certainly wall-clock/energy misalignment (that is server-scale, cf. F16's batched-H100 0.05 and F18's 671B-server figures).
- Domain-sum (IOReport) > system-level estimate ⇒ impossible ⇒ sys_power misread.
- Prefill energy ≫ decode energy per token ⇒ phase windows swapped (prefill runs hotter per second but far shorter).

Cross-reference anchors: batched H100 8B FP16 ≈ 0.05 Wh/1K (F16) — a laptop single-stream M4 Pro in the same order is the expected, literature-consistent result; Raspberry Pi 4 0.5B = 2.61 J/tok (F17) shows where the low end of edge hardware sits.
