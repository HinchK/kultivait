# Research: routing-signal inventory + shadow mechanics (#177)

Date: 2026-09-09 · Branch: `research/centroid-signals` · Parent map: #176
Method: local survey of live code (commit `fd398ed`) + live data in `~/.kultivait/` (read-only; live proxy untouched). Trust classes per ADR 0013 (docs/adr/0013-corpus-and-label-assembly.md).

## 1. Signal-retention register

| Source | Prompt text retained | Evidence |
|---|---|---|
| Ledger snippet (every dispatch row) | Last user message truncated to **80 chars** — `user_text[:80]`; stored verbatim via `Ledger.record(**extra)` | src/kultivait/server.py:236 (`_decision_meta`), src/kultivait/ledger.py:62 |
| Tollbooth pending ticket | **Full** `original_prompt` while pending only; queue file `~/.kultivait/pending_tolls.jsonl` is rewritten on every state change and **unlinked at startup** — zero persistence beyond in-flight | src/kultivait/tollbooth.py:39 (field), :481 (queue write), :213-217 (startup unlink); path src/kultivait/cli.py:56 |
| Tollbooth answered choice | `route_choice` + `toll` mark land on the dispatch's ledger row (with the 80-char snippet); sticky cache is in-memory, 3600 s TTL | src/kultivait/server.py:460-461, :519; src/kultivait/tollbooth.py:210, :278-283 |
| Tollbooth expired/no-presence menu | **Full** `original_prompt` + all options archived to `~/.kultivait/escalations/menu-*.json` (forever) | src/kultivait/tollbooth.py:435-467 (`_archive_missed_menu` → `save_raw`), src/kultivait/escalations.py:96-105 |
| Counterfactual (late answer to expired ticket) | **No prompt text at all** — records only `counterfactual_choice`, `counterfactual_ticket_id`, `effort_canonical` | src/kultivait/tollbooth.py:414-433 |
| Escalation archive (`esc-*.json`) | **Full conversation** (`messages` list, verbatim) + 80-char snippet index field | src/kultivait/escalations.py:79-94 (`EscalationStore.save`), :61-72 (`render_transcript`) |
| Benchmark rows (`tag="benchmark"`, capability-eval) | **No prompt text** — task outcomes only (`task_id`, tokens, tier) | src/kultivait/capability_eval.py:39-59; 16,219 live rows confirm |

Key code facts:

- `_decision_meta` (src/kultivait/server.py:225-237) is the single place dispatch snippets are made; 80 is the exact cap; live census shows 50/73 snippets hit it exactly.
- Escalation archives are the only historical source with full prompts: 46 files, 2,092,497 transcript chars total, last-user-text min/median/max = 27/581/11,068 chars.
- No `menu-*.json` files exist (zero expired/no-presence tolls to date); no `pending_tolls.jsonl`, no `toll_answers/` dir at census time.

## 2. Live-harvest census (`~/.kultivait/ledger.jsonl`, 2026-09-09)

Total rows: **16,923**. Of these, 16,219 are `tag="benchmark"` (capability-eval = bronze; no text) and 631 are legacy pre-meta dispatch rows (no snippet field era); only **73 rows carry any snippet**.

| Trust class (ADR 0013 mapping) | Rows | Rows w/ usable snippet | Snippet len sample (n=20): min/med/max | Notes |
|---|---|---|---|---|
| Gold — toll answered | **0** | 0 | — | No human toll pick ever recorded in ledger |
| Silver — toll expired | **0** | 0 | — | Zero expired tolls |
| Silver — auto-policy outcome | **2** | 2 | 60/60/60 (n=2) | Both `auto:local` |
| Silver — plain served rows | 16,921 (16,850 w/o text) | 71 | 2/80/80 | Text-bearing subset only; rest are benchmark/legacy |
| Counterfactual rows | **0** | 0 | — | None recorded |
| Escalation-bearing rows | 42 | 42 | 27/80/80 | 41 carry `escalation_id` → full transcript in store |
| Bronze — benchmark (capability-eval) | 16,219 | 0 | — | No prompt text by design |
| **All prompt rows** | **16,923** | **73** | 2/80/80 | Full population: 50/73 snippets at the 80-char cap |

Supporting counts: toll-answered rows with `route_choice` recorded = **0**. Preprocess marks: `None`=16,868, `skipped`=27, `ok`=23, `preprocess_timeout`=5. Verdicts: `None`=16,868, local=25, frontier=29, contested=1. Fingerprints: 55 snippet rows carry one, **23 distinct** (heavy dedup). Escalation store: 46 `esc-*.json` (full transcripts), 0 `menu-*.json`. Shadow log: 15 rows.

