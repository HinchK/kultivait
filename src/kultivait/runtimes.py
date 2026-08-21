"""Runtime lifecycle: ollama and llama-server start/stop with verification.

The setup screen hands the machine from one runtime to the other, but they
must never both serve at once — every stop verifies the port actually went
quiet, and callers gate any start on the other runtime being down. All
process, brew, and network access is injected (the bootstrap.py pattern)."""

import shutil
import subprocess
import time

import httpx

from kultivait.config import RUNTIME_URLS

OLLAMA_URL = RUNTIME_URLS["ollama"]
LLAMA_URL = RUNTIME_URLS["llamacpp"]


def _up(url: str, http_get) -> bool:
    try:
        return http_get(url, timeout=2).status_code == 200
    except httpx.HTTPError:
        return False


def ollama_up(http_get=httpx.get) -> bool:
    return _up(f"{OLLAMA_URL}/api/tags", http_get)


def llama_up(http_get=httpx.get) -> bool:
    return _up(f"{LLAMA_URL}/v1/models", http_get)


def _poll_down(is_up, sleep, deadline_s: int) -> bool:
    waited = 0
    while waited < deadline_s:
        if not is_up():
            return True
        sleep(1)
        waited += 1
    return not is_up()


def start_ollama(
    run_cmd=subprocess.run,
    popen=subprocess.Popen,
    http_get=httpx.get,
    which=shutil.which,
    sleep=time.sleep,
    deadline_s: int = 30,
) -> str:
    """"up" once /api/tags answers, "failed" if it never does. Prefers
    `brew services start ollama` (this is how brew-installed ollama is meant
    to run); without brew, launches a detached `ollama serve`."""
    if ollama_up(http_get):
        return "up"
    brew = which("brew")
    binary = which("ollama")
    if brew:
        run_cmd(["brew", "services", "start", "ollama"])
    elif binary:
        popen([binary, "serve"], start_new_session=True)
    else:
        return "failed"
    waited = 0
    while waited < deadline_s:
        if ollama_up(http_get):
            return "up"
        sleep(1)
        waited += 1
    return "failed"


def stop_ollama(
    run_cmd=subprocess.run,
    http_get=httpx.get,
    which=shutil.which,
    sleep=time.sleep,
    deadline_s: int = 10,
) -> str:
    """"down" once /api/tags stops answering. brew services stop first; a
    server that keeps answering gets pkill'd — the exclusivity guarantee is
    worth more than politeness. "failed" means it would not die."""
    if not ollama_up(http_get):
        return "down"
    if which("brew"):
        run_cmd(["brew", "services", "stop", "ollama"])
    if _poll_down(lambda: ollama_up(http_get), sleep, deadline_s):
        return "down"
    run_cmd(["pkill", "-x", "ollama"])
    if _poll_down(lambda: ollama_up(http_get), sleep, deadline_s):
        return "down"
    return "failed"


def stop_llama(
    run_cmd=subprocess.run,
    http_get=httpx.get,
    sleep=time.sleep,
    deadline_s: int = 10,
) -> str:
    """"down" once :8080 stops answering. llama-server has no service
    manager (we launch it detached), so pkill is the primary lever."""
    if not llama_up(http_get):
        return "down"
    run_cmd(["pkill", "-x", "llama-server"])
    if _poll_down(lambda: llama_up(http_get), sleep, deadline_s):
        return "down"
    return "failed"
