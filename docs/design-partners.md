# Design-Partner Guide

This guide outlines the kultivait design-partner trial, its hard privacy
invariants, outcome labeling workflows, and exit protocol.

## 1. The Design-Partner Program

The design-partner program is a 90-day rolling trial measured per partner from
their first routed dispatch, rather than synchronized across a cohort calendar.
Participation is subject to a hard cap of 10 partners ($N=10$) to preserve deep
collaboration and rapid iteration on routing quality.

### Cohort Profile & Selection
Partners are recruited from the initial-user profile via a short intake
application:
- **Hardware**: Apple Silicon Mac (M-series, 24 GB+ unified memory recommended).
- **Local Runtime**: Ollama active as the default local serving engine.
- **Client**: Daily driver of a coding agent harness (e.g., Claude Code, Aider, OpenCode, Codex).
- **Workload**: Active development in private repositories requiring local-first confidentiality.
- **Commitment**: Willingness to generate and share monthly scrubbed exports and participate in fortnightly asynchronous check-ins (with optional monthly 1:1 syncs).

Each partner's 90-day clock begins on the date of their first routed request
logged in their local ledger.

## 2. Privacy Invariants (The Non-Negotiables)

Kultivait's architecture is built so privacy is verified by code construction,
not legal agreements or policy promises.

### Pull-Only Export — Zero Telemetry
Data sharing is strictly **pull-only**:
- Running `kultivait report --export` writes a sanitized local JSON artifact to your machine that you inspect and send manually.
- **No transmit code path exists anywhere in the product**: there are no telemetry libraries, background daemons, upload endpoints, or network beacon calls.
- The public claim—"Nothing phones home"—remains literally true by software construction.

### Metadata-Only by Default
The exported records are **route outcome records** extending your local ledger:
- **Included metadata**: `policy_version`, candidate tiers, routing confidence, operator override flags, retry indicators, fallback reasons, wall-clock timing (`first_token_ms`, `latency_s`), cloud-egress decisions, and outcome labels.
- **Salted repository hashing**: Repositories are identified strictly by a salted per-install hash (`repo_hash`). Your filesystem paths, folder structures, and repository names are never recorded or exported.
- **Zero prompt or completion text**: Dispatches contain neither user input nor model completions by default.

### Snippet Retention & Secret-Shape Refusal
If you choose to opt in to prompt snippet collection for specific repositories:
- **Per-repo opt-in**: Retention must be explicitly enabled per repository; there is no blanket global toggle.
- **Secret-shape refusal**: A test-enforced invariant refuses and strips any text matching credential, key, or token patterns (API keys, private certificates, OAuth tokens, authorization headers). The redaction event itself is recorded in the ledger while the sensitive text is permanently dropped before storage.
- **Double opt-in export**: Snippets never leave your machine unless your export command explicitly specifies the separate `--include-snippets` flag.

### Policy-Controlled Cloud Egress
Cloud model routing is governed by local repository policy:
- **Ask-once-per-repo default**: The first time kultivait considers routing a request from a new repository to a frontier cloud model, it pauses and prompts you once (trolltoll style) to establish that repository's egress posture (`block`, `ask`, or `allow`).
- **Test-enforced blocking**: Opted-out repositories enforce an unconditional, test-enforced block—local requests never touch external frontier APIs regardless of prompt verdict or tool requirements. Secrets never egress.

## 3. Consented Outcome Labels

Design-partner evaluations assess routing accuracy through four explicit
labels recorded in the route outcome record:

| Label | Meaning | When to Apply |
|---|---|---|
| `accepted` | Route was correct | The assigned model answered well without manual intervention or redirection. |
| `retried` | Answer was unusable | You re-issued or retried the task because the assigned model gave an unusable, broken, or hallucinated answer (distinct from client network retries). |
| `escalated` | Explicit cloud upgrade | You manually bypassed the local route to demand a more capable frontier model. |
| `wrong_route` | Structural misroute | The router chose a local tier for a prompt that clearly required frontier reasoning, or vice versa. |

### Labeling Interfaces
You can label dispatches locally using any of three surfaces:
1. **CLI Batch Labeling**:
   ```bash
   kultivait label
   ```
   Interactively step through recent unlabeled dispatches from your terminal.
2. **Dashboard One-Key Shortcuts**:
   Open the local web UI (`kultivait dashboard`) and use single-key hotkeys on the live dispatch stream:
   `y` / `a` (accepted), `r` (retried), `e` (escalated), `w` (wrong route).
3. **Post-Toll Chooser Prompt**:
   When answering a tollbooth in `kultivait choose`, an optional one-line prompt appears after completion:
   `route right? [y/r/e/w]`

## 4. The Monthly Loop

Once a month, each design partner completes a simple reporting cycle:

### 1. What You Run
Generate a scrubbed local export file:
```bash
kultivait report --export
```
This writes a timestamped file (e.g., `~/.kultivait/reports/export-2026-10-01.json`). If you agreed to share scrubbed snippets for an opt-in repository, pass `--include-snippets`.

### 2. What You Send
Inspect the generated JSON file with any text viewer or `jq`. When satisfied, share the file with the kultivait team via your agreed private communication channel (email, private gist, or secure upload).

### 3. What We Compute
The project team aggregates the cohort metrics to evaluate progress against pre-registered success bars:
- **Billed Metered Cash**: Actual dollars billed by pay-per-token API providers.
- **Counterfactual Savings**: Dollars kept in pocket relative to season reference prices.
- **Observed Latency**: Empirical first-token and total wall-clock times.
- **Estimated Time**: Net signed minutes paid relative to frontier baseline tables.
- **Route Regret**: Computed strictly as:
  $$\text{Route Regret} = \frac{\text{wrong\_route labels}}{\text{all labeled dispatches}}$$
  The program operates under a pre-registered **$\le 10\%$ route regret ceiling**. Pinning the denominator to all labeled dispatches ensures the metric cannot be artificially gamed by labeling fewer dispatches.

## 5. Exit & Deletion Protocol

Participation is voluntary from start to finish:

- **Leave Anytime**: You may pause or exit the trial at any time without advance notice or penalty.
- **Rapid Custody Deletion**: Upon request, all exported data files you shared with the project are permanently purged from project storage within **14 days**.
- **Seat Rotation**: Inactive seats are rotated after **21 days of inactivity** (no dispatches or communication) to invite candidates from the waitlist.
- **Program Sunset Deletion**: All received partner exports across the cohort are permanently destroyed **90 days after the expansion memo publishes**.
- **Inspect Before Sharing**: Because exports are pull-only, you retain complete sovereignty over your data—you can inspect, redact, or withhold any export file before transmitting it.

## Related

- [ADR 0025: Design-Partner Consent and Egress Posture](adr/0025-design-partner-consent-and-egress-posture.md)
- [Setup Guide](guides/setup.md)
- [Context and Vocabulary](../CONTEXT.md)
