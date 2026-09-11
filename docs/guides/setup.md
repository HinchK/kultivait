# Setup

`kultivait init` surveys your machine and writes `~/.kultivait/config.toml`.
On first run it opens an interactive setup screen. This guide covers what
that screen does, and how to run kultivait on llama.cpp instead of ollama.

## Zero to local on a Mac

On an Apple Silicon Mac with at least 24 GB of unified memory and no local
runtime installed, the setup screen can do the whole bootstrap itself, using
llama.cpp. It runs a preparation checklist (hardware, runtime, survey,
recommendations) and then a garden chooser: the tuned bundle for your RAM, a
reasoning-only variant, or models already on this machine.

Selecting a garden is the consent. Before you press Enter, the detail panel
shows exactly what will download: contents, sizes, RAM fit, and why this
garden was suggested. The download shows its rate and ETA, and Esc cancels
after a confirmation; `.part` files stay resumable. If the server fails to
start, the screen offers `r Retry` and `c Choose another`. The one other
confirmation is for sudo: raising the GPU memory cap asks again, in the
screen, before sudo ever prompts for a password.

## Ollama and llama.cpp take turns

The two runtimes are never up at the same time. If ollama is installed but
nothing is serving, a "Choose your runtime" card appears after the hardware
review. Choose ollama and the screen starts it (`brew services start
ollama`) and lists its models as offerings, each with a parameter analysis.
Choose llama.cpp (offered when this Mac can grow the tuned garden) and you go
straight to the garden chooser. Esc moves on without starting anything.
Setting `KULTIVAIT_RUNTIME` counts as having answered, so the card is
skipped.

Picking a llama.cpp garden while ollama is serving stops ollama, and checks
that its port has gone quiet, before llama-server launches. A "Switch to
ollama" row does the reverse. If a runtime refuses to stop, the switch is
aborted rather than risk both serving at once.

## Skipping and re-running

Esc on the setup screen is a normal way out. It still writes a virtual-tier
config and an onboarding marker (`~/.kultivait/onboarding.json`).
`kultivait init` is safe to re-run: finished steps are skipped and
size-checked downloads resume.

`kultivait init --no-setup` skips the screen, and so does running with a
stdin that is not a TTY. `kultivait init --setup` reopens it on a completed
setup. `KULTIVAIT_RUNTIME` forces a runtime but does not skip the screen; it
only removes the download offerings from it.

## Download integrity

Each GGUF is checked against a pinned upstream SHA256 (Hugging Face's LFS
oid) before it is promoted from its `.part` file, so a mutable
`resolve/main` ref can't slip corrupt or swapped bytes past you. A file that
fails the check is discarded instead of being resumed with a Range request.

## Using llama.cpp instead of ollama

Run `llama-server` in router mode. Launched without `-m`, it lists your GGUF
models at `/v1/models` and loads whichever one a request names. The router
only serves `/v1/embeddings` if the embedding model is marked as one in a
preset file:

```ini
# presets.ini
[nomic-embed-text-v1.5.Q8_0]
model = /path/to/models/nomic-embed-text-v1.5.Q8_0.gguf
embedding = 1
```

```bash
llama-server --models-dir ~/models --models-preset presets.ini --jinja
kultivait init    # detects the router on :8080
```

`--jinja` enables tool calls. `init` reads the router's model list, sizes
each GGUF from disk, and picks tiers the same way it does for ollama. Models
the router advertises for download but you haven't pulled are ignored.

If both runtimes are running, ollama wins; set `KULTIVAIT_RUNTIME=llamacpp`
to force llama.cpp. For non-default ports and model directories, use
`KULTIVAIT_LLAMACPP_URL` and `KULTIVAIT_LLAMACPP_MODELS_DIR`.

To use a dedicated embedding server instead of the preset, run
`llama-server -m nomic-embed.gguf --embedding --port 8081` and set
`embed_base_url = "http://localhost:8081"` in `~/.kultivait/config.toml`.
An empty `embed_base_url` means the chat server handles embeddings too.

llama.cpp fixes its context size when the server launches (`--ctx-size`),
so kultivait's `num_ctx` setting and truncation detection apply to ollama
only.

## Related

- [Hardware tuning design](../superpowers/specs/2026-07-14-init-hardware-tuning-design.md): how gardens are sized for your RAM
- [Setup screen design](../superpowers/specs/2026-07-15-init-tui-polish-design.md)
- [Runtime consent design](../superpowers/specs/2026-09-10-runtime-consent-design.md)
