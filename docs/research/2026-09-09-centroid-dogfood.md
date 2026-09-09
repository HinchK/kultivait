# Learned-centroids herd dogfood — verdict & evidence

Ticket: [#181](https://github.com/Standard-Pentest/kultivait/issues/181) · map: [#176](https://github.com/Standard-Pentest/kultivait/issues/176)
Date: 2026-09-09 · Mode: **shadow-only** per #180's disposition (candidate failed the accuracy floor; no cutover).

**Verdict: PASS (shadow-only) — the recalibration loop is live end-to-end; no cutover, correctly.**

## What ran

1. `kultivait centroids learn` against the **live harvest** → `learned-v1` in the real
   `~/.kultivait/centroids.json`. Signal counts by trust class (the honest census):
   gold **0** (still no answered tolls), escalations **20** (17 architect + 3 docs),
   silver **14** (3 simple + 4 reasoning + 7 architect) — only **architect** cleared the
   10-signal minimum; every other role retained its seed prior, provenance-recorded.
2. `[centroids].shadow_version = "learned-v1"` set; the live herd proxy restarted onto
   current code (the pre-fix process predated the shadow hook entirely).
3. **Real dispatches observed**: five prompts through the proxy on :4114 (garden routing:
   qwen3.5:4b / claude / one contested thin-margin escalate). The shadow candidate
   dual-classified each — agreements silently pass (by design), and a contested
   thin-margin dispatch (incumbent `qwen3:14b` @ 0.008, escalated) produced a live
   `kind: "centroid"` disagreement row: candidate said `claude` @ 0.016 — consistent with
   the eval's cloud-ward-pull analysis. Shadow observation continues automatically on all
   herd traffic.
4. **Rollback drill**: `cutover --version learned-v1 --yes` then `cutover --version
   seeds-v0 --yes` — both flips verified in the seat; since cutovers take effect at next
   boot and no boot occurred between flips, **live routing never served learned
   centroids**. End state: `active=seeds-v0`, `shadow=learned-v1`.

## A real bug found by dogfooding (fixed, regression-pinned)

The first shadow session logged **zero** centroid rows on real traffic. Surfacing the
swallowed exception revealed a classic eager-default bug:
`vectors.get(role, seed_mean(role, embed_batch))` evaluates the fallback *unconditionally*,
so the serve path (which passes `embed_batch=None` — vectors come from the table, no
embedding needed) crashed silently inside the never-raise guard. Fixed with an explicit
membership check; regression test drives `router_for_version` with `embed_batch=None` on a
complete table. Suite: **763 passed, 2 skipped**. Exactly what dogfooding is for.

## Friction notes (honest)

- Gold remains empty: the herd answers almost no tolls (auto-policy handles contested
  traffic). Learned centroids will stay seed-heavy until toll answers or richer silver
  accumulate under the 512-char cap.
- One flaky dispatch (120 s timeout on a reasoning prompt) mid-session — pre-existing
  behavior, unrelated; noted for the record.
- The disagreement volume is thin (1 row across 6 dispatches) — expected, given 3 of 4
  roles are pure seed prior; volume grows with traffic.

## End state

`learned-v1` shadows all herd traffic; `active=seeds-v0`; the next `centroids learn` (with
more silver under the 512-char cap) produces `learned-v2` and re-enters the eval gate.
