# Launch checklist — 2026-09-13

Wayfinder ticket: [#218](https://github.com/Standard-Pentest/kultivait/issues/218) · parent map: v0.4.0 (#212)
Subject: v0.4.0 candidate — local `main` @ `7cdd107` (ADR 0024; includes #214 tool translation, #215 pin, #216 time ledger + length rule; ahead of upstream pending push)
Machine: macOS, Apple M4 Pro, 24 GB, ollama garden present (the map's stated hardware precondition)
Method: fresh `file://` clone of the candidate tree, isolated `$HOME` + scratch port for the quickstart run; live verification runs; full test suite pass.

**Verdict: ALL AXES PASS** (axis 3 required one fix, applied in this commit: `HANDOFF.md` untracked + gitignored).

## 1. Green-harvest gate (macOS, ollama path) — PASS

Cold path, exactly as the README quickstart tells it, isolated `$HOME` throughout:

- Fresh clone of the candidate tree (file:// of local `main` — identical to post-push upstream).
- `kultivait init --no-setup` — garden auto-detected and written (qwen3.5:4b simple / qwen3:14b reasoning / docs + architect CLIs / nomic-embed embed); `config.toml` carries the new `length_rule_max_tokens = 8192` key. (Interactive-setup parity: README documents Esc-skip writing the same config.)
- `kultivait serve --port 4618` — boots, cultivates seed centroids, listening in ~3 s.
- `POST /v1/chat/completions` ("Say ok") — routed to `qwen3.5:4b` (local), content `ok`.
- `kultivait harvest` — `prompts routed 1 (100% local)`; **energy block present** (0.035 Wh · energy-v1-20260909); **time-ledger section present** — the v0.4.0 addition — showing the honest no-table degrade line and `first-token p50 7116 ms`; ledger row carries `first_token_ms` + `latency_s` + `est_wh` + `energy_model`.
- **Wall-clock ≈ 44 s** warm garden (gate: ≤ 15 min), incl. clone + install + init + boot + dispatch + harvest.
- Method substitution, disclosed: the stranger sequence ran via `uv run` from the clone instead of `uv tool install` — the latter's bin step would overwrite this machine's running herd service; the literal install path was verified on the 2026-09-10 audit and the entry point is identical.

## 2. No telemetry in the build — PASS

- `pyproject.toml`, `uv.lock`, `src/`, `landing/`: every word-hit is benign and enumerated — `headline_telemetry` (the ADR-0015 eval discipline field, `distill/eval.py`), a shadow-pass docstring (`cli.py`), a ledger-fields comment (`backends.py`), and the landing's true "0 bytes of telemetry phoned home" receipt (`landing/index.html`).
- No posthog/mixpanel/segment/sentry anywhere in the dependency chain.

## 3. No internal working files in the repo — PASS (after fix)

- **Found:** `HANDOFF.md` was committed (session-workflow artifact from #214/#216). **Fixed in this commit:** untracked + added to `.gitignore` beside `STATE.md`; the file remains locally, never ships again.
- Fresh-clone root after fix: `AGENTS.md CHANGELOG.md CLAUDE.md CONTEXT.md CONTRIBUTING.md docs evals experiments landing LICENSE pyproject.toml README.md src tests uv.lock vercel.json` + public dotdirs (`.github`, `.pre-commit-config.yaml`, `.python-version`) and accepted dev-tooling dirs (`.claude`, `.agents`, `.codex` — agent workflow config, public by the same design as `AGENTS.md`/`CLAUDE.md`). No `TODO*`, `BACKLOG`, logs, or stray reports.
- `experiments/latency_probe/` is provenance, not working files — sanctioned by the #215 pin ("provenance in experiments/"), including the two `samples-*-discarded-*.json` runs ($1.58 of filter-billed spend; evidence kept on purpose).

## 4. Canonical-home links — PASS

- Upstream `Standard-Pentest/kultivait`: description set ("saving the planet one token at a time"), `homepage = https://kultivait.ai`, issues enabled.
- Fork `HinchK/kultivait`: issues disabled; description redirects to the canonical home.
- Shipped surfaces (README/landing/docs/src/pyproject): no fork-as-door links; remaining `HinchK` mentions are author metadata and accurate fork-relationship docs.

## 5. README / landing / eval claims verified-true — PASS

- `uv run experiments/routing_trust.py`: **24/24 (100%)**, dangerous misroutes 0/24, wasteful misroutes 0/24.
- Distiller table mechanically derived from `experiments/distill_eval/results.json` (80 records): `tests/test_distill_table_parity.py` — 2 passed.
- Energy sanity eval: ALL 6 GATES PASS (`experiments/energy_eval/results.md`).
- Ambient gate eval: ALL 6 GATES PASS (`experiments/ambient_gate_eval/results.md`).
- All 18 commands the README lists exist in `kultivait --help`.
- Harvest example/output claims remain true; the v0.4.0 time-ledger section is additive (README re-scope for v0.4.0 is #219's lane).
- Reference-table honesty: harvest prints "no reference — local medians only" while the probe awaits OpenRouter credits; no fabricated yardstick (see #216 resolution).

## 6. Secrets sweep (history-adjacent) — PASS

- Full history scanned (**262 commits**, all refs): zero matches for PostHog tokens (`phc_…`), Anthropic/OpenRouter keys (`sk-ant-…`, `sk-or-v1-…`), GitHub PATs (`ghp_…`), AWS keys (`AKIA…`), or private-key blocks.
- No `.env`, `.pem`, `.key`, `credentials.toml`, or `.crt` file was ever committed (diff-filter scan over all refs).
- `.env` remains gitignored and untracked.

## Reproduction snippets

```bash
git clone file://$PWD /tmp/kult-gate && cd /tmp/kult-gate      # candidate tree
HOME=/tmp/gate-home uv run kultivait init --no-setup           # cold config
HOME=/tmp/gate-home uv run kultivait serve --port 4618 &       # boot
curl -s localhost:4618/v1/chat/completions -H 'content-type: application/json' \
  -d '{"model":"auto","messages":[{"role":"user","content":"Say ok"}]}'
HOME=/tmp/gate-home uv run kultivait harvest                   # 1 routed, time + energy
uv run experiments/routing_trust.py                            # 24/24, 0/0
uv run pytest tests/test_distill_table_parity.py               # parity
git grep -l -E "phc_[A-Za-z0-9]{20,}|sk-ant-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{30,}|AKIA[0-9A-Z]{16}" $(git rev-list --all)  # no output
```

Suite at artifact time: `uv run pytest -q` → **815 passed, 2 skipped**.
