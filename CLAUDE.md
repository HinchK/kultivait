# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
uv sync                                              # install deps (incl. dev group)
uv run pytest                                        # full test suite
uv run pytest tests/test_router.py                   # one file
uv run pytest tests/test_router.py::test_name -v     # one test
uv run kultivait serve                                # run the proxy locally (:4114)
uv run kultivait route "some prompt"                  # dry-run a classification, no request sent
uv run python experiments/routing_trust.py            # re-validate router accuracy against held-out prompts
uv run python experiments/distill_eval/run.py [model...]  # re-score distiller model candidates by fact recall
```

There is no configured linter, formatter, or type checker in this repo (no ruff/black/mypy config) — don't assume one runs in CI.

Requires a local `ollama` (with a model pulled) or `llama-server` in router mode reachable at their default ports for anything that embeds or generates (`serve`, `route`, `init`, `prune`, `escalations --brief`); pure unit tests (router, config, ledger, escalations, gates logic) don't need either. On a bare Apple Silicon Mac (≥24GB), `kultivait init` can bootstrap llama.cpp itself — hardware sizing lives in `src/kultivait/hardware.py`, the confirmed install/download/launch steps in `src/kultivait/bootstrap.py`.

## Architecture

Request flow through `src/kultivait/`, in call order:

1. **`config.py`** — `detect()` is a pure function `(local models, available CLIs, sizes) -> Config`; this is what makes "any stranger's laptop" a unit-test fixture (see `tests/test_config.py`). It sorts local models by parameter count into `simple`/`reasoning` tiers and maps installed CLIs (`claude`→architect, `agy`/`gemini`→docs) via `KNOWN_CLIS`. A CLI role with nothing installed becomes a **virtual tier** (`frontier:<role>`) — classified but never served; `cli.py:get_config()` loads `~/.kultivait/config.toml` if present (written by `kultivait init`), otherwise re-detects live. `KULTIVAIT_RUNTIME`/`KULTIVAIT_DISTILL_MODEL`/`KULTIVAIT_NUM_CTX` env vars override the loaded config.
2. **`seeds.py` + `router.py`** — `ROLE_SEEDS` are the fixed exemplar prompts per role (validated in `experiments/routing_trust.py`, 24/24 held-out). `cli.py:build_router()` embeds the seeds once per tier into centroids; `Router.classify()` embeds the incoming prompt and picks the nearest centroid by cosine similarity. If the winning margin is thinner than `escalation_margin` (default 0.02), routing bumps one tier up `capability_order` rather than risk under-provisioning — the classifier's uncertainty itself is a routing signal.
3. **`backends.py`** — one `Backend` protocol (`complete`/`stream`), three implementations: `OllamaBackend`, `LlamaCppBackend` (both local/free), `CLIBackend` (wraps a print-mode cloud CLI like `claude -p`). `OllamaBackend` explicitly sets `options.num_ctx` because ollama silently truncates over-long prompts to its default context and keeps the *tail*, not the head — `is_truncated()` detects a `prompt_eval_count` pinned at the ceiling. llama.cpp's context is fixed at server launch instead, so its `truncated` is always `False`. `CLIBackend` has no real token counts (CLIs don't report usage), so it estimates via chars/4 against configured per-CLI pricing (`CLI_PRICING`).
4. **`server.py`** — FastAPI app exposing `/v1/chat/completions` (OpenAI-compatible), `/v1/messages` (Anthropic-compatible, no tool support yet), `/gate`, and `/harvest`. `_resolve_tier()` is the fallback rule: a tools-bearing request is **always** served by a local tool-capable tier even when classification points at a cloud tier, because cloud CLIs run their own agent loop and can't return client-side tool calls — the response's `kultivait.fallback_reason` reports this (`tools_unsupported` vs `no_backend` for virtual tiers). Every fallback also triggers an escalation save (see below).
5. **`ledger.py`** — append-only JSONL at `~/.kultivait/ledger.jsonl`; every request is recorded with cost vs. a frontier-pricing baseline, so `kultivait harvest` can report cumulative savings. `record()` stores arbitrary `**extra` fields verbatim — routing metadata rides along with each entry rather than needing a schema migration.
6. **`escalations.py`** — when a request is force-downgraded to local (tool_fallback) or otherwise, the full conversation is archived to `~/.kultivait/escalations/` *synchronously on the request path* but the paste-ready brief is only distilled lazily via `kultivait escalations --brief`, so the interactive request never pays the distillation cost.
7. **`gates.py`** — `kultivait prune` / `POST /gate`: distills a transcript into a FINDINGS/DECISIONS/CONSTRAINTS/OPEN QUESTIONS brief using the local `distill_model`. The full transcript is *always* composted to `~/.kultivait/compost/` first — distillation is lossy by design, and compost is the recovery path if a brief drops something load-bearing. Same compost-then-distill shape is reused by escalations, with a different prompt template (`HANDOFF_PROMPT`) and section set (TASK/CONTEXT/PROGRESS/NEEDED).

`cli.py` is the composition root: it wires config → router → backends → ledger/gate/escalations for `serve`, and reuses `get_config()`/`build_router()`/`build_gate()` for the other subcommands so `route`/`prune`/`escalations` don't need a running server.

### Cross-cutting conventions worth knowing before editing

- Config detection, routing, and ledger/escalation logic are all pure-function-ish and tested in isolation (`tests/test_config.py`, `test_router.py`, `test_ledger.py`, `test_escalations.py`); network/subprocess calls are pushed to the edges (`cli.py`, `backends.py`) and mocked or skipped in tests — check `tests/test_backends.py` and `test_llamacpp_survey.py` for the pattern before adding new network calls.
- Runtime auto-detection prefers ollama over llama.cpp when both are reachable (`cli.py:_detect_runtime`) — force llama.cpp with `KULTIVAIT_RUNTIME=llamacpp`.
- Model *tiers* are named by role capability, not hardcoded to specific model names — `capability_order()` is derived from whatever `detect()` found on the current machine, so don't assume `llama3.1:8b`/`qwen3:14b` are literal constants anywhere outside tests/docs.
- Ethos ordering when making product/behavior tradeoffs, per README/HANDOFF: **reduce → right-size → localize** — prefer not sending a prompt at all, then the cheapest tier that can carry it, then local over cloud.
