# PostHog post-wizard report

The wizard added the PostHog Python SDK to this FastAPI proxy and configured it through `POSTHOG_PROJECT_TOKEN` and `POSTHOG_HOST` environment variables. The application loads local `.env` configuration, initializes an instance-based PostHog client with exception autocapture, shuts it down on application exit, and captures privacy-safe operational events for completed OpenAI-compatible requests, Anthropic-compatible requests, and phase handoffs. Event properties describe routing metadata only and do not include prompt text or other user-provided content.

| Event name | Description | File |
| --- | --- | --- |
| `chat_completion_completed` | A chat-completion request finishes through the routing proxy. | `src/kultivait/server.py` |
| `message_completion_completed` | An Anthropic-compatible message request finishes through the routing proxy. | `src/kultivait/server.py` |
| `handoff_brief_created` | A transcript is distilled into a phase-handoff brief. | `src/kultivait/server.py` |

## Next steps

- [Analytics basics (wizard) dashboard](https://us.posthog.com/project/28624/dashboard/1867299)
- Saved insights were not created because these newly instrumented events have not yet been ingested into PostHog. Send traffic through the proxy, then create trends for each event after their schema appears.

## Verify before merging

- [ ] Run a full production build (the wizard only verified the files it touched) and fix any lint or type errors introduced by the generated code.
- [ ] Run the test suite — call sites that were rewritten or instrumented may need updated mocks or fixtures.
- [ ] Add the exact PostHog env var names you added to `.env.example` and any monorepo/bootstrap scripts so collaborators know what to set.

### Agent skill

An agent skill folder remains in the project for further agent development with current PostHog integration guidance.
