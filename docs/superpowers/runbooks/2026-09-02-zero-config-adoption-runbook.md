# Zero-Config Adoption & Tool Integration Operational Runbook

**Date**: 2026-09-02  
**Scope**: Developer onboarding, tool interception tiers (Process Wrapper, Shell Hook, IDE Auto-Patcher, Loopback Redirection), recursion safety invariants (`PROXY_ENV_STRIP`), and rollback operations.  
**Relevant ADRs**: [ADR 0019](../../adr/0019-zero-config-adoption.md), [ADR 0005](../../adr/0005-cost-model-duality.md), [ADR 0017](../../adr/0017-distillate-deployment-and-shadow-rollout.md).

---

## 1. Executive Summary & Adoption Philosophy

Kultivait operates as an intelligent routing layer between developer tools and LLM backends (local runtimes and pay-per-token frontier providers). To maximize adoption velocity without friction, Kultivait implements a four-tiered **Zero-Config Adoption Ladder**.

Developers can route traffic into the local proxy (`http://127.0.0.1:4114`) through four progressively integrated mechanisms:
1. **Layer 1: Ephemeral Process Wrapper (`kultivait run -- <cmd>`)**: Intercepts a single child process execution without global state modification.
2. **Layer 2: Shell Session Injection (`eval "$(kultivait hook)"`)**: Exports standard API base URL environment variables across an interactive shell session.
3. **Layer 3: IDE Configuration Auto-Patcher (`kultivait hook ide`)**: Discovers and atomically patches user settings in Cursor, VS Code, and Windsurf.
4. **Layer 4: Transparent Loopback Redirection (`kultivait hook loopback`)**: Generates system-level `/etc/hosts`, macOS packet-filter (`pf`), and TLS proxy configuration for global OS-level interception.

---

## 2. Adoption Ladder: Detailed Path Specifications

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       KULTIVAIT ADOPTION LADDER                             │
├────────────────────────────────┬────────────────────────────────────────────┤
│ Tier / Mechanism               │ Scope & Privilege Profile                  │
├────────────────────────────────┼────────────────────────────────────────────┤
│ 1. Process Wrapper             │ Per-command execution (Ephemeral)          │
│    kultivait run -- <cmd>      │ Zero persistent state, zero root required  │
├────────────────────────────────┼────────────────────────────────────────────┤
│ 2. Shell Hook                  │ Per-shell session (Interactive)            │
│    eval "$(kultivait hook)"    │ Process-tree scoped, zero root required    │
├────────────────────────────────┼────────────────────────────────────────────┤
│ 3. IDE Auto-Patcher            │ Per-editor settings (User profile)         │
│    kultivait hook ide          │ Application-level JSON, atomic backups     │
├────────────────────────────────┼────────────────────────────────────────────┤
│ 4. Loopback Redirection        │ Machine-wide socket redirection (Advanced) │
│    kultivait hook loopback     │ OS packet filter + TLS MITM (Review-only)  │
└────────────────────────────────┴────────────────────────────────────────────┘
```

---

### Path 1: Ephemeral Process Wrapper (`kultivait run`)

The process wrapper is the fastest, lowest-risk entry point. It wraps any command, injects proxy routing environment variables into the child environment, forwards POSIX signals, and preserves exit codes.

#### Syntax & Usage
```bash
# Wrap arbitrary CLI agent loops or scripts
kultivait run -- claude
kultivait run -- pi --provider openai --model auto
kultivait run -- python run_evals.py

# Custom host / port flags
kultivait run --host 127.0.0.1 --port 4114 -- codex exec "fix deadlock"
```

#### Injected Environment
- `OPENAI_BASE_URL="http://127.0.0.1:4114/v1"`
- `ANTHROPIC_BASE_URL="http://127.0.0.1:4114"`
- `OPENAI_API_KEY="kultivait"` (set if unset; preserves existing user keys)
- `ANTHROPIC_API_KEY="kultivait"` (set if unset; preserves existing user keys)

#### Execution Behavior
- **Signal Forwarding**: Traps `SIGINT` (Ctrl+C) and `SIGTERM` and forwards them cleanly to the child process.
- **Exit Code Fidelity**: Propagates the child process's exact exit code (`0` for success, `1..255` for failures, `127` if executable not found).
- **Zero Disk Footprint**: Modifies no shell profiles, registry files, or IDE configs.

---

### Path 2: Shell Session Injection (`kultivait hook`)

For interactive terminal sessions where multiple commands or tools are run sequentially, `kultivait hook` outputs shell-native export/unset directives.

#### Syntax & Usage
```bash
# Standard sh / bash / zsh activation
eval "$(kultivait hook)"

