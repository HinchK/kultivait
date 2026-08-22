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
