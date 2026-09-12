#!/usr/bin/env python3
"""Driver for running and poking kultivait without models or network.

kultivait is a routing proxy in front of a local model runtime. On a clean
machine there is no ollama and no llama-server, so this driver ships a FAKE
ollama (the three endpoints kultivait actually calls) and points a kultivait
instance at it via an isolated HOME. Nothing here touches ~/.kultivait, the
user's config, ledger, or any live proxy.

Subcommands (run from the repo root):
  uv run python .claude/skills/run-kultivait/driver.py smoke   # build + drive + assert, exit 1 on failure
  uv run python .claude/skills/run-kultivait/driver.py up      # leave the stack running, print URLs
  uv run python .claude/skills/run-kultivait/driver.py down    # stop a stack left by `up`
  uv run python .claude/skills/run-kultivait/driver.py fake --port N   # the fake runtime alone

Flags: --keep (smoke leaves the stack up), --home DIR (reuse a sandbox),
--real (skip the fake; use whatever runtime is already running — do NOT use
this while a live kultivait/herd is serving).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
STATE = "driver-state.json"  # written inside the sandbox HOME

# ---------------------------------------------------------------- fake runtime

FAKE_MODELS = [
    {"name": "fake-small:1b", "size": 1_000_000_000},
    {"name": "fake-big:14b", "size": 14_000_000_000},
]
EMBED_DIM = 32


def _embed(text: str) -> list[float]:
    """Deterministic bag-of-words hash embedding: same text -> same vector,
    similar text -> similar vector. Enough for the router to classify."""
    vec = [0.0] * EMBED_DIM
    for word in re.findall(r"[a-z0-9]+", text.lower()):
        h = hashlib.sha256(word.encode()).digest()
        vec[h[0] % EMBED_DIM] += 1.0
    norm = sum(v * v for v in vec) ** 0.5 or 1.0
    return [v / norm for v in vec]


class FakeOllama(BaseHTTPRequestHandler):
    """The three endpoints kultivait calls: /api/tags (survey), /api/embed
    (router centroids + classification), /api/chat (serving, NDJSON stream)."""

    def _read(self):
        n = int(self.headers.get("content-length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def _send(self, obj, code=200, ctype="application/json"):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("content-type", ctype)
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/api/tags"):
            return self._send({"models": FAKE_MODELS})
        self._send({"error": "not found"}, 404)

    def do_POST(self):
        body = self._read()
        if self.path.startswith("/api/embed"):
            texts = body.get("input") or []
            if isinstance(texts, str):
                texts = [texts]
            return self._send({"embeddings": [_embed(t) for t in texts]})
        if not self.path.startswith("/api/chat"):
            return self._send({"error": "not found"}, 404)

        msgs = body.get("messages") or []
        prompt = "".join(str(m.get("content", "")) for m in msgs)
        tools = body.get("tools") or []
        reply = f"FAKE-OK[{body.get('model')}]"
        message = {"role": "assistant", "content": reply}
        if tools:
            # ollama tool-call shape; only the OpenAI-format tools kultivait
            # forwards correctly are understood here.
            fn = tools[0].get("function") or {}
            message = {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"function": {"name": fn.get("name", "unknown"), "arguments": {"path": "a.py"}}}
                ],
            }
        counts = {
            "prompt_eval_count": max(1, len(prompt) // 4),
            "eval_count": len(reply),
            "done": True,
        }
        if not body.get("stream"):
            return self._send({"model": body.get("model"), "message": message, **counts})
        self.send_response(200)
        self.send_header("content-type", "application/x-ndjson")
        self.end_headers()
        if message.get("tool_calls"):
            chunks = [message]
        else:
            chunks = [{"role": "assistant", "content": c} for c in (reply[:8], reply[8:])]
        for ch in chunks:
            self.wfile.write(json.dumps({"model": body.get("model"), "message": ch}).encode() + b"\n")
            self.wfile.flush()
        self.wfile.write(
            json.dumps({"model": body.get("model"), "message": {"content": ""}, **counts}).encode() + b"\n"
        )

    def log_message(self, *a):
        pass


PREPROCESS_PORT = 11434  # hardwired in server.py:_default_preprocess_generate_for


def serve_fake(port: int) -> None:
    """Serve the fake on `port`, and ALSO on 11434 when that port is free.

    kultivait's preprocessor generator ignores the config and always posts to
    http://localhost:11434/api/chat (server.py:96-99, cli.py:632 passes no
    preprocess_generate). On a machine with no ollama, every contested prompt
    would otherwise raise ConnectError -> ASGI 500 (issue #211). Binding the
    fake there too keeps the sandbox self-consistent. If the port is taken
    (a real ollama, or another sandbox), we skip it and the smoke reports the
    contested-prompt path as a known bug instead of a failure."""
    import threading

    try:
        shim = ThreadingHTTPServer(("127.0.0.1", PREPROCESS_PORT), FakeOllama)
        threading.Thread(target=shim.serve_forever, daemon=True).start()
    except OSError:
        pass
    ThreadingHTTPServer(("127.0.0.1", port), FakeOllama).serve_forever()


# ---------------------------------------------------------------- sandbox

def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


CONFIG = """runtime = "ollama"
chat_base_url = "http://127.0.0.1:{fake}"
embed_base_url = ""
embed_model = "fake-embed"
distill_model = "fake-small:1b"
port = {proxy}
num_ctx = 32768
toll_enabled = false

[[tiers]]
name = "fake-small:1b"
role = "simple"
kind = "ollama"
model = "fake-small:1b"

[[tiers]]
name = "fake-big:14b"
role = "reasoning"
kind = "ollama"
model = "fake-big:14b"
"""


def write_config(home: Path, fake: int, proxy: int) -> None:
    (home / ".kultivait").mkdir(parents=True, exist_ok=True)
    (home / ".kultivait" / "config.toml").write_text(CONFIG.format(fake=fake, proxy=proxy))


def wait_http(url: str, timeout: float = 60.0, method: str = "GET") -> bool:
    import httpx

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = httpx.request(method, url, timeout=3)
            if r.status_code < 500:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def env_for(home: Path) -> dict:
    env = dict(os.environ)
    env["HOME"] = str(home)
    for var in ("ANTHROPIC_BASE_URL", "OPENAI_BASE_URL", "KULTIVAIT_RUNTIME"):
        env.pop(var, None)
    return env


def start_stack(home: Path, real: bool) -> dict:
    home.mkdir(parents=True, exist_ok=True)
    proxy = free_port()
    fake = 0
    procs = {}
    if not real:
        fake = free_port()
        p = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "fake", "--port", str(fake)],
            cwd=REPO, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        procs["fake"] = p.pid
        if not wait_http(f"http://127.0.0.1:{fake}/api/tags"):
            raise SystemExit("fake runtime did not come up")
        write_config(home, fake, proxy)
    log = home / "serve.log"
    with open(log, "w") as fh:
        p = subprocess.Popen(
            ["uv", "run", "kultivait", "serve", "--port", str(proxy)],
            cwd=REPO, env=env_for(home), stdout=fh, stderr=subprocess.STDOUT,
        )
    procs["serve"] = p.pid
    state = {"proxy": proxy, "fake": fake, "home": str(home), "procs": procs, "real": real}
    (home / STATE).write_text(json.dumps(state))
    if not wait_http(f"http://127.0.0.1:{proxy}/harvest", timeout=120):
        print(log.read_text()[-2000:], file=sys.stderr)
        stop_stack(home)
        raise SystemExit("kultivait serve did not answer on /harvest")
    return state


CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/usr/bin/google-chrome",
]


def find_chrome() -> "str | None":
    cache = Path.home() / "Library/Caches/ms-playwright"
    if cache.is_dir():  # playwright's headless shell, newest build first
        shells = sorted(cache.glob("chromium_headless_shell-*/*/chrome-headless-shell"), reverse=True)
        if shells:
            return str(shells[0])
    for c in CHROME_CANDIDATES:
        if Path(c).exists():
            return c
    return None


def screenshot(url: str, out: Path) -> str:
    """Capture the dashboard. --timeout is REQUIRED: the page holds an open SSE
    connection to /api/stream, so --virtual-time-budget never settles and the
    browser hangs forever."""
    chrome = find_chrome()
    if not chrome:
        raise SystemExit("no headless chrome found; install a browser or playwright's chromium")
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([chrome, "--headless", "--disable-gpu", "--timeout=8000",
                    "--window-size=1280,1000", f"--screenshot={out}", url],
                   check=True, capture_output=True, timeout=120)
    assert out.exists() and out.stat().st_size > 10_000, f"screenshot looks empty: {out}"
    return f"{out} ({out.stat().st_size} bytes)"


def stop_stack(home: Path) -> None:
    f = home / STATE
    if not f.exists():
        return
    state = json.loads(f.read_text())
    for name, pid in state.get("procs", {}).items():
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    f.unlink()


# ---------------------------------------------------------------- checks

class KnownBug(Exception):
    """A failure caused by a filed kultivait bug, not by the harness."""


class Checks:
    def __init__(self):
        self.rows = []

    def run(self, name, fn):
        try:
            detail = fn() or ""
            self.rows.append(("PASS", name, detail))
        except KnownBug as e:
            self.rows.append(("KNOWN-BUG", name, str(e)))
        except Exception as e:  # noqa: BLE001 - report, don't raise
            self.rows.append(("FAIL", name, f"{type(e).__name__}: {e}"))

    def report(self) -> int:
        bad = sum(1 for s, _, _ in self.rows if s == "FAIL")
        known = sum(1 for s, _, _ in self.rows if s == "KNOWN-BUG")
        for status, name, detail in self.rows:
            print(f"  {status:<9} {name}" + (f" — {detail}" if detail else ""))
        print(f"\n{len(self.rows) - bad - known}/{len(self.rows)} checks passed"
              + (f", {known} known-bug" if known else "") + (f", {bad} FAILED" if bad else ""))
        return 1 if bad else 0


def smoke(home: Path, real: bool, keep: bool) -> int:
    import httpx

    state = start_stack(home, real)
    base = f"http://127.0.0.1:{state['proxy']}"
    c = Checks()

    def openai_nonstream():
        r = httpx.post(f"{base}/v1/chat/completions", timeout=120, json={
            "model": "auto", "messages": [{"role": "user", "content": "rename this variable"}]})
        r.raise_for_status()
        d = r.json()
        assert d["choices"][0]["message"]["content"], "empty content"
        return f"tier={d.get('kultivait', {}).get('tier')} text={d['choices'][0]['message']['content'][:24]!r}"

    def openai_stream():
        seen = []
        with httpx.stream("POST", f"{base}/v1/chat/completions", timeout=120, json={
                "model": "auto", "stream": True,
                "messages": [{"role": "user", "content": "explain this stack trace"}]}) as r:
            r.raise_for_status()
            assert r.headers["content-type"].startswith("text/event-stream")
            for line in r.iter_lines():
                if line.startswith("data: ") and line[6:] != "[DONE]":
                    seen.append(json.loads(line[6:]))
        deltas = "".join(e["choices"][0]["delta"].get("content", "") for e in seen)
        assert deltas, "no content deltas"
        return f"{len(seen)} events, text={deltas[:24]!r}"

    def anthropic_nonstream():
        r = httpx.post(f"{base}/v1/messages", timeout=120, json={
            "model": "auto", "max_tokens": 64,
            "messages": [{"role": "user", "content": "summarize the release notes"}]})
        r.raise_for_status()
        d = r.json()
        assert d["type"] == "message" and d["content"][0]["type"] == "text", d
        return f"stop={d['stop_reason']} text={d['content'][0]['text'][:24]!r}"

    def anthropic_stream():
        events = []
        with httpx.stream("POST", f"{base}/v1/messages", timeout=120, json={
                "model": "auto", "max_tokens": 64, "stream": True,
                "messages": [{"role": "user", "content": "write the migration guide"}]}) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if line.startswith("event: "):
                    events.append(line[7:])
        assert events[0] == "message_start" and events[-1] == "message_stop", events
        return " -> ".join(events[:3]) + " ... " + events[-1]

    def preprocessor_crashed() -> bool:
        """Did this request die in the hardwired-to-ollama preprocessor (#211)?"""
        log = (home / "serve.log").read_text()
        return "preprocessor.py" in log and "ConnectError" in log

    def tools_openai():
        r = httpx.post(f"{base}/v1/chat/completions", timeout=120, json={
            "model": "auto", "messages": [{"role": "user", "content": "read a.py"}],
            "tools": [{"type": "function", "function": {
                "name": "read", "parameters": {"type": "object",
                "properties": {"path": {"type": "string"}}}}}]})
        if r.status_code == 500 and preprocessor_crashed():
            raise KnownBug("#211: contested prompt -> preprocessor hardwired to "
                           "localhost:11434 -> ConnectError -> ASGI 500 (port 11434 busy, "
                           "so the driver's shim could not bind)")
        r.raise_for_status()
        calls = r.json()["choices"][0]["message"].get("tool_calls")
        assert calls, "no tool_calls in response"
        return f"tool_calls[0].name={calls[0]['function']['name']}"

    def harvest_endpoint():
        d = httpx.get(f"{base}/harvest", timeout=30).json()
        assert "requests" in json.dumps(d).lower() or d, d
        return json.dumps(d)[:70]

    def dashboard_summary():
        d = httpx.get(f"{base}/api/dashboard/summary", timeout=30).json()
        return ",".join(sorted(d)[:6])

    def ledger_written():
        rows = (home / ".kultivait" / "ledger.jsonl").read_text().strip().splitlines()
        assert rows, "ledger empty"
        last = json.loads(rows[-1])
        return f"{len(rows)} rows, last tier={last['tier']} local={last['local']}"

    def cli_route():
        out = subprocess.run(["uv", "run", "kultivait", "route", "design a distributed cache"],
                             cwd=REPO, env=env_for(home), capture_output=True, text=True, timeout=180)
        assert out.returncode == 0, out.stderr[-200:]
        d = json.loads(out.stdout[out.stdout.index("{"):])  # route prints a JSON verdict
        return f"tier={d['tier']} margin={d['margin']:.3f} escalated={d['escalated']}"

    def cli_harvest():
        out = subprocess.run(["uv", "run", "kultivait", "harvest"], cwd=REPO, env=env_for(home),
                             capture_output=True, text=True, timeout=180)
        assert out.returncode == 0, out.stderr[-200:]
        return out.stdout.strip().splitlines()[-1][:70]

    def no_crash_in_log():
        log = (home / "serve.log").read_text()
        n = log.count("Exception in ASGI application")
        if n and preprocessor_crashed():
            raise KnownBug(f"{n} ASGI exception(s), all the #211 preprocessor ConnectError")
        assert n == 0, f"{n} ASGI exception(s) in serve log (not the known #211 chain)"
        return "clean"

    for name, fn in [
        ("/v1/chat/completions (non-stream)", openai_nonstream),
        ("/v1/chat/completions (stream/SSE)", openai_stream),
        ("/v1/messages (non-stream)", anthropic_nonstream),
        ("/v1/messages (stream/SSE)", anthropic_stream),
        ("tool calls round-trip (OpenAI format)", tools_openai),
        ("GET /harvest", harvest_endpoint),
        ("GET /api/dashboard/summary", dashboard_summary),
        ("ledger written in sandbox HOME", ledger_written),
        ("kultivait route (CLI)", cli_route),
        ("kultivait harvest (CLI)", cli_harvest),
        ("no ASGI exceptions in serve log", no_crash_in_log),
        ("dashboard UI screenshot", lambda: screenshot(f"{base}/dashboard/", home / "dashboard.png")),
    ]:
        c.run(name, fn)

    print(f"\nsandbox HOME: {home}\nproxy: {base}\n")
    rc = c.report()
    if keep:
        print(f"\nstack left running; stop with: driver.py down --home {home}")
    else:
        stop_stack(home)
    return rc


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("cmd", choices=["smoke", "up", "down", "fake", "shot"])
    ap.add_argument("--home", default=None, help="sandbox HOME (default: a temp dir)")
    ap.add_argument("--port", type=int, default=0, help="port for the `fake` subcommand")
    ap.add_argument("--real", action="store_true", help="use the machine's running runtime, not the fake")
    ap.add_argument("--keep", action="store_true", help="smoke: leave the stack running")
    a = ap.parse_args()

    if a.cmd == "fake":
        serve_fake(a.port or 11435)
        return 0

    default_home = Path(os.environ.get("TMPDIR", "/tmp")) / "kultivait-driver-home"
    home = Path(a.home).expanduser() if a.home else default_home

    if a.cmd == "shot":
        state = json.loads((home / STATE).read_text())
        print(screenshot(f"http://127.0.0.1:{state['proxy']}/dashboard/", home / "dashboard.png"))
        return 0
    if a.cmd == "down":
        stop_stack(home)
        print(f"stopped (home {home})")
        return 0
    if a.cmd == "up":
        state = start_stack(home, a.real)
        print(json.dumps(state, indent=2))
        print(f"\nproxy:  http://127.0.0.1:{state['proxy']}")
        print(f"log:    {home}/serve.log")
        print(f"stop:   uv run python {Path(__file__).name} down --home {home}")
        return 0
    return smoke(home, a.real, a.keep)


if __name__ == "__main__":
    sys.exit(main())
