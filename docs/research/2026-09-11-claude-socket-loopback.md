# Research: claude-socket / loopback interception — viability + test shapes

Date: 2026-09-11 · Branch: `research/claude-socket-loopback` · Seat: PM (claude, herd pane w9:p6)
Surfaces: `kultivait run -- claude` (Z1, #119, `src/kultivait/cli.py:1144`) and `kultivait hook loopback` (Z4, #122, `src/kultivait/hook/loopback.py`).
Method: code read at `8fc7863`, plus **eight no-root empirical tests** on this Mac (Claude Code 2.1.269, a native arm64 Bun 1.4.3 binary), plus a primary-source pass over the Claude Code docs. Nothing touched `/etc/hosts`, pf, the keychain, or the live `~/.kultivait` (the E8 proxy ran with an isolated `HOME`). Harnesses: `experiments/claude_socket/`.
Labels: **VERIFIED** (observed or read at source), **INFERRED**, **UNTESTED**.

---

> ### ⚠ Hazard today: the generated loopback *uninstall* does not uninstall (VERIFIED, E5)
> `kultivait hook loopback --generate-uninstall` prints two `sed` steps. On a scratch copy of a hosts file carrying the generated block:
> - **Step 1** `'/kultivait/d;/# --- kultivait/d'` deletes only the two **marker comments**. `127.0.0.1 api.anthropic.com` and `127.0.0.1 api.openai.com` **stay, now without markers**.
> - **Step 2** `'/api.anthropic.com$/;d;/api.openai.com$/d'` is invalid BSD sed: `invalid command code ;`, rc 1. Nothing is removed. (`loopback.py:78` builds it with `replace(" ", "$/;d;/")`.)
>
> Anyone who applied the hosts block and then follows the documented revert keeps every Anthropic/OpenAI client on the machine pinned to 127.0.0.1. Re-running can't find the lines because the markers are gone. **Fix:** a range delete between the markers, `sed -i '' '/^# --- kultivait transparent proxy/,/^# --- end kultivait ---$/d' /etc/hosts`, plus a test that applies generate → uninstall to a scratch file and asserts byte-identity with the original. (Verified on a scratch file only, never on `/etc/hosts`.)

## Verdicts

| Shape | Verdict | Blocker |
|---|---|---|
| **A. Env injection** — `kultivait run -- claude` | **Viable in principle, blocked end-to-end by one fixable bug.** The wrapper, Claude Code's route needs, and the SSE framing all check out. Real traffic fails on tool-schema translation. | Anthropic-format tools reach local runtimes untranslated (E8) |
| **B. Transparent loopback MITM** — `hook loopback` (hosts + pf + trusted cert) | **Not viable as shipped: the thing the config points at doesn't exist.** | `kultivait serve` has no TLS listener (E4, `cli.py:647`). The guide's `[tls] cert/key` config keys exist nowhere in `src/`. Trust and pinning are *not* the blockers. |
| C. Explicit forward proxy (`HTTPS_PROXY`) | Not built. Documented by Claude Code as supported. Needs a CONNECT-capable MITM proxy, so it inherits B's TLS work. | — |

The ranking the loopback module states itself (`loopback.py` trade-offs: app-level injection is the zero-root standard, loopback the advanced path) holds up. But the advanced path is config for a listener that was never built.

---

## Shape A — `kultivait run -- claude`

### What works (VERIFIED)

- **E1 wrapper.** It injects `ANTHROPIC_BASE_URL=http://127.0.0.1:<port>`, `OPENAI_BASE_URL=…/v1`, and `ANTHROPIC_API_KEY`/`OPENAI_API_KEY=kultivait` only if they're unset (a pre-set user key is preserved, so a real key is forwarded to the proxy). The exit code propagates (7 → 7), a missing binary gives 127, and the form without `--` works.
- **E2 route surface (recording stub mimicking kultivait's two routes, everything else 404).** `kultivait run -- claude -p` against a stub completed with rc 0. Claude Code sent exactly:
  - `HEAD /api/hello`: a connectivity probe. A **404 is tolerated**.
  - `POST /v1/messages?beta=true` ×2, `stream: true`, `model: claude-opus-5`, headers `anthropic-version`, a long `anthropic-beta` list, UA `claude-cli/2.1.269 (external, sdk-cli)`:
    - a small **no-tools** call (3.3k-char system);
    - the **main call: 24 tools**, 100 KB body, 9.2k-char system, `thinking: {type: adaptive}`, `context_management`, `output_config`, 3 `cache_control` blocks.
  - **No** `/v1/messages/count_tokens`, **no** `/v1/models`, **no** `/v1/chat/completions`. The docs agree: `count_tokens` is optional and Claude Code speaks only Messages format ([llm-gateway-protocol](https://code.claude.com/docs/en/llm-gateway-protocol)).
- **E3 in-process replay** of the captured 100 KB request into the real `create_app` (test-suite FakeBackends). HTTP 200 and a well-formed Anthropic SSE sequence (`message_start → content_block_start → content_block_delta… → content_block_stop → message_delta → message_stop`). The `?beta=true` query, adaptive thinking, and context_management don't break anything.

### What that replay also shows (VERIFIED, design consequence)

- **Claude Code's agent loop is always served locally.** Every main-loop call carries tools, and `_resolve_tier` (`server.py:264`) forces tool-bearing requests onto a local tool-capable tier. Classified frontier, the ledger reads `requested_tier: claude`, `fallback_reason: tools_unsupported`, served locally with all 24 tools and a 31k-char system. **`kultivait run -- claude` silently swaps Opus for the local model on every agent turn.** That's a product decision to state loudly (or gate behind a flag), not a transport detail.
- **Every frontier-classified turn archives an escalation synchronously** (35 KB for a one-turn call). Real sessions resend the whole conversation each turn, so the archive grows roughly quadratically with session length.
- **No-tools side calls** (the small call; the docs say Haiku-class background calls also follow the base URL, see [env-vars](https://code.claude.com/docs/en/env-vars), `ANTHROPIC_DEFAULT_HAIKU_MODEL`) are free to classify to the `claude` CLI tier. That spawns a nested `claude -p` process per side call. `PROXY_ENV_STRIP` (`backends.py:21`) keeps it from recursing *under shape A*. (INFERRED from code; not exercised.)

### Why it fails end-to-end (VERIFIED, E8)

A real run through an **isolated** kultivait (`HOME` copied from `~/.kultivait`, llama.cpp runtime, toll off, reusing the live llama-server on :8080, port 4973):
- The no-tools call was served by `Qwen3-4B-Q4_K_M` in 4.1 s.
- The main call got **llama-server HTTP 500: `Failed to parse tools: Missing tool type: {"name":"Agent",…}`**, then kultivait returned `502 [kultivait] dispatch failed on every tier`. Claude Code retried with backoff (13:20:36 → 13:23:33): **rc 1 after 178 s**, and **12 escalation files** archived for one prompt.

Root cause chain:
1. `/v1/messages` passes `body.get("tools")` straight into routing (`server.py` ~l.744). Anthropic tools are `{name, description, input_schema}`.
2. The local backends put them into OpenAI-format payloads untranslated: `LlamaCppBackend` `payload["tools"] = tools` (`backends.py:250`), `OllamaBackend` the same (`backends.py:138`).
3. The converter already exists (`api_backends.py:71–86`, Anthropic → OpenAI `{type: function, function: {name, description, parameters}}`), but only the cloud API backends call it.
4. No test catches it: every `/v1/messages` + Anthropic-tools test (`tests/test_server.py` ~l.1054, 1070) runs against a FakeBackend (`"openrouter"`) that accepts any shape.

- **llama.cpp: VERIFIED hard 500** (exact string above).
- **ollama: UNTESTED.** Ollama was down (never-both-up, `runtimes.py:4`). Whether it returns 400, accepts, or **silently drops** the malformed tools is unknown. A silent drop would be worse than a 500, because the model would answer without tools and Claude Code would see prose where it expected `tool_use`. Test shape T5 below settles it.

Relation to #208: that gate drove `/v1/chat/completions` with OpenAI-format tools, and its tool rows were excluded (R12). The Anthropic `/v1/messages` + local-tools path had never run against a real runtime.

### Auth / credential notes (docs, VERIFIED unless marked)

- `ANTHROPIC_API_KEY` **overrides a subscription login**: always in `-p`, after a one-time approval prompt in interactive mode ([settings](https://code.claude.com/docs/en/settings), [env-vars](https://code.claude.com/docs/en/env-vars)). `kultivait run` setting a dummy key therefore moves a subscription user onto API-key auth. That's harmless while kultivait never forwards upstream; it breaks any future passthrough.
- With `ANTHROPIC_BASE_URL` set and **no** key, the subscription OAuth credential stays active and its traffic goes to the base URL. A passthrough would have to forward the OAuth `anthropic-beta` capability or Anthropic returns 401 ([llm-gateway](https://code.claude.com/docs/en/llm-gateway)). The exact OAuth header on the wire is INFERRED.
- Gateways must stream without buffering and forward `anthropic-version`/`anthropic-beta` verbatim ([llm-gateway-protocol](https://code.claude.com/docs/en/llm-gateway-protocol)). Today kultivait terminates the request and re-emits its own SSE, so nothing is forwarded, which is consistent with E3.
- If a corporate `HTTPS_PROXY` is inherited, `kultivait run` should add `127.0.0.1` to `NO_PROXY` so base-URL traffic doesn't hairpin through it ([corporate-proxy](https://code.claude.com/docs/en/corporate-proxy)). INFERRED as a kultivait change.

---

## Shape B — transparent loopback (`hook loopback`)

### Structural blocker (VERIFIED)

- **E4:** the generated pf rule redirects `127.0.0.1:443 → 127.0.0.1:<serve port>`. `kultivait serve` is plaintext uvicorn (`cli.py:647`, `uvicorn.run(app, host=…, port=…, log_level=…)`, no `ssl_*` args). A TLS ClientHello to it fails the handshake (curl rc 35). The guide's `[tls] cert = …` / `[tls] key = …` keys (`loopback.py:64–66`) are read nowhere. `grep -rni 'tls\|ssl_certfile' src/kultivait/*.py` is empty.
- The pf output is an anchor file with no instructions for loading it (`rdr-anchor "kultivait"` + `load anchor …` in `pf.conf`, then `pfctl -ef`). Uninstall mentions `pf.anchors`, setup doesn't.

### Not blockers (VERIFIED unless marked)

- **Trust store:** Claude Code's default is `CLAUDE_CODE_CERT_STORE=bundled,system`, so the native binary honours the macOS keychain ([corporate-proxy](https://code.claude.com/docs/en/corporate-proxy)). The string `CLAUDE_CODE_CERT_STORE` is present in the local binary. **E6** confirms trust is redirectable without root: an untrusted self-signed cert gives `Self-signed certificate detected`, rc 1; the same cert via `NODE_EXTRA_CA_CERTS` gives rc 0. No pinning against a custom CA; TLS inspection is documented as supported.
- **SAN:** the leaf must carry `api.anthropic.com` for hostname validation under a hosts redirect. INFERRED from standard Bun TLS; the generated `openssl` line already adds those SANs.

### Consequences once TLS exists (INFERRED from code + docs)

- **Self-recursion.** Under a hosts redirect, the proxy's own `claude -p` CLI backend resolves `api.anthropic.com` to 127.0.0.1 and loops into kultivait. `PROXY_ENV_STRIP` strips env vars only and can't help against DNS. Same for any cloud API backend that dials `api.anthropic.com`/`api.openai.com`. Shape B needs an upstream bypass: pinned upstream IPs, a `NO_HOSTS` resolver, or an egress on a non-redirected route.
- **Over-capture.** `api.anthropic.com` also carries Claude Code's WebFetch domain-safety preflight, feature flags, and telemetry ([corporate-proxy](https://code.claude.com/docs/en/corporate-proxy) network table). kultivait's two routes would 404 them. Mitigate with `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` / `skipWebFetchPreflight`, which are env vars, and that erodes the "transparent" premise.
- **Scope.** A hosts entry intercepts *every* process on the machine, including tools that expect genuine Anthropic responses (SDK scripts, other agents). Combined with the E5 uninstall defect, the failure mode lingers.

---

## Candidate test shapes

| # | Shape | Root? | Status | What it proves |
|---|---|---|---|---|
| T1 | **Wrapper contract**: `kultivait run --port P -- env` / `sh -c 'exit 7'` / missing binary | no | ran (E1) | env injection, key setdefault, rc propagation. Cheap pytest: `subprocess` + `env`. |
| T2 | **Recording stub upstream** (`experiments/claude_socket/stub_upstream.py`) + `kultivait run -- claude -p` under a throwaway `HOME`/cwd | no | ran (E2) | Claude Code's real paths/headers/body shape; route-surface sufficiency. Re-run per Claude Code release, since the beta list and tool count drift. |
| T3 | **Captured-fixture replay** (`experiments/claude_socket/e3_replay.py`) into `create_app` with FakeBackends | no | ran (E3) | routing, `tools_unsupported` fallback, escalation archiving, SSE framing on genuine Claude Code bodies. Promote the captured body (scrubbed) to a `tests/fixtures/` file. |
| T4 | **Real E2E through an isolated-HOME proxy** (copy config + centroids; toll off; reuse the running runtime) | no | ran (E8) → **FAIL** | the only shape that exercises runtime tool-schema acceptance. Must become the regression test for the E8 fix. |
| T5 | **Tool-format contract test per local backend**: `/v1/messages` with Anthropic-format tools → assert the backend payload holds OpenAI `{type: function, function: {parameters}}`. Plus one live call against an **ollama**-runtime instance | no | **not run** (ollama down) | closes the ollama UNTESTED item; the unit half can run in CI with `httpx` mocked (`tests/test_backends.py` pattern) |
| T6 | **TLS trust redirect**: TLS stub + `ANTHROPIC_BASE_URL=https://127.0.0.1:P`, untrusted vs `NODE_EXTRA_CA_CERTS` | no | ran (E6) | Claude Code's trust behaviour; no pinning to a custom CA |
| T7 | **TLS-to-plaintext probe**: `curl https://127.0.0.1:<serve port>` | no | ran (E4) | shape B's missing TLS terminator (flip to a pass test once `serve` grows TLS) |
| T8 | **Generate→uninstall round-trip on a scratch hosts file** | no | ran (E5) → **FAIL** | the uninstall hazard; should be a pytest today |
| T9 | **Full shape-B E2E**: hosts + pf anchor load + System-keychain trust + SAN check against `api.anthropic.com` + recursion check (CLI backend must not loop) | **yes** | not runnable here | the only honest venue is a **disposable macOS CI runner** (GitHub-hosted macOS runners have passwordless sudo) or a throwaway VM, torn down after. Never the dev Mac. |

## Ticket candidates (not filed — route via agy-gh if wanted)

1. **bug (hazard): `hook loopback --generate-uninstall` leaves the redirect entries in `/etc/hosts`.** Range-delete fix + a round-trip test (T8).
2. **bug: `/v1/messages` sends Anthropic-format tools untranslated to local runtimes** (llama.cpp 500 → 502 after ~3 min of client retries). Reuse `api_backends.py:71–86` at the local-backend boundary; regression = T4/T5.
3. **decision (grilling-shaped): what should `kultivait run -- claude` do with Claude Code's tool-bearing main loop?** Today it's always served locally (Opus → local model), and each frontier-classified turn archives a growing escalation. Options: an explicit local-agent mode flag, a passthrough-to-Anthropic tier for tool-bearing Claude Code traffic (needs header/OAuth forwarding), or document it as the intended behaviour.
4. **chore: `hook loopback` output is aspirational.** Either implement TLS on `serve` (uvicorn `ssl_certfile`/`ssl_keyfile` + the `[tls]` config it already documents), the pf anchor load steps, and an upstream-bypass for recursion, or label the command experimental and stop printing instructions for config that doesn't exist.
5. **small: `kultivait run` should set `NO_PROXY` to include 127.0.0.1** when it injects the base URL.

## Evidence trail

- Harnesses: `experiments/claude_socket/stub_upstream.py` (records paths/headers/body summaries, redacts auth headers; `--tls CERT KEY` for T6), `experiments/claude_socket/e3_replay.py`.
- E2 captured request summary (redacted): two `POST /v1/messages?beta=true`, 4,078 B and 100,115 B, plus `HEAD /api/hello`. 24 tools: Agent, Bash, CronCreate, CronDelete, CronList, DesignSync, Edit, EnterWorktree, ExitWorktree, ListAgents, Monitor, NotebookEdit, PushNotification, Read, ReportFindings, ScheduleWakeup, SendMessage, Skill, TaskOutput, TaskStop, WebFetch, WebSearch, Workflow, Write.
- E8: isolated ledger row `{tier: Qwen3-4B-Q4_K_M, tokens_in: 761, tokens_out: 158, latency_s: 4.122}` for the side call. 12 escalations 13:20:36–13:23:33. llama-server error string quoted above.
- Docs: [llm-gateway](https://code.claude.com/docs/en/llm-gateway), [llm-gateway-protocol](https://code.claude.com/docs/en/llm-gateway-protocol), [llm-gateway-connect](https://code.claude.com/docs/en/llm-gateway-connect), [corporate-proxy](https://code.claude.com/docs/en/corporate-proxy), [env-vars](https://code.claude.com/docs/en/env-vars), [settings](https://code.claude.com/docs/en/settings). Fetched 2026-09-11.

### Still open

- Ollama's response to untranslated Anthropic tools (T5).
- SAN/hostname validation and keychain trust on the live hosts path (T9, root).
- Whether the Sentry/statsig strings present in the Claude Code binary are live egress (undocumented; only Datadog is documented).
- The exact OAuth header a subscription user's traffic carries to a custom base URL.
