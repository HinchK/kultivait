# Launch checklist — 2026-09-10

Wayfinder ticket: [#194](https://github.com/Standard-Pentest/kultivait/issues/194) · parent map: release v0.2.0
Subject: upstream `Standard-Pentest/kultivait` @ `aaf8fc7`
Machine: macOS, Apple M4 Pro, 24 GB, ollama garden present (the map's stated hardware precondition)
Method: fresh git inspection + live verification runs; isolated `$HOME` for quickstart check; full test suite pass.

**Verdict: ALL AXES PASS.**

## 1. Green-harvest gate (macOS) — PASS

Cold path, exactly as the README quickstart tells it:

- `uv tool install --from git+https://github.com/Standard-Pentest/kultivait kultivait` — clean install from canonical URL.
- `kultivait init --no-setup` (isolated `$HOME`) — garden auto-detected (qwen3.5:4b simple / qwen3:14b reasoning / agy docs / claude architect / nomic-embed embed); `config.toml` + `onboarding.json` written.
- `kultivait serve --port 4514` — boots, cultivates seed centroids, listens.
- `POST /v1/chat/completions` (trivial prompt) — routed to `qwen3.5:4b` (local), content `ok`.
- `kultivait harvest` — `prompts routed 1 (100% local)`, ledger tallied with energy (estimated) block.
- Wall-clock ≈ 1 min warm garden; well inside the ≤ 15 min gate.

## 2. No telemetry in the build — PASS

- Tree: zero PostHog/telemetry wiring in `src/`, `pyproject.toml`, `uv.lock`, `landing/` (remaining word-hits are the ADR-0015 `headline_telemetry` eval field and the landing's true "0 bytes of telemetry phoned home" receipt).
- Installed build: the `uv tool` environment's site-packages contains no `posthog` (dependency chain permanently removed in #133; transitive set absent from `uv.lock`).

## 3. No internal working files in the repo — PASS

Fresh-clone root: `AGENTS.md CLAUDE.md CONTEXT.md CONTRIBUTING.md docs evals experiments landing LICENSE pyproject.toml README.md src tests uv.lock vercel.json` — exactly the public surface. No `TODO*`, `HANDOFF`, `BACKLOG`, logs, reports, `scripts/`, or stray dirs (#134).

## 4. Canonical-home links — PASS

- Upstream: description set; `homepage = https://kultivait.ai`; topics `cost-savings, llm, llm-routing, local-first, ollama, openai-compatible, proxy` (#137).
- Fork `HinchK/kultivait`: description redirects — "Working fork — canonical home: github.com/Standard-Pentest/kultivait (issues & PRs live upstream)"; issues disabled there.
- Shipped surfaces (README/landing/docs/src/pyproject) carry no `kultivaite` typo and no fork-as-door links; contributor-door docs accurately describe the fork relationship.

## 5. README / landing / eval claims verified-true — PASS

- `uv run experiments/routing_trust.py`: `accuracy: 24/24 (100%)`, `dangerous misroutes: 0/24`, `wasteful misroutes: 0/24`.
- Distiller table mechanically derived from `experiments/distill_eval/results.json` matching README exactly:
  - gemma4:latest 94% / 68% / 31s / 92% gen-2 survival
  - phi4:14b 92% / 74% / 25s / 90% gen-2 survival
  - qwen3:14b 87% / 64% / 22s / 87% gen-2 survival
  - qwen2.5:14b 83% / 54% / 19s / 78% gen-2 survival
  - llama3.1:8b 77% / 57% / 10s / 69% gen-2 survival
- Model-free unit test `tests/test_distill_table_parity.py` passes 100% green.
- Energy sanity eval: all 6 gates PASS (`experiments/energy_eval/results.md`).
- Ambient gate eval: all 6 gates PASS (`experiments/ambient_gate_eval/results.md`).
- Recalibration safety eval: R1 PASS (0 dangerous misroutes), R2 FAIL (accuracy floor held, shadow-only disposition honored per ADR 0021).

## 6. Secrets sweep (history-adjacent) — PASS

- Full history scanned (226 commits, all refs): zero matches for PostHog project tokens (`phc_…`), Anthropic/OpenRouter keys (`sk-ant-…`, `sk-or-v1-…`), GitHub PATs (`ghp_…`), AWS keys (`AKIA…`), or private-key blocks.
- No `.env`, `.pem`, `.key`, `credentials.toml`, or `.crt` file was ever committed (diff-filter scan over all refs).
- `.env` remains gitignored and untracked.
- Credential examples in README and runbooks are placeholders (`sk-ant-...`).

## Reproduction snippets

```bash
git clone https://github.com/Standard-Pentest/kultivait && cd kultivait
uv run experiments/routing_trust.py        # 24/24, 0 dangerous, 0 wasteful
uv run pytest tests/test_distill_table_parity.py  # table parity test
git rev-list --all --count                  # 226
git grep -l -E "phc_[A-Za-z0-9]{20,}|sk-ant-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{30,}|AKIA[0-9A-Z]{16}" $(git rev-list --all)   # no output
```

Suite at artifact time: `uv run pytest -q` → **771 passed, 2 skipped**.
