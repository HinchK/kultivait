# kultivait

[![CI](https://github.com/Standard-Pentest/kultivait/actions/workflows/ci.yml/badge.svg)](https://github.com/Standard-Pentest/kultivait/actions/workflows/ci.yml)

An intelligent LLM routing layer. Every prompt is weighed by a local embedding
model, routed to the cheapest model that can carry it — your own garden first,
the cloud only when it earns its cost — and tallied in a savings ledger.

**The greenest token is the one you never send.**

- **Local-first routing** — an embedding classifier runs on your machine in
  milliseconds; no cloud call decides whether to make a cloud call.
- **Two compatible endpoints** — OpenAI (`/v1/chat/completions`) and
  Anthropic (`/v1/messages`), streaming and non-streaming, tools included.
- **An honest ledger** — every dispatch is recorded to
  `~/.kultivait/ledger.jsonl` with savings computed against frontier-model
  baseline pricing.
- **No telemetry** — nothing phones home. Classification, serving, and the
  ledger all stay on your machine.

## Requirements

- **macOS** (Apple Silicon with ≥ 24 GB unified memory for the full
  zero-to-local bootstrap; less works with a smaller garden)
- A local model runtime — either:
  - [ollama](https://ollama.com) with at least one general model pulled, or
  - [llama.cpp](https://github.com/ggml-org/llama.cpp)'s `llama-server` in
    router mode (see [below](#using-with-llamacpp-instead-of-ollama))
  — `kultivait init` detects whichever is running and adapts to whatever
  models you have
- An embedding model: `nomic-embed-text` via ollama is 274 MB; the
  llama.cpp bootstrap path downloads a 146 MB Q8_0 GGUF instead — either
  way, `kultivait init` handles it
- Python 3.12+ (managed automatically by [uv](https://docs.astral.sh/uv/)
  when you install by hand)
- Optional: `claude` / `agy` / `gemini` CLIs on PATH for cloud tiers

## Quickstart

```bash
curl -fsSL https://kultivait.ai/install.sh | sh
```

or, by hand: `uv tool install --from git+https://github.com/Standard-Pentest/kultivait kultivait`

```bash
kultivait init      # setup screen: survey, choose a garden, download, serve
kultivait serve     # proxy on http://localhost:4114
kultivait harvest   # watch the savings grow
```

`init` opens an interactive setup screen on first run: a preparation
checklist, then a chooser of gardens this machine can grow. It detects
whatever you have — your smallest capable model becomes the simple tier,
your largest becomes the reasoning tier, `claude`/`agy`/`gemini` CLIs
become cloud tiers if present. **No cloud CLIs? Local-only mode is a
first-class citizen**: cloud-worthy prompts are still recognized, served by
your best local model, and archived — `kultivait escalations --brief` hands
you a distilled, paste-ready brief to take to any frontier model yourself.
Skipping the screen (Esc) writes the same virtual-tier config; re-run
`kultivait init` anytime, or `kultivait init --setup` to reopen the screen
on a completed setup. Decisions live in `~/.kultivait/config.toml`; edit
freely, re-run `init` anytime.

## How it works

1. **Intercept** — your tools point at kultivait's OpenAI-compatible
   endpoint.
2. **Weigh** — `nomic-embed-text` (local, milliseconds) embeds the prompt
   and classifies it by cosine similarity to seed-prompt centroids. No cloud
   call decides whether to make a cloud call.
3. **Route** — trivial work goes to your simple tier, local reasoning to
   your reasoning tier, doc-grounded checks to a docs CLI (e.g. `agy`),
   cross-file architecture to an architect CLI (e.g. `claude`). Thin
   classification margins escalate one tier up: over-provisioning wastes
   cents, under-provisioning wastes an afternoon.
4. **Harvest** — every decision is recorded to `~/.kultivait/ledger.jsonl`
   with savings computed against frontier-model baseline pricing.

When a routing decision is contested, kultivait can fire a *trolltoll* —
holding the request briefly while a tollbooth offers you a route choice.
Those and other terms are defined in the [glossary](CONTEXT.md).

## Evidence

Claims below reproduce from the repo. Run them yourself:

```bash
uv run experiments/routing_trust.py   # → accuracy: 24/24, dangerous misroutes: 0/24
```

The routing approach was validated first: `experiments/routing_trust.py`
classified 24/24 held-out prompts correctly with zero dangerous misroutes
(cloud-worthy work sent to a weaker model).

The distiller model was chosen by a planted-fact recall eval
(`experiments/distill_eval/`, 5 models × 2 prompts × 3 transcripts).
Numbers below are recomputed from the checked-in artifact
(`experiments/distill_eval/results.json`):

| model | mean recall | tokens kept | avg time |
|---|---|---|---|
| **gemma4:latest** | **100%** | 69% | 28s |
| qwen3:14b | 96.3% | 55% | 18s |
| phi4:14b | 89.6% | 67% | 19s |
| qwen2.5:14b | 87.2% | 52% | 16s |
| llama3.1:8b | 86.9% | 54% | 9s |

There is no built-in distiller default: `kultivait init` picks your
machine's largest local model. Recall beats speed at a phase gate: a
dropped constraint is catastrophic, a slow gate is a coffee sip. Override
with `KULTIVAIT_DISTILL_MODEL=qwen3:14b` if you prefer the faster,
tighter-compressing runner-up. A hardened "never omit numbers" prompt
variant was also tested and rejected — it traded compression away for no
recall gain; model choice dominated.

## Commands

```bash
kultivait serve                    # run the routing proxy
kultivait choose                   # answer pending tolls out-of-band
kultivait run -- <command>         # transparent child process proxy wrapper
kultivait hook [shell|ide|loopback]# zero-config adoption & tool integration
kultivait dashboard                # open real-time web telemetry UI
kultivait route "why does this test deadlock?"    # dry-run a classification
kultivait prune --from explore --to plan transcript.txt   # phase-gate brief
kultivait escalations [--brief]    # cloud-worthy prompts served locally
kultivait harvest [--json]         # cumulative savings
kultivait distill corpus [--dry-run]              # preview anchor set & held-out roster
kultivait distill generate --live                 # dual-teacher synthetic data generation
kultivait distill train --base <base> --corpus-dir <dir>  # train QLoRA under resource ladder
kultivait distill eval --model <model> --heldout <path>   # 5-gate held-out validation
kultivait distill export --base <base> --adapter-path <path> # fuse & register with Ollama
kultivait shadow [--log <path>]                   # shadow log summary & cutover readiness
kultivait cutover --model <distillate> [--yes]    # flip live preprocessor + print rollback
```

`prune` distills a transcript into a FINDINGS / DECISIONS / CONSTRAINTS /
OPEN QUESTIONS brief using a local model, so hygiene itself costs nothing.
The full transcript is always composted to `~/.kultivait/compost/` —
distillation is lossy, and the compost pile is the escape hatch. The same
operation is available on the proxy as `POST /gate`.

## Endpoints & clients

Point any OpenAI-compatible client at `http://localhost:4114/v1` with
`model: auto`. Both endpoints support streaming (SSE).

An Anthropic-compatible `/v1/messages` endpoint (streaming and
non-streaming, content blocks, `system` param, and tool support) is also
served, so Anthropic-API clients can be pointed at the proxy:

```bash
ANTHROPIC_BASE_URL=http://localhost:4114 <your-tool>
```

Note: cloud tiers run through print-mode CLIs, which produce output only on
exit — those responses stream as a single final chunk. Local tiers stream
token-by-token.

Tool-bearing requests are always served by a local tool-capable tier, even
when classification points at a cloud tier: cloud CLIs run their own agent
loops and can't return client-side tool calls. The response's `kultivait`
metadata reports the reason in `fallback_reason` when this happens.

### Using with the Pi coding agent

Add a provider to `~/.pi/agent/models.json`:

```json
"kultivait": {
  "api": "openai-completions",
  "apiKey": "kultivait",
  "baseUrl": "http://127.0.0.1:4114/v1",
  "models": [{ "contextWindow": 131072, "id": "auto", "input": ["text"] }]
}
```

Then: `pi --provider kultivait --model auto`. Tool calls pass through on
the OpenAI endpoint — Pi's full agentic loop (read/bash/edit/write) runs
through the proxy, with every turn routed and tallied.

## Zero-config proxy adoption

Kultivait integrates with existing developer tools, coding agents, and IDEs
without requiring manual API rewrite layers or client code modifications.
Choose the adoption path that matches your workflow:

### 1. Single-command process wrapping (`kultivait run -- <cmd>`)

Wrap any command or agent loop directly (`kultivait run -- claude`).
Injects `OPENAI_BASE_URL` and `ANTHROPIC_BASE_URL` into the child process
environment, forwards POSIX signals, and preserves exit codes with zero
persistent configuration:

```bash
kultivait run -- claude
kultivait run -- pi --provider openai --model auto
kultivait run -- python test_agents.py
```

**Rollback**: none required; environment variables are scoped strictly to
the child process and disappear on exit.

### 2. Shell session integration (`eval "$(kultivait hook)"`)

Inject proxy environment variables across your entire interactive shell
session in four supported shells (`sh`, `bash`, `zsh`, `fish`):

```bash
eval "$(kultivait hook)"                 # activate (sh, bash, zsh)
kultivait hook --shell fish | source     # fish
kultivait hook --check                   # verify active hook status
eval "$(kultivait hook --unset)"         # rollback
```

### 3. IDE auto-patching (`kultivait hook ide`)

Detect and patch local editor settings (Cursor, VS Code, Windsurf) to
route LLM requests through the local proxy. Atomic backups
(`.kultivait-bak`) and instant rollback:

```bash
kultivait hook ide --dry-run     # preview modifications safely
kultivait hook ide               # patch all detected IDEs
kultivait hook ide --ide cursor  # target a specific IDE
kultivait hook ide --restore     # rollback
```

### 4. Advanced loopback redirection (`kultivait hook loopback`)

For global OS-level transparent interception, generate review-ready
configuration templates:

```bash
kultivait hook loopback --generate-hosts   # /etc/hosts entries (routes api.anthropic.com & api.openai.com to 127.0.0.1)
kultivait hook loopback --generate-pf      # macOS packet filter rules
kultivait hook loopback --generate-cert    # TLS certificate generation & trust instructions
kultivait hook loopback --generate-uninstall
```

- **Zero-root standard**: `hook loopback` only produces configuration text
  for review. Applying changes requires explicit `sudo` commands executed
  manually by the operator.
- **TLS MITM caveat**: HTTPS interception requires creating and trusting a
  local self-signed root certificate (`kultivait-proxy.crt`).

### Trade-offs & safety

| Adoption path | Rollback | Result |
|---|---|---|
| Process wrapper | Terminate command (`Ctrl+C`) | Child exits; no residual state |
| Shell hook | `eval "$(kultivait hook --unset)"` | Unsets session environment variables |
| IDE patcher | `kultivait hook ide --restore` | Atomically restores `.kultivait-bak` |
| Loopback | `--generate-uninstall` output | Reverts `/etc/hosts`, `pf` rules, trusted cert |

**Recursion safety (`PROXY_ENV_STRIP`)**: cloud-worthy work may be
dispatched to upstream CLI backends (e.g. `claude`, `gemini`, `codex`,
`opencode`, `agy`). Kultivait strips `OPENAI_BASE_URL`,
`ANTHROPIC_BASE_URL`, and related variables before spawning any upstream
CLI process, so upstream tools always connect directly to native provider
endpoints — no proxy recursion loops.

## Direct REST frontier providers & API tiers

In addition to local runtimes and CLI backends, kultivait supports direct
REST API frontier providers (`anthropic`, `openai`, `openrouter`).

### 1. Configure an API tier

Add an `api`-kind tier to `~/.kultivait/config.toml`:

```toml
[[tiers]]
name = "anthropic"
role = "architect"
kind = "api"
model = "claude-3-7-sonnet-20250219"
price_in = 3.0
price_out = 15.0

[[tiers]]
name = "openai"
role = "architect"
kind = "api"
model = "gpt-4o"
price_in = 2.5
price_out = 10.0

[[tiers]]
name = "openrouter"
role = "architect"
kind = "api"
model = "anthropic/claude-3.7-sonnet"
price_in = 3.0
price_out = 15.0
```

Unpriced API tiers load a conservative default ($3.00 in / $15.00 out per
MTok) with a warning to ensure accurate ledger accounting.

### 2. Configure credentials

API keys resolve from three sources with fixed precedence:

> **Funded balance is a separate precondition.** A key can authenticate and
> pass the route menu's presence probe while the account holds no credits —
> OpenRouter then answers every completion with HTTP 402. **Probe success ≠
> serve success**: the probe checks auth, not balance.

1. **Environment variables** (highest precedence):
   ```bash
   export ANTHROPIC_API_KEY="sk-ant-..."
   export OPENAI_API_KEY="sk-..."
   export OPENROUTER_API_KEY="sk-or-..."
   ```
2. **OS keychain** (macOS `security`, service `kultivait`):
   ```bash
   security add-generic-password -s kultivait -a anthropic -w "sk-ant-..."
   security add-generic-password -s kultivait -a openai -w "sk-..."
   security add-generic-password -s kultivait -a openrouter -w "sk-or-..."
   ```
3. **Credentials file** (`~/.kultivait/credentials.toml`, `0600`):
   ```toml
   [anthropic]
   api_key = "sk-ant-..."

   [openai]
   api_key = "sk-..."

   [openrouter]
   api_key = "sk-or-..."
   ```

> **Security note**: API keys never live in `config.toml` and are never
> logged or exposed.

## Prompt caching & cache economics

For pay-per-token API frontier providers, kultivait features proxy-owned
**prompt caching** ([ADR 0018](docs/adr/0018-cache-breakpoints.md) &
[ADR 0005](docs/adr/0005-cost-model-duality.md) amendment). Multi-turn
agent loops automatically benefit from upstream prefix caching without
manual prompt engineering.

- **Single deterministic policy** — the proxy is the sole cache policy
  owner. Client-provided `cache_control` is recursively stripped before
  translation.
- **Dual-level placement** — for prompts exceeding 1,024 tokens, canonical
  cache breakpoints are injected at the last tool definition (`tools[-1]`)
  and at the system prompt, preventing terminal cache collapse as message
  history grows across turns.
- **Session stickiness** — the conversation fingerprint (hash of system
  prompt + first user message) is forwarded as `session_id` on OpenRouter
  dispatches for routing affinity to warm cache instances.
- **TTL knob** — set `cache_ttl = "5m"` (default, 1.25× write multiplier)
  or `"1h"` (2.0×) on any `api`-kind tier. Anthropic reads bill at 0.1×;
  OpenAI GPT-4o caches implicitly and GPT-5.x reads bill at 0.1×;
  llama.cpp-class targets are cache-blind and report zero cached tokens.

## The harvest

`savings ledger` output — routing savings, metered cash, and cache savings
as three orthogonal lines:

```bash
$ kultivait harvest
the harvest — season to date

  prompts routed     14  (57% local)
  local tokens       42,150
  spent              $0.04
  frontier baseline  $0.18
  notional spent     $0.04
  metered cash out   $0.04
  kept in pocket     $0.14

  cache economics
    kept via cache     $0.0093
    hit rate           40%  (6 cache-bearing dispatches)
    reads per write    1.0
    ttl cohorts        5m: 6 dsp $0.0093
```

`kultivait dashboard` opens the real-time web view of the same data.

## Escalations: when the garden isn't enough

Every tool-fallback is also archived as an *escalation* — the full
conversation, saved instantly off the request path. When you decide a local
answer wasn't good enough:

```bash
kultivait escalations              # list cloud-worthy prompts served locally
kultivait escalations --brief      # distill the latest into a paste-ready brief
```

The brief (TASK / CONTEXT / PROGRESS / NEEDED) is distilled by your local
model and names the recommended target — "take this to Claude" — so
escalating costs one paste instead of re-explaining the whole session.
Routing knows its limits; hygiene makes the handoff cheap.

## Model distillation & shadow cutover

Kultivait's preprocessor evaluates contested prompts to judge whether
local models are sufficient. The **distillation pipeline** closes the
loop: turning harvested routing data (toll choices, escalations, ledger
entries) into fine-tuned local models (`qwen3.5:4b` or
`llama-3.2-3b-instruct` distillates) to improve local judgment accuracy,
reduce unnecessary tolls, and eliminate misroutes.

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

- **`distill corpus [--dry-run]`** prints a preview report of the anchor
  set and the permanent held-out roster; the corpus files themselves are
  written by `distill generate`. Tier labels follow a strict truth
  hierarchy: human toll choices (gold), execution outcomes (silver), and
  eval records (bronze). Real verdict-bearing cases are permanently held
  out and never trained on.
- **`distill generate [--live]`** runs the dual-teacher synthetic
  generator targeting balanced strata (40% contested / 30% local / 30%
  frontier):
  - **Judge teacher**: the CLI default pins a neutral-family judge
    (`--judge-model x-ai/grok-4.6` via OpenRouter; `opencode` is the
    no-argument fallback) that performs an independent second-pass tier
    classification — the **agreement filter**.
  - **Rewriter teacher** (`claude` CLI): synthesizes prompt rewrites;
    band-targeted variations are drafted locally by the vary model
    (`qwen3:14b` by default).
  - **3-stage filter**: exact hash + embedding deduplication
    (cosine < 0.92), JSON contract validation, planted-fact recall checks.
  - *Safety*: requires `--live` to dispatch real subscription CLI
    teachers; refuses to generate from unverified stubs.
- **`distill train --base <base>`** trains a QLoRA adapter with `mlx-lm`
  on supported bases, strictly enforcing the **resource ladder** on
  unified memory: batch 4→2→1, adapted layers 16→8→4, gradient
  checkpointing — aborting rather than causing memory swap.
- **`distill eval --model <model>`** validates distillates against the
  permanent held-out set through the production generate path. Five
  acceptance gates: zero dangerous misroutes; 100% parse rate; latency
  p50 ≤ 8.0 s / max ≤ 15.0 s; agreement ≥ incumbent; two-sided band
  discipline (contested floor ≥ 50%, flood ceiling ≤ 25%) across
  temperature sweeps.
- **`distill export`** fuses QLoRA weights via `mlx_lm.fuse`, generates
  an Ollama `Modelfile`, and registers the model as
  `kv-judge-<base>-g<gen>` (quantized `q4_K_M`, ≤ 4 GB resident).

### Shadow serving & cutover readiness

A gate-passing distillate can be shadowed on live traffic before serving
real routing verdicts:

```toml
# ~/.kultivait/config.toml
[distill]
model = "qwen3.5:4b"                     # live preprocessor seat
shadow_model = "kv-judge-llama32-3b-g1"  # candidate distillate
shadow_mode = "on"                       # "off" | "on"
shadow_sample_rate = 1.0                 # 100% of contested requests
```

The shadow pass runs asynchronously after the live response has been sent
(zero latency impact), is exception-isolated, and logs to
`~/.kultivait/shadow.jsonl` — outside the main ledger, so harvest cost
metrics stay clean. `kultivait shadow` reports ADR 0017 cutover readiness:
n ≥ 30 shadowed requests, agreement ≥ 90% with the incumbent, zero
anomalies.

Automated cutovers are deliberately disallowed — model deployment is
always a human decision:

```bash
kultivait cutover --model kv-judge-llama32-3b-g1   # [y/N] confirm, atomic config update
```

`DistillSeat` resolves the `[distill] model` per request, so rollback is
instant and needs no server restart.

## Setup deep-dive

### Zero to local: `kultivait init` on a Mac

On an Apple Silicon Mac with at least 24 GB of unified memory and no local
runtime installed, the setup screen offers the whole bootstrap itself (the
zero-to-local path is llama.cpp): a preparation checklist (hardware →
runtime → survey → recommendations), then a garden chooser — the tuned
bundle for your RAM, a reasoning-only variant, or models already on this
machine. **Selecting a garden is the consent**: the detail panel shows
exactly what will download (contents, sizes, RAM fit, why this garden)
before Enter commits. The download carries rate/ETA and
Esc-cancel-with-confirm (.part files stay resumable); a failed server
start offers `r Retry` / `c Choose another`. The one extra confirm is
sudo: raising the GPU memory cap asks again, in-screen, before sudo ever
prompts for a password.

**Ollama and llama.cpp take turns — never both up.** If ollama is
installed but not serving, preparation starts it for you (`brew services
start ollama`) and lists its models as offerings, each with a parameter
analysis. Picking a llama.cpp garden stops ollama (and verifies the port
went quiet) *before* llama-server launches; a "Switch to ollama" row does
the reverse. A runtime that refuses to stop aborts the pivot rather than
risk both serving at once.

Skipping (Esc) is a first-class outcome — it still writes a virtual-tier
config plus an onboarding marker (`~/.kultivait/onboarding.json`), and
`kultivait init` re-runs safely: finished steps are skipped and
size-checked downloads resume. Opt out with `kultivait init --no-setup`;
the screen is also skipped when stdin is not a TTY. Setting
`KULTIVAIT_RUNTIME` forces the runtime but does not skip the screen — it
only suppresses download offerings inside it.

Each GGUF is verified against a pinned upstream SHA256 (Hugging Face's
LFS oid) before it's promoted from its `.part` file, so mutable
`resolve/main` refs can't slip corrupt or swapped bytes past you — a
mismatch is discarded rather than Range-resumed.

### Using with llama.cpp instead of ollama

Run `llama-server` in **router mode** — launched without `-m`, it lists
your GGUF models at `/v1/models` and loads whichever one a request names.
One wrinkle: the router won't serve `/v1/embeddings` unless the embedding
model is marked as such in a preset file:

```ini
# presets.ini
[nomic-embed-text-v1.5.Q8_0]
model = /path/to/models/nomic-embed-text-v1.5.Q8_0.gguf
embedding = 1
```

```bash
llama-server --models-dir ~/models --models-preset presets.ini --jinja
kultivait init    # detects the router on :8080
```

(`--jinja` enables tool calls.) `init` surveys the router's model list,
sizes each GGUF from disk, and picks tiers exactly as it does for ollama —
downloadable suggestions the router advertises but you haven't pulled are
ignored. If both runtimes are running, ollama wins; force a choice with
`KULTIVAIT_RUNTIME=llamacpp`. Non-default ports and model dirs:
`KULTIVAIT_LLAMACPP_URL`, `KULTIVAIT_LLAMACPP_MODELS_DIR`.

Prefer a dedicated embedding server instead of the preset? Run
`llama-server -m nomic-embed.gguf --embedding --port 8081` and set
`embed_base_url = "http://localhost:8081"` in `~/.kultivait/config.toml`.
Empty `embed_base_url` means "same server as chat".

Context size for llama.cpp is set at server launch (`--ctx-size`), not per
request — kultivait's `num_ctx` and truncation detection apply to ollama
only.

## Glossary

Domain terms — trolltoll, tollbooth, verdict, escalation, distillate,
kept-via-cache, and friends — are defined in [CONTEXT.md](CONTEXT.md).

## Development

```bash
uv run pytest
```

The landing page lives in `landing/index.html`. This repo is developed as
a coordinated multi-agent herd (looper, architect, docs and GitHub
workers) with milestone maps on the issue tracker — tickets and Wayfinder
maps live here on GitHub.

## Roadmap

- Distillation-quality eval harness: automated planted-fact recall scoring
  across transcripts (recall spans 86.9–100% across
  `experiments/distill_eval/results.json` models today)
- Ambient gates via agent-framework hooks (e.g. Claude Code hooks), so
  pruning happens at phase boundaries without manual invocation
- Watt-hour estimation in the ledger
- Learned centroids from your own routing history

## License

[MIT](LICENSE)
