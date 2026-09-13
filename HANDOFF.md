# HANDOFF — #214 C2: Anthropic→OpenAI tool translation at the local-backend boundary

- **Ticket**: [#214](https://github.com/Standard-Pentest/kultivait/issues/214) (map #221, child)
- **Branch**: `main` (stacked after unpushed `wip` 1947715 = #211/C1 fix — not mine, leave alone, do not push)
- **Started**: 2026-09-13, arch seat (opencode)

## Goal

`/v1/messages` passes Anthropic-format tools (`{name, description, input_schema}`) untranslated
into local backends' OpenAI-format payloads (`backends.py:138` Ollama, `backends.py:250` llama.cpp)
— the claude-socket E8 bug (llama.cpp hard 500 "Missing tool type"; ollama response unknown).
Fix: reuse `api_backends.anthropic_tools_to_openai` at both local seams; OpenAI-format tools
pass through unchanged. Local target must stay eligible for tool-bearing requests.

## Done-criteria (from issue)

1. Tool-bearing `/v1/messages` requests work on ollama (payload translated at the local seam).
2. T5 unit contract test per local backend: Anthropic tools in → OpenAI `{type: function,
   function: {parameters}}` in the wire payload.
3. T4/T5 live regression against a real ollama instance.
4. Capability filter does not silently drop the local target (routing tests already cover
   `tools_unsupported` fallback — verify still green, add payload-level proof).
5. `uv run pytest -q` fully green.

## Ordered tasks

- [x] 1. Claim #214, post plan comment.
- [x] 2. Write HANDOFF.md (this file).
- [x] 3. Implement translation in `OllamaBackend._payload` + `LlamaCppBackend._payload`
       (function-local import — avoids the backends↔api_backends import cycle).
- [x] 4. Unit tests (T5 unit): per-backend payload translation; OpenAI passthrough intact.
- [x] 5. Live regression (T4/T5): skipif-gated pytest — real OllamaBackend direct dispatch +
       full `/v1/messages` E2E over a real uvicorn listener (isolated ledger, toll off),
       model `qwen2.5:14b`, ollama :11434. Both PASSED; manual probes recorded:
       translated tools → `get_weather {"city": "Berlin"}`; UNtranslated (pre-fix payload)
       → ollama 200 with tools silently dropped, prose answer (T5's open question, settled).
- [x] 6. `uv run pytest -q` green: **799 passed, 2 skipped**.
- [ ] 7. Commit `fix:` (+ticked HANDOFF), delegate close + map gist to agy-gh.
- [ ] 8. Ledger record + engrim state; completion verdict.

## Current task

7 (commit + close-out).

## Next action if interrupted

Tasks 3–4 are one commit boundary with this file; if the live test (5) half-ran, re-check
`curl -s localhost:11434/api/tags` first — ollama must be up and exactly one runtime serving
(never-both-up, llama-server currently down = correct for this leg).
