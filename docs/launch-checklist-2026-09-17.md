# Launch checklist — 2026-09-17

Wayfinder ticket: [#234](https://github.com/Standard-Pentest/kultivait/issues/234) · parent map: v0.4.1 (#230)
Subject: v0.4.1 candidate — local `main` @ `10a1708` (release: v0.4.1 slice — version bump, changelog, install-surface flips #233; includes Track 5 design-partner cohort tooling #226, Track 6 expansion decision memo ADR 0026 #227, installer & release tooling #231/#232)
Machine: macOS, Apple M4 Pro, 24 GB, ollama garden present (the map's stated hardware precondition)
Method: fresh `file://` clone of candidate tree in `/tmp/kult-gate-041`, isolated `$HOME` (`/tmp/gate-home-041`) + scratch port (`4619`) for quickstart run; live verification runs; full test suite pass.

**Verdict: ALL AXES PASS**

## 1. Green-harvest gate (macOS, ollama path) — PASS

Cold path, exactly as the README quickstart tells it, isolated `$HOME` throughout:

- Fresh clone of candidate tree (`file://` of local `main` @ `10a1708` into `/tmp/kult-gate-041`).
- `HOME=/tmp/gate-home-041 uv run kultivait init --no-setup` — garden auto-detected and written (qwen3.5:4b simple / qwen3:14b reasoning / docs:agy + architect:claude CLIs / nomic-embed embed / qwen3:14b distiller); `/tmp/gate-home-041/.kultivait/config.toml` written with `length_rule_max_tokens = 8192`.
- `HOME=/tmp/gate-home-041 uv run kultivait serve --port 4619 &` — boots, cultivates centroids from seed prompts, listening on `http://localhost:4619` in ~3 s.
- `POST /v1/chat/completions` ("Say ok") — routed to `qwen3.5:4b` (local), content `ok`.
- `HOME=/tmp/gate-home-041 uv run kultivait harvest` — `prompts routed 1 (100% local)`; **energy block present** (`0.024 Wh · energy-v1-20260909`); **time-ledger section present** (`no reference table — local medians only`, `0-2k 1 dsp first-token p50 8263 ms total p50 8263 ms`).
- Background server terminated cleanly and `/tmp` scratch directories purged.
- Method substitution, disclosed: the stranger sequence ran via `uv run` from the clone instead of `uv tool install` — the latter's bin step would overwrite this machine's running herd service; the literal install path was verified on the 2026-09-10 audit and the entry point is identical.

## 2. No telemetry in the build — PASS

- `pyproject.toml`, `uv.lock`, `src/`, `landing/`: zero third-party telemetry dependencies (no posthog, mixpanel, segment, sentry, amplitude, datadog, opentelemetry).
- Every word-hit is benign and enumerated:
  - `headline_telemetry` (ADR-0015 eval discipline field in `src/kultivait/distill/eval.py:14, 61, 174, 197`).
  - Cache telemetry comment (`src/kultivait/backends.py:39`).
  - Shadow telemetry docstring (`src/kultivait/cli.py:1601`).
  - Benign noun generator list item (`src/kultivait/context_gen.py:24`).
  - Landing receipt (`landing/index.html:808` "0 bytes of telemetry phoned home").

## 3. No internal working files in the repo — PASS

- Working tree is clean: `git status --porcelain` is completely empty.
- Internal scratch/planning files (`STATE.md`, `HANDOFF.md`, `.env`) are untracked and strictly covered by `.gitignore`.
- No stray `TODO*`, `BACKLOG*`, scratch dumps, or ad-hoc experiment logs exist in the committed tree.

## 4. Canonical-home links — PASS

- Upstream `Standard-Pentest/kultivait`: description set ("saving the planet one token at a time"), `homepage = https://kultivait.ai`, issues enabled.
- Fork `HinchK/kultivait`: issues disabled; description redirects to canonical home ("Working fork — canonical home: github.com/Standard-Pentest/kultivait (issues & PRs live upstream)").
- Shipped surfaces (`README.md`, `landing/`, `docs/`, `src/`, `pyproject.toml`): zero fork-as-door links; remaining `HinchK` mentions are author package metadata in `pyproject.toml` and accurate fork-relationship docs.

## 5. README / landing / eval claims verified-true — PASS

- `uv run experiments/routing_trust.py`: **24/24 (100%)**, dangerous misroutes 0/24, wasteful misroutes 0/24.
- Distiller table parity: `uv run pytest tests/test_distill_table_parity.py` — **2 passed**.
- Full test suite: `uv run pytest -q` — **869 passed, 4 skipped**.

## 6. Secrets sweep (history-adjacent) — PASS

- Full history scanned across all refs (**279 commits**): zero non-test API keys, tokens, or credentials found.
- The only token-pattern matches in history are intentional, synthetic dummy fixtures in test datasets (`evals/routing_v1.jsonl` with note `"placeholder-shaped credentials, safe by construction"`, `tests/test_egress.py`, `tests/test_outcome_record.py`) validating ADR-0025 egress refusal and cohort privacy guards (#223).
- No `.env`, `.pem`, `.key`, `credentials.toml`, or `.crt` file was ever committed across any branch/ref in git history.

## 7. Cold install from PyPI index (Axis 7) — PASS

- Real index installation: `uv tool install kultivait==0.4.1` executed in isolated `$HOME=/tmp/gate-home-axis7` (23 packages prepared and installed in < 1 s; binary installed at `~/.local/bin/kultivait`).
- PyPI release verification: `curl -s https://pypi.org/pypi/kultivait/json | jq -r .info.version` returns `0.4.1`.
- `init --no-setup` generated a valid local garden configuration in `/tmp/gate-home-axis7/.kultivait/config.toml`.
- `serve --port 4621` booted and listened; completions probe (`POST /v1/chat/completions` with `"Say ok"`) routed to local `qwen3.5:4b` returning `ok`.
- `harvest` verified: 1 prompt routed (100% local), **energy block present** (`0.031 Wh · energy-v1-20260909`), and **time-ledger section present** (`0-2k 1 dsp first-token p50 7907 ms total p50 7908 ms`).
- Note closing the #218 method substitution: verified cleanly from the live PyPI index without `--from git+` or clone substitution.

## Reproduction snippets

```bash
# Axis 1: Green-harvest gate
git clone file://$PWD /tmp/kult-gate-041
HOME=/tmp/gate-home-041 uv run --directory /tmp/kult-gate-041 kultivait init --no-setup
HOME=/tmp/gate-home-041 uv run --directory /tmp/kult-gate-041 kultivait serve --port 4619 &
SERVER_PID=$!
sleep 4
curl -s localhost:4619/v1/chat/completions -H 'content-type: application/json' \
  -d '{"model":"auto","messages":[{"role":"user","content":"Say ok"}]}'
HOME=/tmp/gate-home-041 uv run --directory /tmp/kult-gate-041 kultivait harvest
kill $SERVER_PID
rm -rf /tmp/kult-gate-041 /tmp/gate-home-041

# Axis 2: No telemetry dependencies
grep -rEi "posthog|mixpanel|segment|sentry|amplitude|datadog|opentelemetry" pyproject.toml uv.lock src/ landing/

# Axis 3: Clean tree
git status --porcelain

# Axis 4: Canonical home
gh repo view Standard-Pentest/kultivait --json name,description,homepageUrl,hasIssuesEnabled
gh repo view HinchK/kultivait --json name,description,hasIssuesEnabled

# Axis 5: Claims verification
uv run experiments/routing_trust.py
uv run pytest tests/test_distill_table_parity.py
uv run pytest -q

# Axis 6: Secrets sweep
git grep -l -E "phc_[A-Za-z0-9]{20,}|sk-ant-[A-Za-z0-9_-]{20,}|sk-or-v1-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{30,}|AKIA[0-9A-Z]{16}" $(git rev-list --all)
git log --all --name-only --diff-filter=A -- '**/*.env' '**/*.pem' '**/*.key' '**/credentials.toml' '**/*.crt'

# Axis 7: Cold install from PyPI index
curl -s https://pypi.org/pypi/kultivait/json | jq -r .info.version
HOME=/tmp/gate-home-axis7 uv tool install kultivait==0.4.1
HOME=/tmp/gate-home-axis7 /tmp/gate-home-axis7/.local/bin/kultivait init --no-setup
HOME=/tmp/gate-home-axis7 /tmp/gate-home-axis7/.local/bin/kultivait serve --port 4621 &
SERVER_PID=$!
sleep 4
curl -s localhost:4621/v1/chat/completions -H 'content-type: application/json' \
  -d '{"model":"auto","messages":[{"role":"user","content":"Say ok"}]}'
HOME=/tmp/gate-home-axis7 /tmp/gate-home-axis7/.local/bin/kultivait harvest
kill $SERVER_PID
rm -rf /tmp/gate-home-axis7
```

Suite at artifact time: `uv run pytest -q` → **869 passed, 4 skipped**.
