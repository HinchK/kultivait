# kultivait

An intelligent LLM routing layer: every prompt is weighed locally, routed to the cheapest model that can carry it, and tallied in a savings ledger.

## Language

**Trolltoll**:
The pause kultivait takes on a contested prompt, holding the request while offering the human a route choice (frontier targets or keep it local). Named for the interruption tax of trolling a human mid-turn.
_Avoid_: pause, toll gate, interrupt, waypoint

**Tollbooth**:
The chooser surface where a trolltoll is answered — rendered inline in serve's TTY or via `kultivait choose` draining the same pending queue.
_Avoid_: menu, prompt screen, router dialog

**Conversation fingerprint**:
The prefix identity (hash of system prompt + first user message) that groups stateless proxy requests into a conversation for sticky route choices.
_Avoid_: session id, client id

**Verdict**:
The routing decision derived structurally from judge fits: local below 0.65, frontier at or above 0.85, contested between (a trolltoll fires). Never asserted by the model itself.
_Avoid_: classification (that's the embedding router's output), judgment

**Preprocessor**:
The gated local-model pass that analyzes, rewrites, and judges a prompt before routing. Skipped when the embedding margin is fat; run where routing is contested.
_Avoid_: gate, filter, classifier (that's the embedding router)

**Escalation**:
An archived, cloud-worthy prompt that was served locally anyway, distillable into a paste-ready brief. Predates the trolltoll; unrelated to it.
_Avoid_: trolltoll (they are different mechanisms)

**Re-fit**:
The per-boundary re-weighing of model + effort for the next sub-task in a conversation fingerprint.
_Avoid_: re-route, re-classify (that's the embedding router's output)

**Sub-task candidates**:
The decomposition a preprocessor emits for compound non-tool prompts, returned in-band as structured metadata for the client's agent loop. Suppressed on tool-bearing requests — agent harnesses plan their own work.
_Avoid_: plan, task list

**Route menu**:
The ranked set of choices a tollbooth presents — top three installed frontier targets by judge fit with fitted effort, plus keep-it-local as the anchor.
_Avoid_: model picker, target list

**Auto-policy**:
The verdict-default dispatch taken when a trolltoll expires unanswered — local when the local tier can serve, else the top-ranked frontier target; the missed menu archives escalation-style.
_Avoid_: fallback (that's _resolve_tier's silent downgrade), default route

**Frontier provider**:
A pay-per-token REST source of frontier models — direct (Anthropic, OpenAI) or aggregated (OpenRouter) — registered by hand as a serving target pinned to one exact model id; registered is not served, serving also requires a resolvable key.
_Avoid_: cloud provider, vendor, API target

**Dialect**:
The wire grammar an endpoint speaks — chat-completions or messages. Clients arrive in either dialect; a frontier provider serves one (OpenRouter serves both), so the proxy translates at the seam.
_Avoid_: format, protocol, schema

**Metered cost**:
The cash a dispatch actually bills — real spend from a pay-per-token frontier provider; subscription and local dispatches carry none.
_Avoid_: actual cost, real cost, spend (unqualified)

**Notional cost**:
The value a dispatch represents at its target's own pay-per-token prices — what the same tokens would have cost metered. The lens savings are measured in.
_Avoid_: estimated cost (that's the tollbooth's pre-dispatch figure), virtual cost

**Reference price**:
The single declared per-token price the whole season's baseline is struck at — flat by default, pinnable to one exact model. The stable yardstick kept-in-pocket is measured against.
_Avoid_: baseline price (that's the computed season total), list price

**Capability filter**:
The route-menu rule that candidacy requires being able to execute the request as sent — tool-bearing requests drop targets that cannot take tools, so the menu may shrink below three options rather than offer broken choices.
_Avoid_: tool filter, eligibility check, tool gate

**Effort projection**:
The mapping of a canonical effort level (fast/balanced/deep) onto a target's native mechanism — CLI flags or API wire fields. Canonical is the shared currency; projection is owned by the target's backend and may diverge per provider.
_Avoid_: effort mapping, effort flags (that's one CLI mechanism), reasoning config

**Capability eval**:
The harness that dispatches identical tool-loop tasks directly to backends — bypassing routing — and scores them by a cross-family model judge, accuracy only. Measures what each target can do; savings stay the harvest's lane.
_Avoid_: dogfooding benchmark (that's the harvest), router benchmark, accuracy-vs-savings harness

**Presence probe**:
The live authenticated check a route menu runs per provider at build time to confirm a target's key works right now; a failed probe drops the target from the menu, not from serving.
_Avoid_: health check, validation (no state is stored), key check

**Buffered relay**:
The dispatch posture where the proxy buffers a provider's full stream before relaying it — client streaming survives, but failures surface clean and pre-stream, never as truncated content.
_Avoid_: passthrough streaming, store-and-forward, mid-stream errors

**Distillate**:
A fine-tuned generation of a local model, produced by the distillation pipeline from harvested routing data and named so the herd can tell generations and bases apart in the ledger.
_Avoid_: fine-tune (that's the process), adapter, custom model

**Anchor set**:
The real harvested prompts that seed synthetic corpus generation — while every real verdict-bearing case stays permanently held out as the eval set, never trained on.
_Avoid_: seed set, eval set (that's the held-out half), training data

**Resource ladder**:
The fixed escalation order a training run climbs when it presses the hardware envelope — batch down, adapted layers down, gradient checkpointing, wired-limit raise — aborting rather than swapping if still over.
_Avoid_: fallback config, memory tuning, degradation path

**Band discipline**:
The two-sided guard on a judge's contested band — gold-contested cases must land in it (floor), the full set must not flood it (ceiling) — so toll-rate wins can't be gamed by dodging the band.
_Avoid_: calibration check, toll guard, band population (that's one side)

**Agreement filter**:
The synthetic-corpus gate where the teacher labels a generated prompt's tier in a second, independent pass, and only pairs whose intended band matches the labeled band survive into training.
_Avoid_: self-check, label verification, double-labeling

**Shadow pass**:
The post-response background run of a gate-passing distillate on contested traffic — compared against the incumbent without touching the live response, logged outside the main ledger until the human cuts over.
_Avoid_: shadow mode (that's the config state), canary, A/B test (no traffic splits)

