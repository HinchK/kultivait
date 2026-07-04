# Copy Prompt button + start.md — Design

**Date:** 2026-07-03
**Status:** Approved (design discussion), pending spec review

## Purpose

Give landing-page visitors a one-click way to hand kultivait's onboarding to
their coding agent, mimicking the "Copy Prompt" pattern on flueframework.com.
Clicking the button copies a starter prompt to the clipboard; the prompt points
the agent at `https://www.kultivait.ai/start.md`, a doc written for AI agents
that walks the user through install and first routing.

Two deliverables:

1. A "Copy the starter prompt" CTA on `landing/index.html`, in two places.
2. A real `landing/start.md`, served at `kultivait.ai/start.md`, so the copied
   prompt works end-to-end.

## The prompt text

Copied verbatim to the clipboard:

> Read https://www.kultivait.ai/start.md and help me plant my first garden — routing my prompts to the cheapest model that can carry them.

Note: the prompt uses `www.kultivait.ai` (per user's wording) while the install
line uses bare `kultivait.ai`. Both must resolve to the same host; this is a
DNS/hosting concern, not a code change in this feature.

## Button design

A distinct primary CTA — visually separate from the small mono `copy` chip on
the install line. Styled in the page's existing palette and fonts:

- Copper accent (`--copper` border, `--copper-bright` on hover), mono label
  (`--mono`), consistent with existing focus-visible outline rules.
- Structure: a `<button class="prompt-copy">` containing a text icon (`⧉`,
  aria-hidden) plus a label `<span>`, followed by a subtitle line:
  *"paste it into your coding agent for a guided walkthrough"*.
- The full prompt lives in a `data-copy-prompt` attribute on the button.

### Placement (two instances)

1. **Hero:** directly below the existing `curl … | sh` install block
   (`div.install#install`), above the `.hero-note` line.
2. **Final CTA:** inside the `.final-cta` block near the bottom, below the
   second install block.

Both instances are identical in markup and behavior.

## Click behavior

New dedicated JS handler for `[data-copy-prompt]`. The existing `[data-copy]`
handler overwrites the button's entire `textContent`, which would destroy the
icon/label structure — it stays untouched and continues to serve the install
chips.

- **Success:** write prompt to clipboard via `navigator.clipboard.writeText`,
  swap the **label span only** to `✓ Copied — now paste into your agent`,
  revert to the original label after ~1.8 s.
- **Failure** (clipboard API unavailable/denied): label shows
  `Press ⌘C — prompt selected`; the prompt text is exposed in a
  visually-hidden-but-selectable element and range-selected so the user can
  copy manually.
- **Accessibility:** the label span has `aria-live="polite"` so the
  confirmation is announced; button is a real `<button type="button">` and
  inherits the page's `:focus-visible` styling.

## start.md content

File: `landing/start.md` (deployed alongside `index.html` and `install.sh`).
Audience: an AI coding agent reading it on the user's behalf. Grounded in
`README.md` — no invented commands or claims. Contents:

1. **One-line framing** — kultivait is a local-first LLM routing proxy; the
   greenest token is the one you never send.
2. **Install** — `curl -fsSL https://kultivait.ai/install.sh | sh`, with the
   `uv tool install` fallback from the README.
3. **Initialize** — `kultivait init` (surveys the machine, writes
   `~/.kultivait/config.toml`).
4. **Serve** — `kultivait serve` (OpenAI-compatible proxy on
   `http://localhost:4114`); point one tool at that endpoint.
5. **Verify** — `kultivait route "why does this test deadlock?"` to dry-run a
   classification.
6. **Harvest** — `kultivait harvest` to watch savings accrue in the ledger.
7. **Local-only note** — no cloud CLIs is a first-class mode; cloud-worthy
   prompts are served locally and `kultivait escalations --brief` produces a
   paste-ready brief.

Written as instructions to the agent ("guide the user through…"), short enough
to be cheap to ingest — target under ~120 lines.

## Out of scope

- DNS/hosting changes (www vs apex resolution).
- Restyling the existing install-chip copy buttons.
- Any server-side or analytics work.

## Testing

Manual verification in a browser (the page is a single static HTML file with
no build step or test harness):

- Click each button instance → clipboard contains the exact prompt; label
  swaps and reverts.
- Simulate clipboard failure (e.g. deny permission) → fallback selection path
  works.
- Keyboard: button reachable by Tab, activates on Enter/Space, focus ring
  visible.
- `start.md` renders as plain markdown and every command in it matches
  `README.md`.