**Snippet-sufficiency verdict (silver-class learning):** the 80-char snippet is *not* sufficient as embedding substrate for learned centroids. Half of the tiny text-bearing set (50/73) is truncated at exactly 80 chars — topic keywords survive, task structure does not. The realistic silver pool today is 73 snippets (≈23 distinct conversations); the only full-text corpus is the 46 escalation transcripts (median 581 chars, max 11 k). Any centroid spec must treat ledger snippets as weak/partial anchors and escalation transcripts (plus future full-prompt capture — a one-line widening of `_decision_meta` or a side-car) as the primary real-prompt source.

## 3. Embed cost (measured, `nomic-embed-text:latest` via ollama `/api/embed`, dim 768)

Reuses `_embed_batch`'s exact request shape (src/kultivait/cli.py:207-223); live config `runtime="ollama"`, `embed_model="nomic-embed-text:latest"`.

| Workload | n | ms/prompt | Batch wall time |
|---|---|---|---|
| 50 real ledger snippets (≤80 chars) | 50 | **8.22** | 411 ms |
| 46 real escalation full texts (med 581, max 11,068 chars) | 46 | **19.92** | 916 ms |

Projections: re-embed all 73 snippet-bearing rows ≈ **0.6 s**; all 46 escalation texts ≈ **0.9 s**; a hypothetical full-history re-embed of all 16,923 rows at realistic length ≈ **337 s (~5.6 min)** single-threaded. Embedding cost is a non-issue at current and near-term harvest size; no batching infra or caching layer is warranted.

## 4. Shadow-mechanics design facts

Live classify path today:

- `Router.classify` is a closure `_classify` (src/kultivait/server.py:239-244): `router.classify(embed(user_text))`, invoked at the top of both request handlers — `POST /v1/chat/completions` (server.py:609) and `POST /v1/messages` (server.py:690). `router` and `embed` are `create_app` constructor args (server.py:139-141), wired in `kultivait serve` as `build_router(config)` + `embed=lambda text: _embed_batch(config, [text])[0]` (src/kultivait/cli.py:623-624).
- Centroids are **not learned today**: `build_router` averages role-seed embeddings (src/kultivait/cli.py:226-233). `Router` is pure numpy cosine vs a normalized centroid matrix (src/kultivait/router.py:15-42) — a candidate centroid table is just a second `Router` instance; classify is µs-scale and needs **no second embed call** (reuse the vector `_classify` already computed).

Precedent (ADR 0017 shadow pass — the wiring to copy):

- Post-response, fire-and-forget hook `shadow_after_response` (src/kultivait/server.py:486-507; src/kultivait/distill/shadow.py:190-219): gated on mode/sample-rate, submits to a **single-worker ThreadPoolExecutor** (shadow.py:29-31) with total exception isolation — zero latency on the request path by construction.
- Rows append to `~/.kultivait/shadow.jsonl` (shadow.py:44-45, :57-67), **never the main ledger**; a listener registry fans rows out to the dashboard SSE (shadow.py:52-54; registered at server.py:844-846, hydrated into the harvest snapshot at server.py:863-866).
- Row shape: `{ts, fingerprint, prompt_hash, incumbent{...}, shadow{...}, agree}` (shadow.py:34-41); readiness/cutover reads derive purely from the log (shadow.py:84-111, :300-375).

**Hook point for candidate-centroid dual-classify:** mirror `shadow_after_response` inside `_resolve_route` (server.py:486-507 is the exact block to parallel) — after the live decision exists, submit an executor job that runs the *same* user-text vector against the candidate centroid `Router` and logs `{live tier/margin/escalated, candidate tier/margin/escalated, agree, fingerprint, prompt_hash}`. Since no embed is needed, the job is numpy-only and can also run inline-then-log-async if ordering matters. **Where learned-centroid shadow rows log:** either the existing `shadow.jsonl` via `append_shadow_log` (rows are dicts; model fields become e.g. `centroids:role-seeds` vs `centroids:learned-v1`, and dashboard fan-out comes free) or a sibling `~/.kultivait/centroid_shadow.jsonl` reusing the same append/listener pattern — either keeps shadow signal out of the ledger per ADR 0017. Live sampling: 15 existing shadow rows (incumbent `qwen3.5:4b` vs `kv-judge-llama32-3b-g0/g1`, 0/15 agree) prove the pipeline runs end-to-end today.

## Verified-facts summary for the spec

1. Real-prompt learning substrate today = 73 ledger snippets (80-char cap, 50 truncated) + 46 full escalation transcripts. Gold class is empty; silver-with-text is 73 rows / ≈23 distinct fingerprints.
2. 80-char snippets are insufficient alone; escalation transcripts are the only full-text history. Retention for *future* signal is the cheap fix point (`_decision_meta`, server.py:236).
3. Embedding is effectively free at this scale: ≤20 ms/prompt, sub-second full re-embed of all real text.
4. Dual-classify shadow slots in exactly where the ADR 0017 shadow pass already lives; no live-decision surface needs to change, and `shadow.jsonl` (or a sibling) is the logging home.
