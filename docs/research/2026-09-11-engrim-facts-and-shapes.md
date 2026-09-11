# engrim — facts and candidate integration shapes

Ticket: [#206](https://github.com/Standard-Pentest/kultivait/issues/206) · Branch: `research/engrim-facts`
Date: 2026-09-11 · Facts only — the go/no-go decision belongs to a separate grilling ticket.
Method: primary sources only — PyPI JSON API (`pypi.org/pypi/engrim/json`), the GitHub API for `timgordontg/engrim`, and a direct read of the locally installed wheel (engrim 1.4.1 under the uv cache, `~/.cache/uv/archive-v0/B1ja1czaCVxkA6t5/`), cross-checked against `uvx engrim --help` subcommand help. Kultivait-side claims cite this repo's source. Every fact carries a register label: **VERIFIED** (source read/cited), **INFERRED** (from source structure or README claims), **UNVERIFIED** (flagged, not guessed).

---

## (a) VERIFIED-FACTS REGISTER — engrim

### A1. Identity, license, packaging

VERIFIED — PyPI JSON API + wheel `engrim-1.4.1.dist-info/METADATA` + GitHub API `repos/timgordontg/engrim`, all retrieved 2026-09-11.

| Field | Value | Source |
|---|---|---|
| Package | `engrim` on PyPI, current version **1.4.1** | PyPI JSON |
| Summary | "Project-scoped, cross-session episodic memory for AI coding agents (Google Antigravity, Claude Code, Cursor MCP) — local SQLite hybrid keyword+semantic store" | PyPI JSON |
| License | **MIT** (PyPI `License:` field, `License :: OSI Approved :: MIT License` classifier, `LICENSE` file shipped in wheel, GitHub API `license.spdx_id: MIT` — all four agree) | PyPI + wheel + GitHub API |
| Author | Tim Gordon (`timgordontg`) | PyPI JSON |
| Repo | `github.com/timgordontg/engrim` — created 2026-06-19, last pushed 2026-09-11, not archived | GitHub API |
| Repo signals | 225 stars, 15 forks, **GitHub issues disabled** (`has_issues: false`; the 5 `open_issues` are PRs) | GitHub API |
| Python | `Requires-Python >=3.10`; pure-Python wheel (`py3-none-any`), 65,484 B (sdist 101,993 B) | PyPI JSON |
| Packaging | Single console script `engrim = engrim.cli:main`; CLI is stdlib **argparse** (not click/typer); storage is stdlib **sqlite3** (FTS5) | wheel `entry_points.txt` + `cli.py` + `--help` |
| Status classifier | `Development Status :: 4 - Beta` — still Beta at 1.4.1 | wheel METADATA |

### A2. Release cadence and versioning

VERIFIED — PyPI JSON release upload timestamps, retrieved 2026-09-11. 17 releases, 18 git tags; GitHub releases mirror PyPI 1:1.

| Burst | Releases | Window | Notes |
|---|---|---|---|
| Jun 2026 (birth) | 0.7.0 → 1.1.0 (8 releases) | 2026-06-22 → 06-24 (3 days) | first public 0.7.0 on 06-23; 1.0.0 two days later |
| Aug 2026 | 1.1.1 → 1.2.2 (5 releases) | 2026-08-11 → 08-12 (2 days) | 10-week gap before it |
| Sep 2026 (current) | 1.3.0 → 1.4.1 (5 releases) | 2026-09-07 → 09-10 (4 days) | 1.4.1 uploaded 2026-09-10T21:37Z |

Cadence pattern: **bursty single-maintainer shipping** — several releases per day inside a burst, then weeks quiet. SemVer-ish 0.x→1.x progression; no deprecation policy stated anywhere in the wheel or README.

### A3. Python API surface

VERIFIED — direct read of installed 1.4.1 source.

- The **declared import API is one symbol**: `engrim/__init__.py` contains only `__version__ = "1.4.1"` and a docstring. No `__all__`, no re-exports.
- The real product surfaces are the **CLI** (25 subcommands: `add, recall, list, context, hook, supersede, retire, setup, uninstall, import, sync, merge, backup, log, assist, statusline, embed, logs, review, prune, project, projects, stats, mcp, serve`) and a **stdio MCP server** (`engrim mcp`; tools `engrim_recall`, `engrim_context`, `engrim_add`, `engrim_review` — read from `mcp_server.py`).
- Importable-but-**undeclared** internals exist: `engrim.cli.connect(db)` (open/init the store), `engrim.cli.add_memory(conn, *, project, type, summary, detail, status, tags, links, source, origin_agent)` (the shared write core behind both CLI and MCP). Functional, but private by every packaging signal.
- Record model (VERIFIED, `cli.py:46` + `add --help`): `TYPES = ("decision", "fact", "feedback", "state", "reference", "user")`, plus tags, links, `--source`, `--origin-agent` provenance (antigravity/claude-code/cursor/cli/user), `status`, and a supersede/retire lifecycle. Project tag precedence: `--project` > `$ENGRIM_PROJECT` > git root of cwd > cwd. Store: one SQLite file (default `~/.engrim/memory.db`, `$ENGRIM_DB` overrides).

### A4. Dependency footprint

VERIFIED — wheel METADATA `Requires-Dist` + listing of the local uv environment the wheel actually resolved into.

| Layer | Packages |
|---|---|
| **Declared direct deps** | **`model2vec>=0.3` — the only one** |
| Observed transitive chain (macOS, py3.14) | numpy, safetensors, tokenizers, huggingface-hub, hf-xet, filelock, fsspec, tqdm, packaging, pyyaml, typing-extensions (model2vec's chain); plus click, joblib, cloudpickle, jinja2, markupsafe, httpx/anyio/httpcore/certifi/idna/h11 |
| Runtime network behavior | Semantic recall downloads `minishlab/potion-base-8M` from the **Hugging Face Hub on first embed**; `ENGRIM_EMBED=off` forces pure-lexical; any embedder load failure degrades to `(None, None)` silently — "never a hard error" (`cli.py` `_resolve_embedder`, lines 568–594). Auto-embed on write is best-effort and can't fail a write (`add_memory` docstring). |

Note for kultivait's local-first posture: the package itself is local-only (no cloud calls in normal operation), but the first semantic-embed makes one outbound HF Hub fetch unless `ENGRIM_EMBED=off`. Lexical FTS5 mode needs no model at all. Whether a one-time model fetch conflicts with the launch checklist's no-telemetry/local claims is a grilling question, not a fact.

### A5. Maintenance signals

VERIFIED — GitHub API + commit log, retrieved 2026-09-11.

- **Bus factor ≈ 1**: contributors are `timgordontg` (45 commits), `mwpastore` (5), `emsilva` (2).
- **Alive and fast right now**: last push 2026-09-11 (today); commits land same-day as PyPI uploads (e.g. `chore: bump version to 1.4.1 & enrich MCP tool definition schemas` 2026-09-10T21:36Z vs PyPI 21:37Z).
- CI badge for `ci.yml` in README; a `glama.json` MCP-server manifest was added 2026-09-10; recent commit references "gh-aw" (GitHub Agentic Workflows) — the project uses automation agents on itself.
- Issues are **disabled** upstream (same posture as kultivait's fork policy); contribution surface is PRs only.
- README carries promotional self-measurement ("105-session case study", "99%+ cut in reloaded context cost") — INFERRED: vendor claims, independently unverified.

### A6. Agent-environment wiring (the overlap-relevant surface)

VERIFIED — `engrim setup --help`, `engrim hook --help`, and README text shipped in the wheel METADATA.

- `setup --claude` wires **`SessionStart`, `Stop`, `SessionEnd`, `UserPromptSubmit`** hooks into **`~/.claude/settings.json`** (user-level) plus CLAUDE.md; `--agy`, `--codex`, `--cursor` variants exist for other hosts. Strict mode configures the Stop hook to **exit 2** when uncaptured decisions are detected (blocks stop/clear).
- `hook --event {boot,stop,sessionstart}` is the injection core: on SessionStart it mirrors file-memory, then emits a **budget-bounded context pack** (assist default 600 chars ≈ 150 tokens; README markets the pack at < 4,000 chars / ≈ 1,000 tokens — INFERRED, vendor figure).
- `prune` in engrim = **purge old transcript logs + VACUUM the store** (opt-in retention). Name collision with `kultivait prune` (= distill a transcript into a handoff brief) with **opposite semantics**.

---

## (b) Feature-by-feature overlap vs kultivait

Kultivait-side citations: brief write/rotate/inject `src/kultivait/ambient.py:161-207` (`KEEP_BRIEFS = 20`, `latest.json` manifest, SessionStart stdout block), compost-first distill `src/kultivait/gates.py:43-68`, manual prune `src/kultivait/cli.py:760-769`, compost dir `src/kultivait/cli.py:54`, hook install (project `.claude/settings.json`, SubagentStop/PreCompact/SessionStart) `src/kultivait/ambient.py:21-34`.

| Dimension | kultivait | engrim | Overlap verdict |
|---|---|---|---|
| Cross-session continuity | **Handoff brief** — LLM-distilled FINDINGS/DECISIONS/CONSTRAINTS/OPEN QUESTIONS, injected at SessionStart via project-level hooks | **Memory pack** — curated typed records, injected at SessionStart via user-level `~/.claude/settings.json` hooks | **Same slot, different artifact.** Both inject at SessionStart; different settings files so both can be installed at once → potential double injection (token cost, and two narratives of "what happened") |
| Capture vocabulary | Brief sections: FINDINGS / DECISIONS / CONSTRAINTS / OPEN QUESTIONS (`gates.py` DISTILL_PROMPT) | Record types: decision / fact / feedback / state / reference / user, + tags/links/provenance | **Natural mapping, lossy in both directions**: DECISIONS→decision, FINDINGS→fact, CONSTRAINTS→fact, OPEN QUESTIONS→state. Brief is derived/lossy; engrim records are meant to be authoritative/curated |
| Lifecycle | Brief rotation: newest 20 kept, `latest.json` points at current; older briefs deleted (`ambient.py:19,194`) | Records persist indefinitely; `supersede`/`retire` mark done/stale rather than delete; `recall` can include-stale | **Complementary — engrim outlives the rotation.** The known "briefs vanish after 20" loss is exactly what an engrim store retains |
| Raw transcripts | **Compost**: full transcripts archived to `~/.kultivait/compost/<id>.txt` before distillation (durability boundary) | None comparable — `log`/`logs` are bounded recent-turn scans for assist/review, not a full-transcript archive | **No overlap.** Engrim is not a compost replacement; its records are curated summaries by design |
| "prune" | `kultivait prune` = distill transcript → handoff brief (`cli.py:1474`) | `engrim prune` = delete old logs + VACUUM | **Name collision, opposite semantics** — a docs hazard if both are recommended together |
| Distillation engine | LLM distillation (Gate + prompt template, phase map from `.kultivait/gates.toml`) | None — capture is agent/human-authored `add` or the `review` scan prompting the agent to capture | **Complementary.** Engrim has no transcript→brief distiller; kultivait has no durable store. Neither does the other's job |
| Retrieval | None beyond latest-brief injection and `gates briefs` listing | Hybrid FTS5-bm25 + model2vec vectors with RRF; `recall`/`context`/MCP tools | Complementary — engrim gives brief-derived content *searchability* it lacks as flat files |
| Routing / savings / tollbooth | Core product | Absent | **Zero overlap** — engrim stores memory, kultivait routes models |

**Bottom line of the map**: one genuine collision (SessionStart injection slot; cosmetic `prune` name clash), and otherwise the feature sets are complementary rather than competing.

---

## (c) Candidate "kultivait uses engrim" shapes

Costs/benefits are one-liners; none is a verdict. **"None" stays live** in every row's shadow: everything kultivait needs its briefs do today, with zero new dependencies.

### (i) Agent-facing outputs written into an engrim store
At brief-write time (`write_brief` / `cmd_prune` success path), best-effort emit the distilled sections as typed engrim records (`DECISIONS`→decision, `CONSTRAINTS`→fact, `OPEN QUESTIONS`→state) with `--source` pointing at the brief path + compost id.
- **Cost**: one opt-in subprocess per gate fire (must stay inside the never-block rule: failures swallowed into `gates.log`); engrim becomes a detected optional dep, not a requirement.
- **Benefit**: brief content survives the 20-brief rotation and becomes hybrid-searchable; any other agent on the project (Cursor, Antigravity, Codex — engrim's other hosts) picks up kultivait-derived context for free.

### (ii) Docs/quickstart recommending engrim as the companion memory layer
Zero code: document `engrim setup --claude` alongside `kultivait gates install --claude`, with two mandatory notes — the SessionStart double-injection interaction, and the `prune` name-collision disambiguation.
- **Cost**: claim-verification burden on every engrim release (bursty beta churn means docs rot fast); engrim's GitHub has issues disabled, so upstreaming corrections is PR-only.
- **Benefit**: answers the natural next question ("where does brief knowledge live after rotation?") with zero coupling; MIT license poses no docs obstacle.

### (iii) Programmatic runtime dependency
Import `engrim.cli.connect` / `engrim.cli.add_memory` instead of shelling out.
- **Cost**: the API is **undeclared** (only `__version__` is exported) and the project shipped 5 releases in 5 days this month — private-module coupling into a fast beta; plus the transitive chain (numpy/tokenizers/HF hub) lands in kultivait's dependency footprint, against its stdlib-leaning grain.
- **Benefit**: single-process write, no subprocess latency on the gate path. **Weakest shape on current facts** — nothing in engrim invites programmatic consumers.

### (iv) MCP co-presence (surfaced during research)
Engrim already ships a stdio MCP server (`engrim mcp`; bare non-tty invocation defaults to it as of 1.4.1). Shape: kultivait docs/config register `engrim mcp` for the user's agent client, so *agents* write/read memory via `engrim_add`/`engrim_recall` tools rather than kultivait writing for them; kultivait's briefs remain the distilled artifact, engrim the agent-owned ledger (`review --strict` can gate capture).
- **Cost**: none in kultivait code beyond a docs snippet; division of labor must be written down.
- **Benefit**: clean ownership split — kultivait distills boundaries, the agent curates durable facts — with no library coupling at all.

### (v) SessionStart arbitration (surfaced during research)
If both engrim and kultivait gates are wired, two packs inject at SessionStart (engrim from user-level settings, kultivait from project-level). Shape: document precedence, or add a kultivait flag to skip its brief block when an engrim pack is present.
- **Cost**: one flag + a docs paragraph.
- **Benefit**: avoids the token double-charge and the two-conflicting-narratives failure mode; relevant under shapes (i)/(ii)/(iv) alike.

### (vi) None
Everything briefs do today — distill, compost, inject latest, rotate — works with zero external packages. Any engrim shape must beat "free, already shipped."

---

## Open questions for the deciding grilling session

1. **Writer of record**: briefs are machine-distilled and lossy; engrim records are meant to be curated and authoritative. Does shape (i) pollute an engrim store with derived artifacts (and does 20-briefs-per-project noise dilute hybrid recall across projects)?
2. **Injection budget**: with both wired, what does SessionStart actually cost in tokens (kultivait brief + engrim pack), and which narrative wins when they disagree?
3. **Local-first posture**: is engrim's one-time HF Hub model fetch (semantic mode) acceptable, or is `ENGRIM_EMBED=off` lexical-only the only admissible mode? Does the launch checklist's no-telemetry claim need a carve-out sentence either way?
4. **Opt-in vs default-on**: which shapes, if any, ship on by default in `kultivait gates install`, and how is "engrim present" detected without becoming a hard dep?
5. **Churn tolerance**: bursty single-maintainer beta — is docs-only (ii)/(iv) the maximum safe exposure, with (i) gated behind opt-in and (iii) off the table until engrim declares a stable import API?
6. **"None"**: what brief/store failure actually justifies revisiting — is there a live pain (brief rotation loss, cross-agent context) with incident reports, or is this speculative integration?

## UNVERIFIED register (flagged, not guessed)

- **potion-base-8M download size / offline-after-first-fetch behavior** — the code path is verified (`cli.py:568-594`), the model artifact size and re-fetch policy were not measured here.
- **README performance claims** (105-session study, 99% context-cost cut, <1,000-token packs) — vendor self-measurement, INFERRED only.
- **Whether `add_memory`/`connect` are intended as public API** — no statement found in wheel, README, or release notes; absence of evidence, not evidence of prohibition.
- **Windows/Linux behavior** — release notes for 1.2.1 claim all three OSes; only macOS observed here.
- **Decomposition of the 5 `open_issues`** into PRs vs something else — GitHub reports `has_issues: false`, so they should all be PRs; not itemized.
