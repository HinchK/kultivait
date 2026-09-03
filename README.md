# kultivait

An intelligent LLM routing layer. Every prompt is weighed by a local embedding
model, routed to the cheapest model that can carry it — your own garden first,
the cloud only when it earns its cost — and tallied in a savings ledger.

**The greenest token is the one you never send.**

## How it works

1. **Intercept** — your tools point at kultivait's OpenAI-compatible endpoint.
2. **Weigh** — `nomic-embed-text` (274 MB, local, milliseconds) embeds the prompt
   and classifies it by cosine similarity to seed-prompt centroids. No cloud
   call decides whether to make a cloud call.
3. **Route** — trivial work → `llama3.1:8b`, local reasoning → `qwen3:14b`,
   doc-grounded checks → Gemini via `agy`, cross-file architecture → `claude`.
   Thin classification margins escalate one tier up: over-provisioning wastes
   cents, under-provisioning wastes an afternoon.
4. **Harvest** — every decision is recorded to `~/.kultivait/ledger.jsonl` with
   savings computed against frontier-model baseline pricing.

The routing approach was validated first: `experiments/routing_trust.py`
classified 24/24 held-out prompts correctly with zero dangerous misroutes
(cloud-worthy work sent to a weaker model).

## Quickstart

```bash
curl -fsSL https://kultivait.ai/install.sh | sh
```

or, by hand: `uv tool install --from git+https://github.com/Standard-Pentest/kultivaite kultivait`

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
kultivait distill corpus [--dry-run]              # assemble anchor set & held-out roster
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

The distiller model was chosen by a planted-fact recall eval
(`experiments/distill_eval/`, 5 models x 2 prompts x 3 transcripts):

| model | mean recall | tokens kept | avg time |
|---|---|---|---|
| **gemma4:latest** (default) | **100%** | 61% | 29s |
| qwen3:14b | 96.3% | 44% | 15s |
| phi4:14b | 92.6% | 65% | 18s |
| qwen2.5:14b | 90.2% | 49% | 16s |
| llama3.1:8b | 86.5% | 44% | 8s |

Recall beats speed at a phase gate: a dropped constraint is catastrophic,
a slow gate is a coffee sip. Override with `KULTIVAIT_DISTILL_MODEL=qwen3:14b`
if you prefer the faster, tighter-compressing runner-up. A hardened
"never omit numbers" prompt variant was also tested and rejected — it traded
compression away for no recall gain; model choice dominated.

Point any OpenAI-compatible client at `http://localhost:4114/v1` with
`model: auto`. Both endpoints support streaming (SSE).

An Anthropic-compatible `/v1/messages` endpoint (streaming and
non-streaming, content blocks and `system` param handled) is also served,
so Anthropic-API clients can be pointed at the proxy:

```bash
ANTHROPIC_BASE_URL=http://localhost:4114 <your-tool>
```

Note: cloud tiers run through print-mode CLIs, which produce output only on
exit — those responses stream as a single final chunk. Local tiers stream
token-by-token.

### Zero-Config Proxy Adoption

Kultivait integrates seamlessly with existing developer tools, coding agents, and IDEs without requiring manual API rewrite layers or client code modifications. Choose the adoption path that matches your workflow:

#### 1. Single-Command Process Wrapping (`kultivait run -- <cmd>`)

Wrap any command or agent loop directly (`kultivait run -- claude`). Injects `OPENAI_BASE_URL` and `ANTHROPIC_BASE_URL` into the child process environment, forwards POSIX signals, and preserves exit codes with zero persistent configuration:

```bash
# Wrap agent CLI loops or scripts
kultivait run -- claude
kultivait run -- pi --provider openai --model auto
kultivait run -- python test_agents.py
```

- **Rollback**: None required; environment variables are scoped strictly to the child process and disappear on exit.

#### 2. Shell Session Integration (`eval "$(kultivait hook)"`)

Inject proxy environment variables across your entire interactive shell session across 4 supported shells (`sh`, `bash`, `zsh`, `fish`):

```bash
# Activate in current shell (sh, bash, zsh)
eval "$(kultivait hook)"

# Fish shell syntax
kultivait hook --shell fish | source

# Verify active hook status
kultivait hook --check

# Rollback: deactivate and unset variables
eval "$(kultivait hook --unset)"
# For fish:
kultivait hook --shell fish --unset | source
```

#### 3. IDE Auto-Patching (`kultivait hook ide`)

