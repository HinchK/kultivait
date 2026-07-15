# kultivait init: hardware scan + llama.cpp bootstrap — design

Date: 2026-07-14
Branch: `pivot/initsetup-hardwaretuning-zerotohere-o`
Status: approved in brainstorming session

## Problem

`kultivait init` today assumes a local runtime (ollama or llama-server) is
already installed *and running*; on a bare machine it surveys nothing, writes
a config full of virtual tiers, and leaves the user to figure out local-model
setup themselves. The target user — someone on a capable Apple Silicon Mac
who has never installed a local LLM runtime — gets no path from zero to a
working local garden.

## Goal

`kultivait init` scans the machine's hardware. If the machine is capable of
running local models (Apple Silicon, ≥24GB unified RAM) and neither ollama
nor llama.cpp is installed, init offers to install and tune llama.cpp using
current Apple Silicon best practices, download right-sized models, and start
the server — each mutating step behind its own confirmation. After bootstrap
(or if a runtime was already running), the existing survey → `config.toml`
flow proceeds unchanged.

## Decisions made during brainstorming

| Decision | Choice |
|---|---|
| Hardware gate | Any Apple Silicon (M1+, any form factor), ≥24GB unified RAM |
| Automation level | Full setup driven by init, step-by-step `[Y/n]` confirms |
| Model selection | Opinionated per-RAM defaults (built-in table), confirmed once with sizes shown |
| Server lifecycle | Generated start script only — no LaunchAgent, kultivait does not supervise llama-server |
| Structure | New `hardware.py` (pure scan/plan) + `bootstrap.py` (side effects), composed in `cmd_init` |

## Research findings (basis for tuning constants)

- **Install path:** the official Homebrew formula (`brew install llama.cpp`)
  ships `llama-server`/`llama-cli` with Metal enabled by default on Apple
  Silicon and tracks upstream releases. Source builds (as in the Medium
  article that prompted this work) are unnecessary.
- **GPU wired-memory cap is the main tuning lever.** macOS caps GPU-usable
  unified memory at ~66.7% of RAM for machines with ≤36GB, ~75% for >36GB.
  `sudo sysctl iogpu.wired_limit_mb=N` raises it; leave ≥8GB for the OS; the
  setting resets on reboot.
- **Server flags that matter on M-series:** `-ngl 99` (all layers on GPU),
  `--flash-attn` (own Metal implementation; hard prerequisite for KV-cache
  quantization), `--cache-type-k q8_0 --cache-type-v q8_0` (halves KV memory,
  negligible quality loss), explicit `-c <ctx>` (never 0 = model max),
  `-b 2048 -ub 2048`.
- **Flags that are x86 folklore, skip:** `--numa`, `--main-gpu`,
  `--tensor-split`, CPU-affinity flags.
- **Memory budget:** weights + KV cache + activations + OS overhead must fit
  the wired limit.

