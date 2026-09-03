# Public-claims verification — README.md & landing/index.html vs the code

Research ticket: [#136](https://github.com/Standard-Pentest/kultivait/issues/136) · parent map: [#132](https://github.com/Standard-Pentest/kultivait/issues/132)
Date: 2026-09-03 · Branch: `research/verify-public-claims` · Method: full read of README.md (592 ln), landing/index.html (907 ln), landing/install.sh, pyproject.toml; read of all ground-truth modules in `src/kultivait/`; live re-run of `experiments/routing_trust.py`; recomputation of `experiments/distill_eval/results.json`; live HTTP checks against kultivait.ai and github.com.

**Counts: 46 TRUE · 13 FALSE-or-STALE · 7 UNVERIFIABLE.**

Live verifications performed read-only on this machine (2026-09-03):
- `uv run experiments/routing_trust.py` → `accuracy: 24/24 (100%)`, `dangerous misroutes: 0/24`
- `ollama list` → `nomic-embed-text:latest 274.3 MB`
- embed round-trip (5 warm calls) → 14–20 ms
- `https://kultivait.ai/install.sh` → 200 (serves a **stale, different** script); `/start.md` → 404 (apex and www)
- `https://github.com/Standard-Pentest/kultivaite` → 301 redirect to `…/kultivait`; `git ls-remote` via the typo URL succeeds

---

## (a) VERIFIED-FACTS REGISTER — claim → where → ground truth → TRUE

### Core routing story

| # | Claim | Where | Ground truth |
|---|---|---|---|
| 1 | Intercept/weigh/route/harvest architecture; OpenAI-compatible endpoint | README:9-20, 97 | `server.py:619` `/v1/chat/completions`; `router.py`; `ledger.py` |
| 2 | Local embedding classifies by cosine similarity to seed-prompt centroids; no cloud call decides cloud routing | README:12-14 | `router.py:28-42`; `cli.py:226-233` (`build_router`); `seeds.py` |
| 3 | Thin classification margins escalate one tier up ("over-provisioning wastes cents…") | README:17-18 | `router.py:36-41` — comment is verbatim in code |
| 4 | Every decision recorded to `~/.kultivait/ledger.jsonl` with savings vs frontier baseline pricing | README:19-20 | `cli.py:53`; `ledger.py:9` (baseline $3/$15 per MTok), `:131`, `:183` |
| 5 | **`experiments/routing_trust.py` classified 24/24 held-out prompts correctly, zero dangerous misroutes** | README:22-24 | Script holds 4 tiers × 6 held-out = 24 (`routing_trust.py:21-94`); **re-run live 2026-09-03: 24/24, 0 dangerous** |
| 6 | Proxy on `http://localhost:4114` | README:36, 97, 105 | `config.py:134` (`port: int = 4114`); `cli.py:635-637` |
| 7 | Roles: trivial→simple tier, local reasoning→reasoning tier, docs→`agy`, architecture→`claude` | README:15-16 | `config.py:16,27-33` (`KNOWN_CLIS`: claude/codex/opencode→architect, agy/gemini→docs) |
| 8 | `nomic-embed-text` is local and runs in milliseconds | README:12 | measured 14–20 ms warm round-trip on this machine |
| 9 | `nomic-embed-text` **274 MB** via ollama | README:476-477 | local ollama reports `nomic-embed-text:latest 274.3 MB`; `cli.py:202` hint says 274 MB. (llama.cpp bootstrap path downloads a 146 MB Q8_0 GGUF — see nuance in (b)#12) |

### CLI surface (every subcommand README shows exists)

| # | Claim | Where | Ground truth |
|---|---|---|---|
| 10 | `init` (setup screen, `--setup`, `--no-setup`), `serve`, `harvest` | README:35-37, 48-51 | `cli.py:1328-1341`, `cmd_init:366-380` |
| 11 | `choose` — answer pending tolls out-of-band | README:57 | `cli.py:1485-1486`, `cmd_choose:528` |
| 12 | `run -- <command>` — injects `OPENAI_BASE_URL`/`ANTHROPIC_BASE_URL`, forwards POSIX signals, preserves exit codes, zero persistent config | README:58, 116-127 | `cmd_run:1017-1060` (SIGINT/SIGTERM forwarding, `SystemExit(rc)`) |
| 13 | `hook [shell\|ide\|loopback]`; 4 shells (sh/bash/zsh/fish); `--check`, `--unset` | README:59, 129-147 | `cli.py:1425-1449`; `cmd_hook:975-1014` |
| 14 | `hook ide`: Cursor/VS Code/Windsurf, atomic `.kultivait-bak` backups, `--dry-run`, `--restore` | README:149-165 | `hook/ide.py:40` (`BACKUP_SUFFIX = ".kultivait-bak"`), `:95-112` |
| 15 | `hook loopback`: `--generate-hosts/-pf/-cert/-uninstall`; review-only zero-root; routes api.anthropic.com & api.openai.com; `/etc/pf.anchors/kultivait`; `kultivait-proxy.crt` | README:167-187 | `hook/loopback.py:15-16,38,55-66`; `cmd_hook_loopback:904-933` prints text only |
| 16 | `dashboard` — real-time web telemetry UI | README:60 | `cmd_dashboard:1063-1105`; `/api/stream` SSE `server.py:930-958`; `/dashboard` mount `server.py:960-963` |
| 17 | `route "prompt"` — dry-run a classification | README:61 | `cmd_route:640-644` |
| 18 | `prune --from X --to Y file` — phase-gate brief | README:62 | `cli.py:1347-1351`, `cmd_prune:647` |
| 19 | `escalations [--brief]` — list / distill handoff | README:63 | `cli.py:1353-1358`, `cmd_escalations:661-690` |
| 20 | `harvest [--json]` | README:64 | `cli.py:1360-1362`, `cmd_harvest:777` |
| 21 | `distill corpus/generate/train/eval/export`, `shadow [--log]`, `cutover --model [--yes]` | README:65-72 | `cli.py:1364-1483` — all present with the flags README shows |
| 22 | `POST /gate` performs the same prune | README:78 | `server.py:879-901` |

### Endpoints, tools, telemetry-free routing metadata

| # | Claim | Where | Ground truth |
|---|---|---|---|
| 23 | Both endpoints support streaming (SSE) | README:98 | `server.py:632-679` (OpenAI chunks), `:732-828` (Anthropic events) |
| 24 | Anthropic-compatible `/v1/messages`, streaming + non-streaming, content blocks, `system` handled | README:100-106 | `server.py:717-877` |
| 25 | Cloud CLI tiers stream as one final chunk; local tiers token-by-token | README:108-110 | `backends.py:530-545` (CLIBackend.stream yields whole text); `OllamaBackend.stream:170-209` yields deltas |
| 26 | Tool-bearing requests always served by a local tool-capable tier (cloud CLIs run their own loops) | README:224-227 | `server.py:_resolve_tier:260-275`; `backends.py:434` (`supports_tools = False`) |
| 27 | Pi provider config with `model: auto` works; tool calls pass through the OpenAI endpoint | README:207-222 | `model` field ignored by proxy; tools plumbed end-to-end `server.py:620-715`; `OllamaBackend.supports_tools=True` |
| 28 | PROXY_ENV_STRIP recursion invariant: proxy env vars stripped before spawning upstream CLIs | README:194-196 | `backends.py:21-27`, applied at `:479` |
| 29 | `kultivait` metadata block in responses | README:226 | `server.py:481-498,714` (key names: see (b)#3) |

### REST API tiers, credentials, caching

| # | Claim | Where | Ground truth |
|---|---|---|---|
| 30 | `api`-kind tiers for anthropic/openai/openrouter; README's example models & prices | README:230-264 | `config.py:81-103` `PROVIDER_DEFAULTS` matches (claude-3-7-sonnet-20250219 3/15; gpt-4o 2.5/10; anthropic/claude-3.7-sonnet 3/15); `cli.py:268-292` |
| 31 | Unpriced API tiers default $3/$15 with warning | README:264 | `config.py:43-44,282-290` (`UserWarning`) |
| 32 | Credentials: env > macOS keychain (service `kultivait`) > `~/.kultivait/credentials.toml` 0600; never in config.toml, never logged | README:266-303 | `credentials.py:67-91` (priority), `:94-126` (`os.chmod 0o600`), `:129-135` (masking) |
| 33 | Prompt caching: client `cache_control` recursively stripped; breakpoints at `tools[-1]` + system for prompts > `MIN_CACHE_PREFIX_TOKENS` (1,024); `5m`→1.25× / `1h`→2.0× writes; conversation fingerprint forwarded as OpenRouter `session_id`; Anthropic reads 0.1×; OpenAI gpt-4o implicit / gpt-5.x 0.1× reads | README:305-335 | `api_backends.py:321` (1024), `:348-354` (strip), `:363-408` (placement, multipliers), `:411-419` (`0.1 if "gpt-5" in m else 0.5`); `server.py:69-80` (fingerprint); ledger prices reads at 0.9 discount `ledger.py:75` |
| 34 | Harvest tracks cache savings as an orthogonal third line (`kept-via-cache`), hit rate, reads/write, ttl cohorts — README's sample output block is the real format | README:337-357 | `cli.py:format_harvest:713-728`; `ledger.py:_cache_section:57-91` — line-for-line identical layout |
| 35 | Notional vs metered cash: CLI tiers notional-only (subscription), API tiers metered | README sample + ADR refs | `server.py:_record:199-213` (exactly this three-way split) |

### Escalations & local-only mode

| # | Claim | Where | Ground truth |
|---|---|---|---|
| 36 | Local-only first-class: virtual cloud tiers classified-never-served; cloud-worthy prompts recognized, served by best local model, archived | README:43-47 | `config.py:221-223` (virtual tiers); `cli.py:293-294`; `server.py:260-275` (fallback to most capable serving tier) |
| 37 | Every tool-fallback archived as an escalation, off the request path | README:359-362 | `server.py:457-458` |
| 38 | `escalations --brief` → TASK/CONTEXT/PROGRESS/NEEED brief distilled by local model, names recommended target ("take this to Claude") | README:366-373 | `escalations.py:34-50` (`HANDOFF_PROMPT`), `:18-32` (`recommended_target`); `cmd_escalations:684` |

### Distillation pipeline

| # | Claim | Where | Ground truth |
|---|---|---|---|
| 39 | Corpus truth hierarchy gold/silver/bronze; verdict-bearing cases permanently held out, never trained on | README:395-396 | `corpus.py:1-13`, `:80-141` (`split_heldout`) |
| 40 | Generate: balanced strata 40% contested / 30% local / 30% frontier; exact-hash + cosine>0.92 dedup; JSON contract validation; planted-fact recall; refuses without `--live` | README:398-403 | `generator.py:35` (`DEDUP_COSINE = 0.92`), `:233` (default strata 0.4/0.3/0.3), `:288-311`; `cli.py:801-803` (refusal) |
| 41 | Train: mlx-lm QLoRA on `qwen3.5:4b` / `llama-3.2-3b-instruct`; resource ladder batch 4→2→1, layers 16→8→4, gradient checkpointing, aborts rather than swap | README:405-406 | `trainer.py:26-54` (`BASES`, ladder rungs exactly 4/16 → 1/4, abort "never swap") |
| 42 | Eval 5 gates: zero dangerous misroutes; 100% parse; p50 ≤ 8.0s / max ≤ 15.0s; agreement ≥ incumbent; band floor ≥ 50% / ceiling ≤ 25% across temperature sweeps | README:408-414 | `eval.py:30-33` (`BAND_FLOOR=0.5`, `BAND_CEILING=0.25`, `LATENCY_P50_S=8.0`, `LATENCY_MAX_S=15.0`), `:78-87` (sweep) |
| 43 | Export: `mlx_lm.fuse` + Modelfile + Ollama registration as `kv-judge-<base>-g<gen>`, default `q4_K_M`, ≤ 4 GB resident | README:416-417 | `export.py:7-8,28,117`; live ollama has `kv-judge-llama32-3b-g0..g3` |
| 44 | Shadow: async post-response fire-and-forget, exception-isolated, `~/.kultivait/shadow.jsonl` outside ledger; readiness = n ≥ 30, agreement ≥ 90%, zero anomalies; cutover human-only with `[y/N]`/`--yes`, instant rollback via per-call `DistillSeat` | README:419-466 | `shadow.py:9-10,26-27` (`CUTOVER_MIN_N=30`, `CUTOVER_AGREEMENT=0.90`); `server.py:500-521`; `cmd_cutover:863-901`; `config.py:117-125` |

### Setup/init flow, runtimes, installer plumbing

| # | Claim | Where | Ground truth |
|---|---|---|---|
| 45 | Apple Silicon ≥ 24 GB whole-bootstrap offer; prep checklist; garden chooser tuned to RAM (Qwen3 family ladder); sudo confirm precedes password; Esc-cancel leaves resumable `.part`; `r Retry`/`c Choose another`; SHA256 pinned to HF LFS oid, mismatch discarded; ollama/llama.cpp never both up — stops verify port quiet, pivot aborts on refusal; skipping writes virtual-tier config + `~/.kultivait/onboarding.json`; re-run skips finished steps | README:480-515 | `hardware.py:59` (`MIN_RAM_GB = 24.0`), `:115-120`, `:73-75`; `bootstrap.py:73-85` (discard on mismatch), `:103` (size-checked resume), `:242-255`; `runtimes.py:45-110` (`brew services start ollama`, `_poll_down`); `setup_screen.py:384-449`; `setup_state.py:349,356` (`r Retry · c Choose another`); `onboarding.py` |
| 46 | llama.cpp router mode: surveys `/v1/models`, sizes GGUFs from disk, ignores undownloaded suggestions, presets `embedding = 1`, `--jinja` for tools, ollama wins if both up, `KULTIVAIT_RUNTIME`/`KULTIVAIT_LLAMACPP_URL`/`KULTIVAIT_LLAMACPP_MODELS_DIR` overrides, `embed_base_url` dedicated server, ctx fixed at launch / `num_ctx` ollama-only; dev workflow `uv run pytest`, landing in `landing/index.html`, Herdr wizard + briefs | README:517-582 | `cli.py:50,114-139,158-165`; `backends.py:229-238`; `config.py:139,148-149`; `hardware.py:179` (`--jinja`); `scripts/herdr-kultivait-session.sh` + `scripts/herdr-briefs/` exist |
| — | `uv tool install --from git+https://github.com/Standard-Pentest/kultivaite kultivait` **mechanically works**: `pyproject.toml:30-31` `[project.scripts] kultivait = "kultivait.cli:main"`; `uv_build` backend (`pyproject.toml:20-22`) with `src/kultivait/` layout; typo URL 301-redirects and `git ls-remote` succeeds | README:32 | verified live — but see (b)#1 |

---

## (b) FALSE-OR-STALE LIST

1. **Install git URL typo `kultivaite`** — README:32 and landing/install.sh:17. The repo is `Standard-Pentest/kultivait`; the typo'd URL works *only* via GitHub's rename 301 redirect (verified: `curl → 301`, `git ls-remote` succeeds through it). If that redirect is ever reclaimed/removed, every install path 404s. Cosmetic today, latent breaker.
2. **Landing starter-prompt URL is dead** — landing/index.html:540,545,829,834: "Read https://www.kultivait.ai/start.md …" is pasted by both "Copy the starter prompt" CTAs. Live check: **404** on `www.kultivait.ai/start.md` *and* apex `/start.md`. The repo has `landing/start.md` but it is not deployed. The landing's primary conversion path is broken.
3. **README:226-227 metadata key `tool_fallback: true`** — the actual `kultivait` metadata field is `fallback_reason` (`server.py:481-498`); `ledger.py:132-133` explicitly calls `tool_fallback` "the pre-config legacy field". Stale field name in public docs.
4. **README:228 "Anthropic-endpoint tool support is not yet implemented"** — FALSE: `/v1/messages` accepts `tools` and emits `tool_use` content blocks in both streaming and non-streaming paths (`server.py:754-799`, `:842-861`).
5. **README:508-510 "the screen is also skipped … when `KULTIVAIT_RUNTIME` is set"** — FALSE: `cmd_init` (`cli.py:366-380`) checks only `--no-setup`, TTY, and first-run. `KULTIVAIT_RUNTIME` merely suppresses download offerings *inside* the screen (`setup_screen.py:540`). The screen still appears.
6. **Distiller eval table (README:83-95) is not reproducible from the checked-in artifact** — `experiments/distill_eval/results.json` (30 records = 5 models × 2 prompts × 3 transcripts ✓). Recomputed: recall matches for gemma4 (100%) and qwen3:14b (96.3%) but **not** phi4:14b (README 92.6% vs artifact 89.6%), qwen2.5:14b (90.2% vs 87.2%), llama3.1:8b (86.5% vs 86.9%); tokens-kept mismatch for gemma4 (61% vs 69%), qwen3:14b (44% vs 55%), llama3.1:8b (44% vs 54%); avg time mismatch for qwen3:14b (15s vs 18.4s), gemma4 (29s vs 27.9s). Either the table came from an earlier run or was hand-rounded; as shipped, a stranger recomputing the artifact will get different numbers.
7. **README:85 "`gemma4:latest` (default)"** — there is no code default. `Config.distill_model` defaults to None and `detect()` picks the machine's largest local model (`config.py:132,229`); "gemma4:latest" is the dev machine's pick. Misleading as a product default.
8. **README:400 judge teacher "neutral family, e.g. `opencode` / GLM … creates band-targeted variations"** — stale vs the ADR 0016 amendment: the CLI default pins `--judge-model x-ai/grok-4.6` via OpenRouter (`cli.py:1385-1387`; `generator.py:356-365` — opencode is only the no-`judge_model` fallback), and variations are drafted by the local `vary_model` (`qwen3:14b` default, `cli.py:1388-1389`), not the judge.
9. **README:590 roadmap item "Streaming responses"** — contradicts README:98 and the code (both endpoints stream SSE, `server.py:632-828`). Stale roadmap line.
10. **Landing watt-hour claims** — index.html:607 ("est. avoided 31 Wh" tally), :610-811 ("~0.9 kWh … est. inference avoided"), and the JS at :897-903 that *fabricates* a monotonically growing $/Wh counter. No watt-hour estimation exists anywhere in the ledger (README:591 itself lists it as roadmap). Implies a feature that does not exist.
11. **kultivait.ai serves a stale, divergent `install.sh`** — live fetch returns 200 but with a *different* script: it hard-exits if ollama isn't pre-installed, lacks the repo version's `</dev/tty` fix for `curl | sh` stdin, and uses the same typo'd `kultivaite` URL. The deployed landing page itself is also a different 281-line SEO/analytics page, not `landing/index.html`. The README quickstart "works" only by serving stale bits.
12. **"274 MB" as a blanket embed size** — true for `ollama pull nomic-embed-text` (274.3 MB verified) but the zero-to-local bootstrap actually downloads `nomic-embed-text-v1.5.Q8_0.gguf` at **146,146,432 bytes ≈ 146 MB** (`hardware.py:81-88`). README:476-477 says "the installer handles this" — the repo's install.sh delegates to `kultivait init` (setup screen), which handles the llama.cpp path; the *deployed* script pulls ollama's 274 MB itself. Two paths, two sizes, one number in the docs.
13. **README:65 "distill corpus — assemble anchor set & held-out roster"** — the subcommand only prints a dry-run report (`cmd_distill_corpus:785-791` → `dry_run_report`); corpus files are actually written by `distill generate` (`write_corpus`). `--dry-run` is decorative. Minor overstatement.

*Context note (not a doc claim): `posthog>=7.26.0` is a runtime dependency (`pyproject.toml:14`) and `server.py:17,170-181` activates a PostHog client when `POSTHOG_PROJECT_TOKEN` is set. No README/landing text claims "no telemetry," but the landing's "private" ethos framing and map #132's remove-telemetry decision make this the first thing the restructure ticket must reconcile. Also `pyproject.toml:4` still ships the placeholder description "Add your description here."*

---

## (c) UNVERIFIABLE — no repo artifact can substantiate; what would be needed

1. **Trellis routing shares (62% / 23% / 11% / 4%) and "rerouted local 85%"** (index.html:572-575,605) — no harvest dataset ships in the repo. Needs: a committed anonymized ledger sample or removal of the numbers.
2. **"Roughly two of every three prompts sent to a frontier model were weeds"** (index.html:615) — anecdote; no artifact. Needs: the agentic-session corpus it references, or softer wording.
3. **Ledger example rows ($0.31 claude, $0.09 gemini; "Session total: $0.40 … versus $6.12")** (index.html:672-698) — arithmetically plausible under `CLI_PRICING` (`config.py:34-41`), but no session artifact exists. Needs: a real exported harvest.
4. **Pruning-gate numbers (96K→1.8K, 41K→1.2K, 74K→2.4K)** (index.html:713-741) — the gate machinery produces such briefs (`gates.py`), but these specific numbers are invented. Needs: real gate runs, or labeling as illustrative.
5. **Harvest month stats ("2.1M tokens, $127 kept, 38% pruned, ~0.9 kWh — figures from a typical month of daily agentic coding")** (index.html:796-814) — no month of ledger data in repo; the kWh figure additionally rests on the nonexistent Wh feature (see (b)#10).
6. **"Saved this session $4.87 / 31 Wh" hero tally** (index.html:604-608) — the value is JS-fabricated and grows on a timer (:897-903); not derivable from anything.
7. **Roadmap "~85% retention rate"** (README:587) — roughly consistent with the distill_eval recall range (86.5–100%) but not a recorded metric anywhere. Needs: a defined measurement (the planned planted-fact harness) or a range citation.

---

## Top 5 most damaging false claims (for the restructure #139 / landing-sync #138 tickets)

1. **Dead starter-prompt URL** `https://www.kultivait.ai/start.md` → 404 on both CTA buttons (landing:540,829). Primary conversion path broken.
2. **Deployed install.sh is stale and divergent** (hard-fails without ollama; no `</dev/tty` fix; typo URL) while README:29 tells strangers to `curl | sh` it — works by luck, fails loudly on ollama-less machines.
3. **Typo'd git URL `kultivaite`** in README:32 + install.sh:17 (repo and deployed) — every install depends on a GitHub rename redirect surviving.
4. **Distiller-model table numbers irreproducible** from `experiments/distill_eval/results.json` (3 of 5 recall figures + most tokens-kept/time cells mismatch) and "gemma4:latest (default)" is not a code default — the one place README shows a data table doesn't recompute.
5. **Landing watt-hour claims** (live "31 Wh" counter, "~0.9 kWh/month") imply ledger Wh accounting that does not exist (README:591 lists it as roadmap).

Runners-up: `KULTIVAIT_RUNTIME` does not skip the setup screen (README:508-510); `tool_fallback` metadata key renamed to `fallback_reason` (README:227); Anthropic-endpoint tools *are* implemented (README:228); "Streaming responses" still listed as roadmap (README:590).

## Verification snippets (repro)

```bash
uv run experiments/routing_trust.py          # → accuracy: 24/24, dangerous: 0/24
curl -s https://kultivait.ai/start.md        # → 404 (apex and www)
curl -sI https://github.com/Standard-Pentest/kultivaite   # → 301 → kultivait
python3 - <<'EOF'                            # distill table recompute
import json, statistics as s
rows = json.load(open('experiments/distill_eval/results.json'))
for m in {r['model'] for r in rows}:
    rs = [r for r in rows if r['model']==m]
    print(m, round(100*s.mean(r['recall'] for r in rs),1),
          round(100*sum(r['tokens_after'] for r in rs)/sum(r['tokens_before'] for r in rs),1),
          round(s.mean(r['seconds'] for r in rs),1))
EOF
```