Automatically detect and patch local editor settings (Cursor, VS Code, Windsurf) to route LLM requests through the local proxy. Features atomic backups (`.kultivait-bak`) and instant rollback:

```bash
# Preview modifications safely
kultivait hook ide --dry-run

# Patch all detected IDEs
kultivait hook ide

# Target a specific IDE
kultivait hook ide --ide cursor

# Rollback: restore original settings from backup
kultivait hook ide --restore
```

#### 4. Advanced Loopback Redirection (`kultivait hook loopback`)

For global OS-level transparent interception without application settings changes, generate review-ready configuration templates:

```bash
# Generate /etc/hosts entries (routes api.anthropic.com & api.openai.com to 127.0.0.1)
kultivait hook loopback --generate-hosts

# Generate macOS packet filter (pf) rules
kultivait hook loopback --generate-pf

# Generate TLS certificate generation & trust instructions
kultivait hook loopback --generate-cert

# Generate uninstallation instructions
kultivait hook loopback --generate-uninstall
```

- **Sudo / Root Responsibility**: Kultivait adheres to a strict zero-root standard — `kultivait hook loopback` only produces configuration text for review. Applying changes requires explicit `sudo` commands executed manually by the operator.
- **TLS MITM Caveat**: HTTPS interception requires creating and trusting a local self-signed root certificate (`kultivait-proxy.crt`) to terminate TLS for intercepted domains.
- **Rollback**: Run the commands generated by `kultivait hook loopback --generate-uninstall` to remove hosts entries, delete `/etc/pf.anchors/kultivait`, and remove the certificate from the system keychain.

#### 5. Adoption Trade-Offs: Application-Level vs. Loopback

- **Application-Level Injection (`run`, `hook`, `hook ide`) = The Standard**: Zero-root, zero-MITM overhead, tool-scoped consent, and completely safe for everyday development.
- **Loopback Redirection = Advanced Path**: Global transparency across all processes, but requires `/etc/hosts` and `pf` modifications, TLS certificate generation/trust-store injection, and manual `sudo` execution.

#### 6. Recursion Safety Invariant (`PROXY_ENV_STRIP`)

When intercepted tools dispatch requests to the proxy, cloud-worthy work may be dispatched to upstream CLI backends (e.g. `claude`, `gemini`, `codex`, `opencode`, `agy`). To prevent infinite proxy recursion loops, Kultivait automatically strips `OPENAI_BASE_URL`, `ANTHROPIC_BASE_URL`, and related variables (`PROXY_ENV_STRIP`) prior to spawning any upstream CLI process, ensuring upstream tools always connect directly to native provider endpoints.

#### 7. Rollback & Restoration Matrix

| Adoption Path | Rollback Command | Result |
|---|---|---|
| **Process Wrapper** | Terminate command (`Ctrl+C`) | Child process exits; no residual state |
| **Shell Hook** | `eval "$(kultivait hook --unset)"` | Unsets session environment variables |
| **IDE Patcher** | `kultivait hook ide --restore` | Atomically restores `.kultivait-bak` |
| **Loopback** | `kultivait hook loopback --generate-uninstall` | Reverts `/etc/hosts`, `pf` rules, and trusted cert |

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

Then: `pi --provider kultivait --model auto`. Tool calls pass through on the
OpenAI endpoint — Pi's full agentic loop (read/bash/edit/write) runs through
the proxy, with every turn routed and tallied.

Tool-bearing requests are always served by a local tool-capable tier, even
when classification points at a cloud tier: cloud CLIs run their own agent
loops and can't return client-side tool calls. The response's `kultivait`
metadata reports `tool_fallback: true` when this happens. Anthropic-endpoint
tool support is not yet implemented.

### Direct REST frontier providers & API tier registration

In addition to local runtimes and CLI backends, kultivait supports direct REST API frontier providers (`anthropic`, `openai`, `openrouter`).

#### 1. Configure an API tier

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

Unpriced API tiers load a conservative default ($3.00 in / $15.00 out per MTok) with a warning to ensure accurate ledger accounting.

#### 2. Configure credentials

API keys resolve from three sources with fixed precedence:

> **Funded balance is a separate precondition.** A key can authenticate and pass
> the route menu's presence probe while the account holds no credits — OpenRouter
> then answers every completion with HTTP 402 ("insufficient credits"). **Probe
> success ≠ serve success**: the probe checks auth, not balance. Fund the account
> before expecting dispatches to land (the REST evidence round's #62 finding).

1. **Environment variables** (highest precedence):
   ```bash
   export ANTHROPIC_API_KEY="sk-ant-..."
   export OPENAI_API_KEY="sk-..."
   export OPENROUTER_API_KEY="sk-or-..."
   ```

2. **OS Keychain** (macOS `security`):
   ```bash
   # Add key to Keychain (service: kultivait, account: <provider>)
   security add-generic-password -s kultivait -a anthropic -w "sk-ant-..."
   security add-generic-password -s kultivait -a openai -w "sk-..."
   security add-generic-password -s kultivait -a openrouter -w "sk-or-..."
   ```

3. **Credentials file** (`~/.kultivait/credentials.toml`, `0600` permissions):
   ```toml
   [anthropic]
   api_key = "sk-ant-..."

   [openai]
   api_key = "sk-..."

   [openrouter]
   api_key = "sk-or-..."
   ```

> **Security note**: API keys never live in `config.toml` and are never logged or exposed.

### Prompt caching & cache economics

For pay-per-token API frontier providers, kultivait features proxy-owned **prompt caching** ([ADR 0018](docs/adr/0018-cache-breakpoints.md) & [ADR 0005](docs/adr/0005-cost-model-duality.md) amendment). Multi-turn agent loops automatically benefit from upstream prefix caching without manual prompt engineering.

#### 1. Proxy-Owned Breakpoints & Client Stripping
- **Single Deterministic Policy**: The proxy is the sole cache policy owner. Client-provided `cache_control` headers or properties (e.g. from upstream coding agents) are recursively stripped before translation.
- **Dual-Level Placement**: For prompts exceeding `MIN_CACHE_PREFIX_TOKENS` (1,024 tokens), kultivait injects canonical cache breakpoints at two levels:
  1. **Last Tool Definition** (`tools[-1]`): Anchors the shared tool schemas (level 1).
  2. **System Prompt**: Anchors system instructions (level 2), preventing terminal cache collapse as message history grows across turns.
- **Session Stickiness**: The `conversation fingerprint` (hash of system prompt and first user message) is forwarded as `session_id` on OpenRouter dispatches to ensure routing affinity to warm cache instances.
- **Presence Probe Bypass**: Cache-bearing dispatches skip the presence probe to preserve upstream sticky routing.

#### 2. Configuration & TTL Knobs
Set `cache_ttl` on any `api`-kind tier in `~/.kultivait/config.toml`:

```toml
[[tiers]]
name = "anthropic"
role = "architect"
kind = "api"
model = "claude-3-7-sonnet-20250219"
price_in = 3.0
price_out = 15.0
cache_ttl = "5m"       # "5m" (default, 1.25x write multiplier) or "1h" (2.0x write multiplier)
```

#### 3. Supported Provider Dialects
- **Anthropic**: Explicit block-level `cache_control` (`type = "ephemeral"`, optional `ttl = "1h"`). Cache reads receive a 90% discount (0.1× input price).
- **OpenAI**: Implicit caching on GPT-4o family; explicit write token parsing and 0.1× read multipliers on GPT-5.6+ family.
- **OpenRouter**: Canonical Anthropic markers are translated upstream into native provider shapes; `session_id` guarantees sticky cache worker routing.
- **Llama / Open-Weights**: Cache-blind; entries report zero cached tokens.

#### 4. Cache Telemetry & The Harvest
The harvest tracks cache savings as an **orthogonal third line** (`kept-via-cache`), keeping routing savings (`kept-in-pocket`) and metered cash out completely un-distorted:

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

### Escalations: when the garden isn't enough

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

### Model distillation & shadow cutover

Kultivait's preprocessor evaluates contested prompts to judge whether local models are sufficient or if a prompt should escalate or trigger a trolltoll. The **distillation pipeline** closes the loop: turning harvested routing data (toll choices, escalations, ledger entries) into fine-tuned local models (`qwen3.5:4b` or `llama-3.2-3b-instruct` distillates) to improve local judgment accuracy, reduce unnecessary tolls, and eliminate misroutes.

#### 1. The Distillation Workflow

```
Harvest (~/.kultivait)
  │
  ├── 1. Corpus (distill corpus) ─── Extract real anchors & split held-out eval set
  ├── 2. Generate (distill generate) ─ Dual-teacher synthesis (opencode + claude) + agreement filter
  ├── 3. Train (distill train) ────── mlx-lm QLoRA on Apple Silicon under resource ladder
  ├── 4. Eval (distill eval) ──────── 5-gate validation against permanent held-out set
  ├── 5. Export (distill export) ──── Fuse QLoRA weights & register kv-judge-<base>-g<gen> in Ollama
  ├── 6. Shadow (shadow) ──────────── Zero-latency background shadow pass on contested traffic
  └── 7. Cutover (cutover) ────────── Human-confirmed flip to live preprocessor seat + instant rollback
```

#### 2. Pipeline Subcommands

- **`kultivait distill corpus [--dry-run] [--harvest-dir PATH]`**  
  Assembles training anchor prompts and separates a permanent held-out test roster from the harvest. Tier labels follow a strict truth hierarchy: human toll choices (gold), execution outcomes (silver), and eval records (bronze). Real verdict-bearing cases are permanently held out and never trained on. Use `--dry-run` to preview anchor counts and strata distributions.

- **`kultivait distill generate [--live] [--target-pairs N] [--out-dir PATH] [--harvest-dir PATH] [--judge-cli CLI] [--rewriter-cli CLI]`**  
  Runs the dual-teacher synthetic data generator targeting balanced strata (40% contested, 30% local, 30% frontier):
  - **Judge teacher** (neutral family, e.g. `opencode` / GLM): creates band-targeted variations and performs an independent second-pass tier classification (**agreement filter**).
  - **Rewriter teacher** (`claude` CLI): synthesizes prompt rewrites for each pair.
  - **3-stage filter**: validates pairs with exact hash + embedding deduplication (cosine similarity < 0.92), JSON contract schema validation, and planted-fact recall checks.
  - *Safety constraint*: Requires `--live` to dispatch real subscription CLI teachers (with ledger provenance tagging); refuses to generate from unverified stubs.

- **`kultivait distill train --base <base> --corpus-dir <path> [--iters N] [--epochs N] [--adapter-path PATH] [--resume]`**  
  Trains a QLoRA adapter using `mlx-lm` on supported bases (`qwen3.5:4b`, `llama-3.2-3b-instruct`). Strictly enforces the **resource ladder** on unified memory systems: automatically scales batch size (4→2→1), reduces adapted LoRA layers (16→8→4), enables gradient checkpointing, and aborts rather than causing memory swap.

- **`kultivait distill eval --model <model> --heldout <path> [--incumbent] [--incumbent-model MODEL]`**  
  Evaluates candidate distillates against the permanent held-out dataset through the production generate path (`extract_json` + framing). Validates all 5 acceptance gates:
  1. **Zero dangerous misroutes**: Frontier-worthy requests never misclassified as local.
  2. **100% parse rate**: Valid JSON contract formatting on all outputs.
  3. **Latency budget**: p50 ≤ 8.0s, max ≤ 15.0s.
  4. **Agreement**: ≥ incumbent baseline agreement.
  5. **Band discipline**: Two-sided guard ensuring contested cases populate the band (floor ≥ 50%) without flooding (ceiling ≤ 25%), validated across temperature sweeps.

- **`kultivait distill export --base <base> --adapter-path <path> [--out-root PATH] [--generation N] [--no-quantize]`**  
  Fuses trained QLoRA weights into base weights via `mlx_lm.fuse`, generates an Ollama `Modelfile`, and registers the model in Ollama as `kv-judge-<base>-g<gen>` (quantized to `q4_K_M` by default to ensure serving RAM ≤ 4 GB).

#### 3. Shadow Serving & Cutover Readiness

A gate-passing distillate can be shadowed on live traffic before serving real routing verdicts:

```toml
# ~/.kultivait/config.toml
[distill]
model = "qwen3.5:4b"                     # live preprocessor seat
shadow_model = "kv-judge-llama32-3b-g1"  # candidate distillate
shadow_mode = "on"                       # "off" | "on"
shadow_sample_rate = 1.0                 # 100% of contested requests
```

- **Zero latency impact**: The shadow pass runs asynchronously as a fire-and-forget background task *after* the live response has been sent to the client.
- **Exception isolation**: Shadow evaluation failures or crashes are caught and recorded as anomalies, never disrupting live requests.
- **Isolated shadow log**: Results land in `~/.kultivait/shadow.jsonl` outside the main ledger to avoid polluting harvest cost metrics or toll analytics.

Check shadow agreement and cutover readiness anytime:

```bash
kultivait shadow
```

Outputs live statistics and evaluates ADR 0017 cutover readiness:
- **Sample volume**: `n >= 30` shadowed contested requests.
- **Agreement**: `agreement >= 90%` with the incumbent model.
- **Zero anomalies**: `0 anomalies` (0 parse errors, 0 dangerous local verdicts on escalations).

#### 4. Human Cutover & Instant Rollback

Automated cutovers are deliberately disallowed. Model deployment is always a human decision:

```bash
kultivait cutover --model kv-judge-llama32-3b-g1
```

1. **Readiness check**: Checks `~/.kultivait/shadow.jsonl` and displays agreement/anomaly stats (or prints a warning if criteria are not yet met).
2. **Explicit confirmation**: Prompts `[y/N]` before modifying any configuration (pass `--yes` to skip in scripted flows).
3. **Atomic config update**: Rewrites `[distill] model = "<distillate>"` in `~/.kultivait/config.toml`.
4. **Instant rollback guarantee**: `DistillSeat` in the proxy server resolves the `[distill] model` configuration dynamically per request. No server restarts are required.

To roll back immediately, run the command printed during cutover:

```bash
kultivait cutover --model qwen3.5:4b --config ~/.kultivait/config.toml
```

The rollback takes effect on the very next incoming request.

## Requirements

- a local model runtime — either:
  - [ollama](https://ollama.com) with at least one general model pulled, or
  - [llama.cpp](https://github.com/ggml-org/llama.cpp)'s `llama-server` in
    router mode (see below)
  — `kultivait init` detects whichever is running and adapts to whatever
  models you have
- an embedding model (`ollama pull nomic-embed-text`, 274 MB — the installer
  handles this; for llama.cpp, a nomic-embed GGUF)
- optional: `claude` / `agy` / `gemini` CLIs on PATH for cloud tiers

### Zero to local: `kultivait init` on a Mac

On an Apple Silicon Mac with at least 24GB of unified memory and no local
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
the reverse — llama-server stops first, ollama starts, and the chooser
re-surveys in place. A runtime that refuses to stop aborts the pivot
rather than risk both serving at once.

Skipping (Esc) is a first-class outcome — it still writes a virtual-tier
config plus an onboarding marker (`~/.kultivait/onboarding.json`), and
`kultivait init` re-runs safely: finished steps are skipped and
size-checked downloads resume. Opt out with `kultivait init --no-setup`;
the screen is also skipped when stdin is not a TTY or when
`KULTIVAIT_RUNTIME` is set (a forced runtime means you already have a
setup in mind).

Each GGUF is verified against a pinned upstream SHA256 (Hugging Face's
LFS oid) before it's promoted from its `.part` file, so mutable
`resolve/main` refs can't slip corrupt or swapped bytes past you — a
mismatch is discarded rather than Range-resumed.

### Using with llama.cpp instead of ollama

Run `llama-server` in **router mode** — launched without `-m`, it lists your
GGUF models at `/v1/models` and loads whichever one a request names. One
wrinkle: the router won't serve `/v1/embeddings` unless the embedding model is
marked as such in a preset file:

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

(`--jinja` enables tool calls.) `init` surveys the router's model list, sizes
each GGUF from disk, and picks tiers exactly as it does for ollama —
downloadable suggestions the router advertises but you haven't pulled are
ignored. If both runtimes are running, ollama wins; force a choice with
`KULTIVAIT_RUNTIME=llamacpp`. Non-default ports and model dirs:
`KULTIVAIT_LLAMACPP_URL`, `KULTIVAIT_LLAMACPP_MODELS_DIR`.

Prefer a dedicated embedding server instead of the preset? Run
`llama-server -m nomic-embed-text.gguf --embedding --port 8081` and set
`embed_base_url = "http://localhost:8081"` in `~/.kultivait/config.toml`.
Empty `embed_base_url` means "same server as chat".

Context size for llama.cpp is set at server launch (`--ctx-size`), not per
request — kultivait's `num_ctx` and truncation detection apply to ollama only.

## Development

```bash
uv run pytest
```

The landing page lives in `landing/index.html`.

## Roadmap

- Distillation-quality eval harness: automated planted-fact recall scoring
  across transcripts, to measure and improve the ~85% retention rate
- Ambient gates via agent-framework hooks (e.g. Claude Code hooks), so
  pruning happens at phase boundaries without manual invocation
- Streaming responses
- Watt-hour estimation in the ledger
- Learned centroids from your own routing history