Sources: [Homebrew formula](https://formulae.brew.sh/formula/llama.cpp),
[llama.cpp install docs](https://github.com/ggml-org/llama.cpp/blob/master/docs/install.md),
[Tune llama.cpp on Apple Silicon: 7 flags](https://medium.com/@michael.hannecke/tuning-llama-cpp-on-apple-silicon-843f37a6c3dc),
[Tuning llama-server on Apple Silicon](https://medium.com/@michael.hannecke/tuning-llama-server-on-apple-silicon-9b3e778ab100),
[Override macOS Metal VRAM cap](https://github.com/ivanopcode/devnote-override-macos-metal-vram-cap),
[Optimizing VRAM settings on macOS](https://blog.peddals.com/en/fine-tune-vram-size-of-mac-for-llm/),
[Apple Silicon local-LLM limits](https://stencel.io/posts/apple-silicon-limitations-with-usage-on-local-llm%20.html).

## Architecture

Two new modules mirror the repo's pure-core / side-effect-edges convention
(`config.detect()` is the model):

```
cmd_init (cli.py)
  ├─ hardware.scan()          pure parse of sysctl output -> HardwareProfile
  ├─ runtime census           _reachable() (running?) + shutil.which (installed?)
  ├─ hardware.plan(profile)   pure -> SetupPlan (eligibility, models, flags, wired-limit advice)
  ├─ bootstrap.run(plan, …)   side effects: brew, downloads, artifacts, sysctl offer, server start
  └─ existing survey -> save_config()   (unchanged)
```

### `hardware.py`

```python
@dataclass(frozen=True)
class HardwareProfile:
    platform: str          # "darwin" | "linux" | ...
    chip: str              # "Apple M3 Pro" | "Intel(R) Core..." | ""
    is_apple_silicon: bool
    ram_gb: float          # hw.memsize / 2**30

@dataclass(frozen=True)
class SetupPlan:
    eligible: bool
    reason: str                  # human-readable, always set (why / why not)
    models: list[ModelPick]      # role, hf_repo, filename, approx_bytes, kv_bytes_per_token
    ctx: int
    server_flags: list[str]
    default_gpu_cap_mb: int
    wired_limit_mb: int | None   # None = default cap suffices, don't offer sysctl
```

- `scan(sysctl_output: str | None = None) -> HardwareProfile` — parses
  `machdep.cpu.brand_string`, `hw.memsize`, and platform. The subprocess call
  lives in a thin `_read_sysctl()` helper; `scan` accepts raw text so tests
  feed fixture strings.
- `plan(profile: HardwareProfile) -> SetupPlan` — pure. Eligibility:
  `is_apple_silicon and ram_gb >= 24`. Ineligible profiles still get a
  `SetupPlan` with `eligible=False` and a specific `reason` (Intel Mac /
  <24GB / non-macOS) so cmd_init can explain rather than silently skip.

**Default GPU cap** (macOS behavior, computed not guessed):
`ram_gb <= 36 → ram_mb * 2/3`, `ram_gb > 36 → ram_mb * 3/4`.

**Model table** (`MODEL_TABLE` constant; exact HF repo names, filenames, and
byte sizes are pinned during implementation by checking Hugging Face — the
rows below are the intended defaults):

| RAM tier | simple | reasoning (doubles as distiller) | ctx |
|---|---|---|---|
| 24GB | Qwen3-4B Q4_K_M (~2.5GB) | Qwen3-14B Q4_K_M (~9.0GB) | 16384 |
| 32GB | Qwen3-4B Q4_K_M | Qwen3-14B Q4_K_M | 32768 |
| 48GB | Qwen3-4B Q4_K_M | Qwen3-32B Q4_K_M (~19.8GB) | 32768 |
| ≥64GB | Qwen3-8B Q4_K_M (~5.0GB) | Qwen3-32B Q5_K_M (~23GB) | 32768 |

Plus `nomic-embed-text-v1.5` Q8_0 GGUF (~280MB) in every tier — it is what
`detect()`/`_require_embed_model` already prefer. Role names match
`config.ROLES`; after bootstrap the ordinary survey classifies these models
into tiers exactly as if the user had installed them by hand.

**KV-cache estimate:** each `ModelPick` carries `kv_bytes_per_token` (q8_0,
from the model's layer/GQA geometry — e.g. ~80KB/token for the 14B class,
~100KB/token for the 32B class; values pinned alongside the table).

**Wired-limit advice:** budget = sum of all planned model bytes + KV bytes
for the largest model at target ctx + 2GB margin. If budget >
`default_gpu_cap_mb`, set `wired_limit_mb = min(budget_mb_rounded_up_to_GB,
(ram_gb - 8) * 1024)`; otherwise `None`. The plan must always fit
`(ram_gb - 8) * 1024` — if it doesn't, drop ctx one notch (32768 → 16384 →
8192) until it fits; the table above already fits, this rule guards future
edits.

**Server flags** (router mode, one server for chat + embedding):

```
--models-dir ~/Library/Caches/llama.cpp
--models-preset ~/.kultivait/llamacpp-presets.ini
--jinja -ngl 99 --flash-attn
--cache-type-k q8_0 --cache-type-v q8_0
-c <ctx> -b 2048 -ub 2048
--port 8080
```

### `bootstrap.py`

`run(plan, *, confirm, run_cmd, http) -> BootstrapResult` — orchestrates the
steps below. `confirm`, `run_cmd`, and the HTTP client are injected so tests
never touch the real system. Every step is **idempotent**: already-satisfied
steps are skipped, so re-running `kultivait init` converges.

1. **Install llama.cpp.** Skip if `llama-server` is on PATH. Requires
   Homebrew: if `brew` is missing, print Homebrew's install instructions and
   switch to *advisory mode* — print every remaining step as copy-paste
   commands, then continue to the survey (which will find nothing running
   and write a virtual-tier config, same as today). Otherwise run
   `brew install llama.cpp` after confirmation.
2. **Download models.** Show the full list with per-file and total sizes,
   confirm once, then stream each GGUF via httpx into
   `~/Library/Caches/llama.cpp` (the dir `cli._gguf_dirs()` already scans;
   `KULTIVAIT_LLAMACPP_MODELS_DIR`/`LLAMA_CACHE` overrides respected).
   Progress shown per file; interrupted downloads leave a `.part` file and
   resume via HTTP `Range` on re-run. Files already present (matching size)
   are skipped.
3. **Write artifacts** (always regenerated from the current plan, like
   `config.toml`):
   - `~/.kultivait/llamacpp-presets.ini` — per-model preset entries;
     `embedding = 1` on the nomic-embed entry.
   - `~/.kultivait/start-llamacpp.sh` (chmod +x) — the tuned launch command
     with output redirected to `~/.kultivait/llamacpp.log`. The sysctl
     wired-limit line is included as a *comment* with a one-line explanation
     (it needs sudo and resets on reboot; the script must run without it).
4. **Offer the wired-limit bump** — only when `plan.wired_limit_mb` is set.
   Print the exact `sudo sysctl iogpu.wired_limit_mb=N` command, explain
   what it does and that it resets on reboot, ask whether to run it now
   (sudo prompts for the password itself — consent is explicit twice).
   Declining continues without it.
5. **Start the server.** Run the start script detached, poll
   `http://localhost:8080/v1/models` until healthy with a 60s ceiling (first
   model load can be slow). On timeout/failure: print the last ~20 lines of
   `~/.kultivait/llamacpp.log`, tell the user how to start manually, and
   exit non-zero — do not fall through to a survey that would find nothing.

### `cmd_init` integration

```
scan -> census:
  runtime running            -> existing flow, unchanged
  ollama installed, stopped  -> print "start ollama (ollama serve), then re-run init"; no bootstrap offer
  llama-server installed, stopped:
    plan.eligible            -> offer steps 2–5 (skip install)
    not eligible             -> print how to start llama-server manually; no sizing offer
  neither installed:
    plan.eligible            -> offer full bootstrap (steps 1–5)
    not eligible             -> print plan.reason + cloud-CLI-only note; existing flow
then: existing survey -> save_config (runtime="llamacpp" after bootstrap)
```

Interactivity guards: all offers are skipped when stdin is not a TTY, or
when `kultivait init --no-setup` is passed — behavior is then identical to
today's init. Prompts default to yes (`[Y/n]`) since every step was already
explicitly offered.

## Error handling summary

| Failure | Behavior |
|---|---|
| No Homebrew | Advisory mode: print manual commands, continue to survey |
| `brew install` fails | Show brew's output, abort bootstrap, continue to survey |
| Download interrupted | `.part` file kept; resume on next `init` via Range request |
| sudo declined / sysctl fails | Continue without bump (plan fits default cap by construction) |
| Server health check times out | Tail the log, print manual-start hint, exit non-zero |
| Non-TTY / `--no-setup` | No offers; today's behavior exactly |

## Testing

No network, no subprocess, no sudo in tests — the repo's existing pattern
(`tests/test_config.py`, `tests/test_cli_runtime.py`, mocked httpx in
`tests/test_backends.py`).

- `tests/test_hardware.py`
  - `scan()` on fixture sysctl text: M1/M2/M3/M4 brand strings, Intel Mac,
    Linux (no sysctl), odd RAM sizes.
  - `plan()` table-driven: eligibility edges (16/23.9/24/32GB), the 36GB cap
    boundary (66.7% vs 75%), model picks per tier, ctx, wired-limit offered
    only when the budget exceeds the default cap, ctx step-down rule.
- `tests/test_bootstrap.py`
  - Injected fakes for confirm/run_cmd/http + `tmp_path` home.
  - Idempotency: satisfied steps skipped (binary present, files present).
  - Decline paths at each confirm; advisory mode when brew missing.
  - Artifact golden checks: start script contains the plan's flags; INI
    marks the embed model; sysctl line present only as a comment.
  - Download resume: existing `.part` triggers a Range request.
  - Health-poll timeout surfaces log tail and non-zero exit.
- `cmd_init` dispatch (extend `tests/test_cli_runtime.py` style): bootstrap
  offered only for eligible-and-bare; running ollama unchanged; non-TTY and
  `--no-setup` skip offers.

## Docs

README: replace/augment the manual "Using with llama.cpp" setup prose with a
short "Zero to local: `kultivait init` on a Mac" subsection. The tuning
rationale and sizing table stay in this spec, not the README.

## Out of scope

- LaunchAgent / auto-start on login (decided: start script only)
- kultivait supervising llama-server as a child process
- Linux or Windows bootstrap; Intel Mac bootstrap
- Installing ollama (users who want ollama install it themselves; init
  detects and adapts as it always has)
- Model benchmarking or eval during init
- Persisting the sysctl setting across reboots (documented in the start
  script comment instead)