# Fish shell activation
kultivait hook --shell fish | source

# Verify hook status in the current shell
kultivait hook --check
# Output:
# OPENAI_BASE_URL=http://127.0.0.1:4114/v1
# ANTHROPIC_BASE_URL=http://127.0.0.1:4114
# expected: http://127.0.0.1:4114
# hooked: yes
```

#### Deactivation & Unset
```bash
# Deactivate proxy routing in current shell
eval "$(kultivait hook --unset)"

# Fish shell deactivation
kultivait hook --shell fish --unset | source
```

---

### Path 3: IDE Configuration Auto-Patcher (`kultivait hook ide`)

`kultivait hook ide` discovers local editor installations on macOS and Linux, creates an atomic backup of user settings, and injects base URL configuration.

#### Supported IDE Targets & Registry
| IDE | Platform Path | Patched Settings Key | Injected Value |
|---|---|---|---|
| **Cursor** | `~/Library/Application Support/Cursor/User/settings.json`<br>`~/.config/Cursor/User/settings.json` | `openai.baseUrl` | `http://127.0.0.1:4114/v1` |
| **VS Code** | `~/Library/Application Support/Code/User/settings.json`<br>`~/.config/Code/User/settings.json` | `openai.baseUrl` | `http://127.0.0.1:4114/v1` |
| **Windsurf** | `~/.codeium/windsurf/settings.json`<br>`~/.codeium/windsurf/settings.json` | `openai.baseUrl` | `http://127.0.0.1:4114/v1` |

#### Commands & Safety Controls
```bash
# 1. Preview changes without writing to disk
kultivait hook ide --dry-run
# Output:
# detected: cursor, vscode
#   cursor [dry-run] would set: openai.baseUrl
#   vscode [dry-run] would set: openai.baseUrl

# 2. Apply atomic patch across all detected editors
kultivait hook ide
# Output:
# detected: cursor, vscode
#   cursor: patched openai.baseUrl (backup: .../settings.json.kultivait-bak)
#   vscode: patched openai.baseUrl (backup: .../settings.json.kultivait-bak)

# 3. Target a specific editor
kultivait hook ide --ide cursor

# 4. Instant rollback to previous configuration
kultivait hook ide --restore
# Output:
# detected: cursor, vscode
#   cursor: restored from backup
#   vscode: restored from backup
```

#### Atomic Safety Guarantee
- **Pre-Write Backup**: Creates `<settings.json>.kultivait-bak` before writing any changes.
- **Atomic Replace**: Writes to a temporary `<settings.json>.tmp` file and atomically renames (`replace`) over the target file, preventing corruption during concurrent writes or sudden termination.
- **Idempotency**: Running `kultivait hook ide` repeatedly against an already-patched file reports `already routed (no change needed)` and performs zero writes.

---

### Path 4: Transparent Loopback Redirection (`kultivait hook loopback`)

For environments requiring transparent system-wide redirection without application-level settings modification, `kultivait hook loopback` acts as a non-privileged configuration generator.

> [!IMPORTANT]
> In accordance with Kultivait's zero-root standard, `kultivait hook loopback` generates review-ready configuration templates. It never executes `sudo` or modifies system files autonomously.

#### Generated Configuration Artifacts
```bash
# Generate /etc/hosts domain redirection entries
kultivait hook loopback --generate-hosts

# Generate macOS packet filter (pf) rules
kultivait hook loopback --generate-pf

# Generate TLS certificate generation & trust instructions
kultivait hook loopback --generate-cert

# Generate uninstallation & clean-up script
kultivait hook loopback --generate-uninstall

# Print complete setup and trade-off guide
kultivait hook loopback
```

#### Architecture & Trade-Offs
- **Domains Intercepted**: `api.anthropic.com`, `api.openai.com` redirected to `127.0.0.1`.
- **Packet Filter (`pf`)**: Redirects port 443 TCP traffic on loopback `lo0` to Kultivait's local listener.
- **TLS Termination**: Requires a trusted local root CA / self-signed certificate (`kultivait-proxy.crt`) configured in `~/.kultivait/config.toml` under `[tls]`.
- **Trade-Off**: Provides absolute transparency across all processes, but introduces TLS MITM maintenance overhead and system keychain mutations. Application-level injection (Paths 1–3) remains the recommended standard.

