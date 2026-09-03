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

# 2. kultivait
say "installing kultivait..."
uv tool install --force --from git+https://github.com/Standard-Pentest/kultivait kultivait

# 3. in-app setup: runtime choice, models, server, config — all from here.
#    </dev/tty because `curl | sh` leaves stdin as the pipe; the setup
#    screen needs the real terminal.
say ""
kultivait init </dev/tty

say ""
say "planted. next:"
say "  kultivait serve                    # proxy on http://localhost:4114"
say "  kultivait route \"your prompt\"      # see where a prompt would go"
say "  kultivait harvest                  # watch the savings grow"
