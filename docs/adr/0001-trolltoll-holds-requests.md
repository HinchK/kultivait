# Trolltoll holds requests open

When a routing decision is contested, kultivait holds the caller's HTTP request open for up to `toll_timeout_s` (default 60s) while a human answers the trolltoll — rather than responding immediately with auto-policy and offering an out-of-band veto. We chose this despite HANDOFF.md:107-113 having explicitly rejected in-band intervention, because that rejection was about advice-*as-prose* breaking agent loops (a turn expects `content` or `tool_calls`; "go use Claude" derails it), not about latency: a held request that eventually returns real content keeps the agent loop intact, and holding is the only shape where the human's choice actually steers the turn.

## Considered Options

- **Respond immediately, veto after** (escalation-style, HANDOFF's earlier recommendation): rejected as the primary mechanism because the frontier dispatch has already been paid for by the time a human vetoes.
- **Never hold, menu purely out-of-band**: kept as the *headless arm* of the hybrid — presence-gated (serve TTY or a `kultivait choose` heartbeat within ~5 min); with no reachable human the request is never taxed with a dead 60s wait, auto-policy runs, and the menu is archived.

## Consequences

- Server architecture must support in-flight requests parked on a pending-tolls queue with two faces (serve's TTY tollbooth, `kultivait choose`), timeout drain to auto-policy, and late answers recorded as ledger counterfactuals only — never re-opening a dispatched request.
- The hold must stay under typical client HTTP timeouts; 60s is the tuned default, not a law.
- Unambiguous requests are never held (contested+boundaries trigger only), so the interruption tax stays proportionate to the decision's actual stakes.
