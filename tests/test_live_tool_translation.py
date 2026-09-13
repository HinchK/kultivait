"""Live T4/T5 regression for #214: Anthropic tools on the local-backend seam.

E8 (claude-socket loopback) proved /v1/messages forwarded Anthropic flat tools
to local runtimes untranslated — llama.cpp hard-500'd; ollama's response was
never tested. These tests run against a real ollama instance and skip (not
fail) when none is serving. Never-both-up: this leg requires llama-server
DOWN; if it answers on :8080 the runtime policy is violated and both tests
skip with that reason.
"""

import json
import os

import httpx
import numpy as np
import pytest

from kultivait.backends import OllamaBackend
from kultivait.escalations import EscalationStore
from kultivait.gates import Gate
from kultivait.ledger import Ledger
from kultivait.router import Router
from kultivait.server import create_app

OLLAMA_URL = os.environ.get("KULTIVAIT_LIVE_OLLAMA", "http://localhost:11434")
MODEL = os.environ.get("KULTIVAIT_LIVE_TOOL_MODEL", "qwen2.5:14b")

TOOLS = [
    {
        "name": "get_weather",
        "description": "Get the current weather for a city",
        "input_schema": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
    }
]

PROMPT = (
    "You must answer using the get_weather tool. "
    "What is the weather in Berlin? Call get_weather with city Berlin."
)


def _probe(url: str) -> bool:
    try:
        return httpx.get(url, timeout=2).status_code == 200
    except Exception:
        return False


def _installed_models() -> list[str]:
    try:
        r = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        return [m.get("name", "") for m in r.json().get("models", [])]
    except Exception:
        return []


ollama_up = _probe(f"{OLLAMA_URL}/api/tags")
llamacpp_up = _probe("http://localhost:8080/health")
model_installed = any(m.split(":")[0] == MODEL.split(":")[0] for m in _installed_models())

pytestmark = pytest.mark.skipif(
    not ollama_up,
    reason=f"no ollama answering on {OLLAMA_URL}",
)


@pytest.mark.skipif(llamacpp_up, reason="never-both-up violated: llama-server also serving")
@pytest.mark.skipif(not model_installed, reason=f"model {MODEL} not pulled")
def test_t5_live_ollama_accepts_translated_anthropic_tools():
    backend = OllamaBackend(MODEL, base_url=OLLAMA_URL)
    completion = backend.complete(
        [{"role": "user", "content": PROMPT}],
        tools=TOOLS,
    )
    assert completion.local is True
    # the regression is a hard backend failure (E8: parse error / HTTP 500);
    # reaching a Completion at all means the translated payload was accepted
    if completion.tool_calls:
        call = completion.tool_calls[0]
        assert call["function"]["name"] == "get_weather"
        args = json.loads(call["function"]["arguments"])
        assert "berlin" in json.dumps(args).lower()


@pytest.mark.skipif(llamacpp_up, reason="never-both-up violated: llama-server also serving")
@pytest.mark.skipif(not model_installed, reason=f"model {MODEL} not pulled")
def test_t4_live_messages_endpoint_serves_anthropic_tools_locally(tmp_path):
    import socket
    import threading
    import time

    import uvicorn

    backend = OllamaBackend(MODEL, base_url=OLLAMA_URL)
    app = create_app(
        router=Router(
            centroids={
                MODEL: np.array([1.0, 0.0]),
                "virtual-frontier": np.array([0.0, 1.0]),
            },
            capability_order=[MODEL, "virtual-frontier"],
        ),
        embed=lambda text: np.array([1.0, 0.0]),
        backends={MODEL: backend},
        ledger=Ledger(tmp_path / "ledger.jsonl"),
        gate=Gate(generate=lambda p: "distilled", compost_dir=tmp_path / "compost"),
        escalations=EscalationStore(tmp_path / "escalations"),
        toll_enabled=False,
    )

    # T4 shape: a real serve listener, not TestClient — E8 was observed over
    # the wire, so the regression proves the same path (real HTTP, real
    # dispatch, isolated ledger under tmp_path)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            httpx.get(f"http://127.0.0.1:{port}/", timeout=1)
            break
        except Exception:
            time.sleep(0.2)
    else:
        pytest.fail("scratch serve listener never came up")

    try:
        resp = httpx.post(
            f"http://127.0.0.1:{port}/v1/messages",
            json={
                "model": "auto",
                "max_tokens": 512,
                "messages": [{"role": "user", "content": PROMPT}],
                "tools": TOOLS,
            },
            timeout=300,
        )
    finally:
        server.should_exit = True
        thread.join(timeout=10)

    assert resp.status_code == 200, resp.text[:500]
    data = resp.json()
    # tool-bearing request must serve on the local tier without being dropped:
    # the Anthropic response carries the served tier as `model`
    assert data["model"] == MODEL
    tool_uses = [b for b in data["content"] if b.get("type") == "tool_use"]
    if tool_uses:
        assert tool_uses[0]["name"] == "get_weather"
        assert "berlin" in json.dumps(tool_uses[0].get("input", {})).lower()
