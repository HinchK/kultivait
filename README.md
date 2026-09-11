# kultivait

[![CI](https://github.com/Standard-Pentest/kultivait/actions/workflows/ci.yml/badge.svg)](https://github.com/Standard-Pentest/kultivait/actions/workflows/ci.yml)

kultivait is an LLM routing proxy. A local embedding model weighs every
prompt and sends it to the cheapest model that can carry it: your own garden
of local models first, the cloud only when the work earns its cost. Every
dispatch is tallied in a savings ledger.

**The greenest token is the one you never send.**

- Routing runs on your machine in milliseconds. No cloud call decides
  whether to make a cloud call.
- It speaks both OpenAI (`/v1/chat/completions`) and Anthropic
  (`/v1/messages`), streaming and non-streaming, tools included.
- Every dispatch is recorded to `~/.kultivait/ledger.jsonl`, with savings
  computed against frontier-model pricing.
- Nothing phones home. Classification, serving, and the ledger stay on your
  machine.

## Requirements

- macOS. The full zero-to-local bootstrap needs Apple Silicon with at least
  24 GB of unified memory; less works with a smaller garden.
- A local model runtime: [ollama](https://ollama.com) with at least one
  general model pulled, or [llama.cpp](https://github.com/ggml-org/llama.cpp)'s
  `llama-server` in router mode (see
  [Using llama.cpp](docs/guides/setup.md#using-llamacpp-instead-of-ollama)).
  `kultivait init` detects whichever is running and adapts to the models you
  have.
- An embedding model, which `kultivait init` fetches for you:
  `nomic-embed-text` through ollama is 274 MB, and the llama.cpp path
  downloads a 146 MB Q8_0 GGUF instead.
- Python 3.12+, which [uv](https://docs.astral.sh/uv/) manages for you if
  you install by hand.
- Optional: the `claude`, `agy`, or `gemini` CLIs on your PATH, for cloud
  tiers.

## Quickstart

```bash
curl -fsSL https://kultivait.ai/install.sh | sh
```

or, by hand:

```bash
uv tool install --from git+https://github.com/Standard-Pentest/kultivait kultivait
```

```bash
kultivait init      # setup screen: survey, choose a garden, download, serve
kultivait serve     # proxy on http://localhost:4114
kultivait harvest   # watch the savings grow
```

On first run, `init` opens a setup screen: a preparation checklist, then a
chooser of gardens this machine can grow. If ollama is installed but nothing
is serving, the screen asks which runtime to use before starting anything;
kultivait never starts ollama on its own. Your smallest capable model
becomes the simple tier and your largest the reasoning tier, and any
`claude`, `agy`, or `gemini` CLI becomes a cloud tier.

Cloud CLIs are optional, and local-only mode is fully supported. Cloud-worthy
prompts are still recognized, served by your best local model, and
archived, and `kultivait escalations --brief` turns one into a paste-ready
brief you can take to any frontier model yourself.

Pressing Esc skips the screen and still writes the virtual-tier config.
Decisions live in `~/.kultivait/config.toml`, which you can edit freely. Run
`kultivait init` again anytime, or `kultivait init --setup` to reopen the
screen on a completed setup. The [setup guide](docs/guides/setup.md) covers
the bootstrap, the runtimes, and downloads in detail.

## How it works

1. Your tools point at kultivait's OpenAI- or Anthropic-compatible endpoint.
2. `nomic-embed-text` embeds the prompt locally, in milliseconds, and
   classifies it by cosine similarity to seed-prompt centroids.
3. Trivial work goes to your simple tier, local reasoning to your reasoning
   tier, doc-grounded checks to a docs CLI such as `agy`, and cross-file
   architecture to an architect CLI such as `claude`. When the
   classification margin is thin, the prompt goes one tier up:
   over-provisioning wastes cents, under-provisioning wastes an afternoon.
4. Every decision lands in `~/.kultivait/ledger.jsonl` with its savings
   against frontier pricing.

When a routing decision is contested, kultivait can fire a *trolltoll*: it
holds the request briefly while a tollbooth offers you a choice of route.
The [glossary](CONTEXT.md) defines these and the project's other terms.

## Evidence

Every claim here reproduces from the repo:

```bash
uv run experiments/routing_trust.py   # → accuracy: 24/24, dangerous misroutes: 0/24
```

The router classifies all 24 held-out prompts in
`experiments/routing_trust.py` correctly, with zero dangerous misroutes
(cloud-worthy work sent to a weaker model).

The distiller model was picked with a planted-fact recall eval
(`experiments/distill_eval/`: 5 models × 2 prompts × 8 transcripts,
including multi-turn chat, tool loops, and phase-gate handoffs; see
[ADR 0022](docs/adr/0022-planted-fact-eval.md)). The table below is
generated from the checked-in results file,
`experiments/distill_eval/results.json`; regenerate it with
`uv run python experiments/distill_eval/run.py --emit-table`.

| model | mean recall | tokens kept | avg time | gen-2 survival |
|---|---|---|---|---|
| **gemma4:latest** | **94%** | 68% | 31s | 92% |
| phi4:14b | 92% | 74% | 25s | 90% |
| qwen3:14b | 87% | 64% | 22s | 87% |
| qwen2.5:14b | 83% | 54% | 19s | 78% |
| llama3.1:8b | 77% | 57% | 10s | 69% |

There is no built-in distiller default: `kultivait init` picks your
machine's largest local model. At a phase gate, recall matters more than
speed, because a dropped constraint is catastrophic and a slow gate costs a
coffee sip. If you'd rather have the faster runner-up, which also
compresses harder, set `KULTIVAIT_DISTILL_MODEL=qwen3:14b`. Gen-2 survival
measures how well facts hold up when a brief is distilled a second time. On
this corpus the hardened "never omit numbers" prompt (v2 in the results
file) beats the base prompt for four of the five models; the per-prompt
splits are in `results.json`.

## The harvest

`kultivait harvest` reports routing savings, metered cash, and cache
savings as separate lines:

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

`kultivait dashboard` shows the same data live in your browser.

## Commands

```bash
kultivait serve                    # run the routing proxy
kultivait choose                   # answer pending tolls out-of-band
kultivait run -- <command>         # transparent child process proxy wrapper
kultivait hook [shell|ide|loopback]# zero-config adoption & tool integration
kultivait dashboard                # open the live web dashboard
kultivait route "why does this test deadlock?"    # dry-run a classification
kultivait prune --from explore --to plan transcript.txt   # phase-gate brief
kultivait gates install --claude           # ambient gates: prune at phase boundaries automatically
kultivait escalations [--brief]    # cloud-worthy prompts served locally
kultivait harvest [--json]         # cumulative savings (+ est. local Wh once local dispatches exist)
kultivait centroids [learn|status|cutover]        # learned routing centroids from your history (human-gated cutover)
kultivait eval [--target <t>] [--json]            # direct-to-backend capability eval (alias: benchmark)
kultivait distill [corpus|generate|train|eval|export]   # distillation pipeline
kultivait shadow [--log <path>]                   # shadow log summary & cutover readiness
kultivait cutover --model <distillate> [--yes]    # flip live preprocessor + print rollback
```

Run `kultivait <command> --help` for every option.

## Guides

- [Setup](docs/guides/setup.md): the zero-to-local bootstrap on a Mac, how
  ollama and llama.cpp take turns, and running on llama.cpp.
- [Connecting your tools](docs/guides/connecting.md): both endpoints, the Pi
  coding agent, and the zero-config adoption paths, from wrapping one
  command to OS-level loopback.
- [API providers and prompt caching](docs/guides/api-providers.md): direct
  Anthropic, OpenAI, and OpenRouter tiers, their credentials, and cache
  economics.
- [Phase gates and escalations](docs/guides/gates-and-escalations.md):
  `prune`, ambient gates, the compost pile, and handoff briefs.
- [Distillation and shadow cutover](docs/guides/distillation.md): training a
  local judge from your harvest and promoting it safely.

The [documentation index](docs/README.md) lists everything else: design
decisions (ADRs), design specs, runbooks, and research notes.

## Development

```bash
uv sync
uv run pytest
```

The landing page lives in `landing/index.html`. This repo is developed by a
coordinated multi-agent herd (looper, architect, docs, and GitHub workers),
with tickets and milestone maps on the GitHub issue tracker. See
[CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.

## What's shipped

Release notes are in [CHANGELOG.md](CHANGELOG.md). v0.2.0 added ambient
phase-gates, estimated watt-hours in the ledger, learned routing centroids
(shadow-only until a human cuts over), and the planted-fact distillation
eval behind the table above.

## Roadmap

The next milestone hasn't been chosen yet. Planned work will be tracked as
[issues on GitHub](https://github.com/Standard-Pentest/kultivait/issues).

<!-- Stub: list the next milestones here once they're chartered. -->

## License

[MIT](LICENSE)