---

## 3. Recursion Safety Invariant (`PROXY_ENV_STRIP`)

### The Infinite Loop Hazard
When Kultivait intercepts a client tool (e.g. an agent running via `kultivait run -- claude`), the request arrives at the proxy on `http://127.0.0.1:4114`.
If the proxy's embedding classifier or preprocessor determines that the prompt is cloud-worthy and dispatches to an upstream CLI backend (such as `claude`, `gemini`, `codex`, or `agy`), the upstream CLI process inherits the environment of the parent proxy.

If `OPENAI_BASE_URL` or `ANTHROPIC_BASE_URL` remained in the environment, the upstream CLI would attempt to connect back to `http://127.0.0.1:4114`, causing a recursive request loop that exhausts system file descriptors and crashes the proxy.

```
[Client Agent]
      │ (ANTHROPIC_BASE_URL=127.0.0.1:4114)
      ▼
[Kultivait Proxy :4114]
      │
      ├── Router / Preprocessor (verdict: frontier)
      │
      └── CLIBackend Dispatch (e.g. `claude`)
            │
            ├── ⚠️ WITHOUT PROXY_ENV_STRIP:
            │     claude reads ANTHROPIC_BASE_URL=127.0.0.1:4114 ──► [RECURSION LOOP / CRASH]
            │
            └── ✅ WITH PROXY_ENV_STRIP:
                  Stripped Environment (Direct to upstream) ────► [api.anthropic.com]
```

### The Invariant Implementation
In [`src/kultivait/backends.py`](../../src/kultivait/backends.py), `PROXY_ENV_STRIP` defines the strict set of environment variables stripped prior to spawning any upstream CLI backend process:

```python
PROXY_ENV_STRIP: list[str] = [
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_API_URL",
    "OPENAI_BASE_URL",
    "OPENAI_API_BASE",
    "OPENAI_PROXY_URL",
]
```

When `CLIBackend.complete()` builds the execution environment via `os.environ`, it enforces:
```python
env = {k: v for k, v in os.environ.items() if k not in PROXY_ENV_STRIP}
```

This guarantees that upstream CLI dispatches always break out of the proxy environment and communicate directly with native provider endpoints.

---

## 4. Rollback & Restoration Matrix

| Adoption Path | Active Artifacts | Restoration Command | Verification Check |
|---|---|---|---|
| **Process Wrapper** | None (ephemeral child process) | Terminate command (`Ctrl+C`) | `env | grep BASE_URL` (empty) |
| **Shell Hook** | Session environment variables | `eval "$(kultivait hook --unset)"` | `kultivait hook --check` (`hooked: no`) |
| **IDE Auto-Patcher** | Patched `settings.json` + `.kultivait-bak` | `kultivait hook ide --restore` | Inspect `settings.json` (no `openai.baseUrl`) |
| **Loopback Redirection** | `/etc/hosts`, `/etc/pf.anchors`, Keychain cert | `kultivait hook loopback --generate-uninstall` (run generated script) | `ping api.openai.com` (resolves to public IP) |

---

## 5. Verification Checklist & Troubleshooting

### Operational Verification Workflow
1. **Start the Proxy**:
   ```bash
   kultivait serve
   ```
2. **Verify Process Wrapping**:
   ```bash
   kultivait run -- python -c "import os; print(os.environ['OPENAI_BASE_URL'])"
   # Expected output: http://127.0.0.1:4114/v1
   ```
3. **Verify Shell Hook & Check**:
   ```bash
   eval "$(kultivait hook)"
   kultivait hook --check
   # Expected output: hooked: yes
   eval "$(kultivait hook --unset)"
   kultivait hook --check
   # Expected output: hooked: no
   ```
4. **Verify IDE Patch & Restore**:
   ```bash
   kultivait hook ide --dry-run
   kultivait hook ide
   kultivait hook ide --restore
   ```
5. **Inspect Live Harvest Telemetry**:
   ```bash
   kultivait harvest
   ```
   Ensure dispatches and `kept-in-pocket` / `kept-via-cache` economics record accurately in `~/.kultivait/ledger.jsonl`.
