# Connecting your tools

## Endpoints

Point any OpenAI-compatible client at `http://localhost:4114/v1` with
`model: auto`. kultivait also serves an Anthropic-compatible `/v1/messages`
endpoint with content blocks, the `system` parameter, and tool support, so
Anthropic API clients can use the proxy as well:

```bash
ANTHROPIC_BASE_URL=http://localhost:4114 <your-tool>
```

Both endpoints stream over SSE. Local tiers stream token by token. Cloud
tiers run through print-mode CLIs, which only produce output when they exit,
so those responses arrive as a single final chunk.

A request that carries tools is always served by a local tool-capable tier,
even when classification points at a cloud tier, because cloud CLIs run
their own agent loops and can't return client-side tool calls. When that
happens, the `fallback_reason` field in the response's `kultivait` metadata
says so.

### The Pi coding agent

Add a provider to `~/.pi/agent/models.json`:

```json
"kultivait": {
  "api": "openai-completions",
  "apiKey": "kultivait",
  "baseUrl": "http://127.0.0.1:4114/v1",
  "models": [{ "contextWindow": 131072, "id": "auto", "input": ["text"] }]
}
```

Then run `pi --provider kultivait --model auto`. Tool calls pass through on
the OpenAI endpoint, so Pi's whole agent loop (read, bash, edit, write) runs
through the proxy and every turn is routed and tallied.

## Zero-config adoption

You can route existing tools, agents, and IDEs through kultivait without
changing their code. There are four ways in, from narrowest to broadest.

### Wrap one command: `kultivait run -- <cmd>`

`kultivait run` sets `OPENAI_BASE_URL` and `ANTHROPIC_BASE_URL` in the child
process's environment, forwards POSIX signals, and preserves the exit code.
It leaves no configuration behind.

```bash
kultivait run -- claude
kultivait run -- pi --provider openai --model auto
kultivait run -- python test_agents.py
```

There's nothing to roll back: the variables exist only in the child process
and disappear when it exits.

### Hook a shell session: `eval "$(kultivait hook)"`

This sets the same variables for your whole interactive shell. It works in
`sh`, `bash`, `zsh`, and `fish`.

```bash
eval "$(kultivait hook)"                 # activate (sh, bash, zsh)
kultivait hook --shell fish | source     # fish
kultivait hook --check                   # verify active hook status
eval "$(kultivait hook --unset)"         # rollback
```

### Patch your editor: `kultivait hook ide`

`hook ide` finds Cursor, VS Code, and Windsurf settings and points their LLM
requests at the proxy. It keeps atomic `.kultivait-bak` backups, and
`--restore` rolls the change back.

```bash
kultivait hook ide --dry-run     # preview modifications safely
kultivait hook ide               # patch all detected IDEs
kultivait hook ide --ide cursor  # target a specific IDE
kultivait hook ide --restore     # rollback
```

### OS-level loopback: `kultivait hook loopback`

For transparent interception across the whole OS, `hook loopback` generates
configuration for you to review:

```bash
kultivait hook loopback --generate-hosts   # /etc/hosts entries (routes api.anthropic.com & api.openai.com to 127.0.0.1)
kultivait hook loopback --generate-pf      # macOS packet filter rules
kultivait hook loopback --generate-cert    # TLS certificate generation & trust instructions
kultivait hook loopback --generate-uninstall
```

`hook loopback` never applies anything itself and never needs root; you run
the `sudo` commands by hand after reading them. Intercepting HTTPS also
means creating and trusting a local self-signed root certificate
(`kultivait-proxy.crt`).

### Rolling back

| Adoption path | Rollback | Result |
|---|---|---|
| Process wrapper | Terminate command (`Ctrl+C`) | Child exits; no residual state |
| Shell hook | `eval "$(kultivait hook --unset)"` | Unsets session environment variables |
| IDE patcher | `kultivait hook ide --restore` | Atomically restores `.kultivait-bak` |
| Loopback | `--generate-uninstall` output | Reverts `/etc/hosts`, `pf` rules, trusted cert |

### Recursion safety

Some cloud-worthy work is dispatched to upstream CLIs such as `claude`,
`gemini`, `codex`, `opencode`, and `agy`. Before spawning any of them,
kultivait strips `OPENAI_BASE_URL`, `ANTHROPIC_BASE_URL`, and related
variables (the `PROXY_ENV_STRIP` list), so upstream tools connect straight
to their providers and never loop back through the proxy.

## Related

- [Zero-config adoption runbook](../superpowers/runbooks/2026-09-02-zero-config-adoption-runbook.md): every path in more detail, with sample output
- [Tools dogfooding findings](../superpowers/specs/2026-08-24-tools-dogfooding-findings.md): streaming tool calls through the proxy
