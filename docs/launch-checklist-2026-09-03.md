# Launch checklist — 2026-09-03

Wayfinder ticket: [#140](https://github.com/Standard-Pentest/kultivait/issues/140) · parent map: [#132](https://github.com/Standard-Pentest/kultivait/issues/132)
Subject: upstream `Standard-Pentest/kultivait` @ `e1c245c` (post #133–#139)
Machine: macOS, Apple M4 Pro, 24 GB, ollama garden present (the map's stated hardware precondition)
Method: fresh canonical clone + fresh `uv tool install` from the public git URL; isolated `$HOME` for config/ledger; live verification runs.

**Verdict: ALL AXES PASS.**

## 1. Green-harvest gate (macOS) — PASS

Cold path, exactly as the README quickstart tells it:

- `uv tool install --from git+https://github.com/Standard-Pentest/kultivait kultivait` — clean install from canonical URL (no redirect luck; #135/#137).
- `kultivait init` (isolated `$HOME`) — garden auto-detected (qwen3.5:4b simple / qwen3:14b reasoning / agy docs / claude architect / nomic-embed embed); `config.toml` + `onboarding.json` written.
  - Automation note: this re-run used the documented headless flag `kultivait init --no-setup` — the pty+Esc replay of the interactive screen is timing-flaky under automation (lone-ESC escape-sequence decode race). The interactive stranger path was proven end-to-end in #135 (screen rendered, Esc registered, virtual-tier config written). No code regression: `cmd_init` is unchanged since #135 (only README/landing/pyproject-description changed between `e1c245c` and the #135-verified tree).
- `kultivait serve --port 4514` — boots, cultivates seed centroids, listens.
- `POST /v1/chat/completions` (trivial prompt) — routed to `qwen3.5:4b` (local), content `ok`.
- `kultivait harvest` — `prompts routed 1 (100% local)`, ledger tallied.
- Wall-clock ≈ 1 min warm garden; well inside the ≤ 15 min gate.

## 2. No telemetry in the build — PASS

- Tree: zero PostHog/telemetry wiring in `src/`, `pyproject.toml`, `uv.lock`, `landing/` (remaining word-hits are the ADR-0015 `headline_telemetry` eval field and the landing's true "0 bytes of telemetry phoned home" receipt).
- Installed build: the `uv tool` environment's site-packages contains no `posthog` (dependency chain removed in #133; transitive set absent from `uv.lock`).

## 3. No internal working files in the repo — PASS

Fresh-clone root: `AGENTS.md CLAUDE.md CONTEXT.md docs evals experiments landing LICENSE pyproject.toml README.md src tests uv.lock vercel.json` — exactly the public surface. No `TODO*`, `HANDOFF`, `BACKLOG`, logs, reports, `scripts/`, or stray dirs (#134).

## 4. Canonical-home links — PASS

- Upstream: description set; `homepage = https://kultivait.ai`; topics `cost-savings, llm, llm-routing, local-first, ollama, openai-compatible, proxy` (#137).
- Fork `HinchK/kultivait`: description redirects — "Working fork — canonical home: github.com/Standard-Pentest/kultivait (issues & PRs live upstream)"; issues disabled there.
- Shipped surfaces (README/landing/docs/src/pyproject) carry no `kultivaite` typo and no fork-as-door links; the contributor-door doc (`docs/agents/issue-tracker.md`) accurately describes the fork relationship; `pyproject` author field is author attribution, not a door.

## 5. README / landing claims verified-true — PASS

- `uv run experiments/routing_trust.py` (in the fresh clone): `accuracy: 24/24 (100%)`, `dangerous misroutes: 0/24`, `wasteful misroutes: 0/24`.
- Distiller table recomputed from `experiments/distill_eval/results.json`: gemma4 100.0 / qwen3:14b 96.3 / phi4:14b 89.6 / qwen2.5:14b 87.2 / llama3.1:8b 86.9 — matches the README table cell-for-cell.
- Landing spot-checks: repo-reproducible receipts present (24/24 stat + reproduce command); ledger/pruning figures labeled illustrative; fabrication grep (`$4.87`, `31 Wh`, `2.1M`, `$127`, `0.9 kWh`, branch-share percents, `tally-*` counters) → 0 hits; HTML parse-balanced.
- Known deferred truth gaps (documented, not hidden): the deployed kultivait.ai serves a stale landing + stale `install.sh` until the out-of-scope deploy happens; `/start.md` resolves only after deploy (rewrite is in `vercel.json`).

## 6. Secrets sweep (history-adjacent) — PASS

- Full history scanned (174 commits, all refs): zero matches for PostHog project tokens (`phc_…`), Anthropic/OpenRouter keys (`sk-ant-…`, `sk-or-v1-…`), GitHub PATs (`ghp_…`), AWS keys (`AKIA…`), or private-key blocks.
- No `.env`, `.pem`, `.key`, `credentials.toml`, or `.crt` file was ever committed (diff-filter scan over all refs).
- `.env` (which held the now-deleted PostHog token) was permanently gitignored and never tracked — confirmed by empty `git log -- .env`.
- Credential examples in README are placeholders (`sk-ant-...`).

## Reproduction snippets

```bash
git clone https://github.com/Standard-Pentest/kultivait && cd kultivait
uv run experiments/routing_trust.py        # 24/24, 0 dangerous, 0 wasteful
python3 - <<'EOF'                          # distiller table
import json, statistics as s
rows = json.load(open('experiments/distill_eval/results.json'))
for m in sorted({r['model'] for r in rows}):
    rs = [r for r in rows if r['model'] == m]
    print(m, round(100*s.mean(r['recall'] for r in rs), 1))
EOF
git rev-list --all --count                  # 174
git grep -l -E "phc_[A-Za-z0-9]{20,}|sk-ant-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{30,}|AKIA[0-9A-Z]{16}" $(git rev-list --all)   # no output
```

Suite at artifact time: `uv run pytest -q` → **713 passed, 2 skipped**.
