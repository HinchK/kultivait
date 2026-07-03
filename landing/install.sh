#!/bin/sh
# kultivait installer — https://kultivait.ai
# The greenest token is the one you never send.
set -e

say() { printf '%s\n' "$*"; }

# 1. uv (installs kultivait into an isolated tool environment)
if ! command -v uv >/dev/null 2>&1; then
  say "installing uv (python tool manager)..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

# 2. ollama (the local garden itself — we don't install it for you)
if ! command -v ollama >/dev/null 2>&1; then
  say ""
  say "⚠ ollama not found. kultivait routes to local models via ollama."
  say "  install it from https://ollama.com then re-run this script."
  exit 1
fi

# 3. kultivait
say "installing kultivait..."
uv tool install --force --from git+https://github.com/Standard-Pentest/kultivaite kultivait

# 4. an embedding model, if the garden lacks one (274 MB)
if ! ollama list 2>/dev/null | grep -q "nomic-embed-text"; then
  say "pulling nomic-embed-text (274 MB) — the local scale that weighs every prompt..."
  ollama pull nomic-embed-text
fi

# 5. survey the machine and write config
say ""
kultivait init

say ""
say "planted. next:"
say "  kultivait serve                    # proxy on http://localhost:4114"
say "  kultivait route \"your prompt\"      # see where a prompt would go"
say "  kultivait harvest                  # watch the savings grow"
