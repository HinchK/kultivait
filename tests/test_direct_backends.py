import json
import pytest
import httpx
import numpy as np
from fastapi.testclient import TestClient

from kultivait.api_backends import AnthropicBackend, OpenAIBackend
from kultivait.backends import Completion
from kultivait.escalations import EscalationStore
from kultivait.gates import Gate
from kultivait.ledger import Ledger
from kultivait.router import Router
from kultivait.server import create_app


def _sse_bytes(lines: list[str]) -> bytes:
    return ("\n".join(lines) + "\n\n").encode("utf-8")


def _anthropic_sse_with_cache(
    tool_id: str,
    tool_name: str,
    args: str,
    in_toks: int = 100,
    cache_create: int = 50,
    cache_read: int = 200,
    out_toks: int = 30,
) -> bytes:
    lines = [
        "event: message_start",
        f'data: {{"type":"message_start","message":{{"usage":{{"input_tokens":{in_toks},"cache_creation_input_tokens":{cache_create},"cache_read_input_tokens":{cache_read}}}}}}}',
        "",
        "event: content_block_start",
        f'data: {{"type":"content_block_start","index":0,"content_block":{{"type":"tool_use","id":"{tool_id}","name":"{tool_name}","input":{{}}}}}}',
        "",
        "event: content_block_delta",
        f'data: {{"type":"content_block_delta","index":0,"delta":{{"type":"input_json_delta","partial_json":"{args}"}}}}',
        "",
        "event: content_block_stop",
        'data: {"type":"content_block_stop","index":0}',
        "",
        "event: message_delta",
        f'data: {{"type":"message_delta","usage":{{"output_tokens":{out_toks}}}}}',
        "",
        "event: message_stop",
        'data: {"type":"message_stop"}',
        "",
    ]
    return _sse_bytes(lines)


def _openai_sse_with_cached_tokens(
    tool_id: str,
    tool_name: str,
    args_json: str,
    prompt_toks: int = 500,
    cached_toks: int = 200,
    comp_toks: int = 60,
) -> bytes:
    chunks = [
        f'data: {{"choices":[{{"index":0,"delta":{{"tool_calls":[{{"index":0,"id":"{tool_id}","type":"function","function":{{"name":"{tool_name}","arguments":""}}}}]}}}}]}}'
    ]
    for i in range(0, len(args_json), 8):
        frag = args_json[i : i + 8].replace('"', '\\"')
        chunks.append(
            f'data: {{"choices":[{{"index":0,"delta":{{"tool_calls":[{{"index":0,"function":{{"arguments":"{frag}"}}}}]}}}}]}}'
        )
    chunks += [
        'data: {"choices":[{"index":0,"delta":{},"finish_reason":"tool_calls"}]}',
        f'data: {{"choices":[],"usage":{{"prompt_tokens":{prompt_toks},"completion_tokens":{comp_toks},"prompt_tokens_details":{{"cached_tokens":{cached_toks}}}}}}}',
        "data: [DONE]",
    ]
    return _sse_bytes([c for chunk in chunks for c in (chunk, "")])


# ----------------------------------------------------------------------
# 1. Anthropic Direct Backend Tests
# ----------------------------------------------------------------------

def test_anthropic_headers_and_cache_cost_calculation():
    captured_requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append({
            "headers": dict(request.headers),
            "body": json.loads(request.content.decode("utf-8")),
        })
        body = _anthropic_sse_with_cache(
            "call_ant_01",
            "lookup_file",
            '{"path": "src/main.py"}',
            in_toks=1000,
            cache_create=500,
            cache_read=2000,
            out_toks=100,
        )
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    backend = AnthropicBackend(
        api_key="sk-ant-testkey",
        price_in=3.0,
        price_out=15.0,
        client=client,
    )

    comp = backend.complete(
        messages=[{"role": "user", "content": "lookup file"}],
        canonical_effort="deep",
    )

    # 1. Headers verification
    req = captured_requests[0]
    headers = req["headers"]
    assert headers["x-api-key"] == "sk-ant-testkey"
    assert headers["anthropic-version"] == "2023-06-01"
    assert "anthropic-beta" not in headers  # GA caching: the stale beta header is dropped (#82)

    # 2. Token field & Effort verification
    req_body = req["body"]
    assert "max_tokens" in req_body
    assert req_body["max_tokens"] >= 16384  # deep effort elevation
    assert req_body["output_config"] == {"effort": "high"}

    # 3. Tool calls verification
    assert comp.tool_calls is not None
    assert comp.tool_calls[0]["id"] == "call_ant_01"
    assert comp.tool_calls[0]["function"]["name"] == "lookup_file"

    # 4. Cache-aware cost math:
    # in_toks: 1000 * 3.0 = 3000
    # cache_create: 500 * (3.0 * 1.25 = 3.75) = 1875
    # cache_read: 2000 * (3.0 * 0.10 = 0.30) = 600
    # out_toks: 100 * 15.0 = 1500
    # Total cost USD: (3000 + 1875 + 600 + 1500) / 1e6 = 6975 / 1e6 = 0.006975
    # Total tokens in: 1000 + 500 + 2000 = 3500
    assert comp.tokens_in == 3500
    assert comp.tokens_out == 100
    assert pytest.approx(comp.cost_usd, rel=1e-4) == 0.006975


# ----------------------------------------------------------------------
# 2. OpenAI Direct Backend Tests
# ----------------------------------------------------------------------

def test_openai_headers_and_cache_discount_calculation():
    captured_requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append({
            "headers": dict(request.headers),
            "body": json.loads(request.content.decode("utf-8")),
        })
        body = _openai_sse_with_cached_tokens(
            "call_oai_01",
            "search_code",
            '{"q": "auth"}',
            prompt_toks=1000,
            cached_toks=400,
            comp_toks=200,
        )
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    backend = OpenAIBackend(
        api_key="sk-oai-testkey",
        price_in=2.5,
        price_out=10.0,
        client=client,
    )

    comp = backend.complete(
        messages=[{"role": "user", "content": "search code"}],
        canonical_effort="deep",
    )

    # 1. Headers verification
    req = captured_requests[0]
    headers = req["headers"]
    assert headers["authorization"] == "Bearer sk-oai-testkey"

    # 2. Token field & Effort verification
    req_body = req["body"]
    assert "max_completion_tokens" in req_body
    assert req_body["max_completion_tokens"] >= 16384
    assert req_body["reasoning_effort"] == "xhigh"

    # 3. Tool calls verification
    assert comp.tool_calls is not None
    assert comp.tool_calls[0]["id"] == "call_oai_01"
    assert comp.tool_calls[0]["function"]["name"] == "search_code"

    # 4. Cached tokens pricing (50% discount):
    # uncached_toks: 1000 - 400 = 600 * 2.5 = 1500
    # cached_toks: 400 * (2.5 * 0.5 = 1.25) = 500
    # comp_toks: 200 * 10.0 = 2000
    # Total cost USD: (1500 + 500 + 2000) / 1e6 = 4000 / 1e6 = 0.004000
    assert comp.tokens_in == 1000
    assert comp.tokens_out == 200
    assert pytest.approx(comp.cost_usd, rel=1e-4) == 0.004000


# ----------------------------------------------------------------------
# 3. Server End-to-End Hand-Registered Tier Integration
# ----------------------------------------------------------------------

def test_hand_registered_direct_tiers_dispatch_through_server(tmp_path):
    def ant_handler(request: httpx.Request) -> httpx.Response:
        body = _anthropic_sse_with_cache("ant_tc_1", "run_cmd", '{"cmd": "ls"}', in_toks=100, out_toks=20)
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    def oai_handler(request: httpx.Request) -> httpx.Response:
        body = _openai_sse_with_cached_tokens("oai_tc_1", "run_cmd", '{"cmd": "git status"}', prompt_toks=150, comp_toks=25)
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    ant_backend = AnthropicBackend(api_key="sk-ant", client=httpx.Client(transport=httpx.MockTransport(ant_handler)))
    oai_backend = OpenAIBackend(api_key="sk-oai", client=httpx.Client(transport=httpx.MockTransport(oai_handler)))

    backends = {
        "anthropic": ant_backend,
        "openai": oai_backend,
    }
    app = create_app(
        router=Router(
            centroids={"anthropic": np.array([1.0, 0.0]), "openai": np.array([0.0, 1.0])},
            capability_order=["anthropic", "openai"],
        ),
        embed=lambda text: np.array([1.0, 0.0]) if "ant" in text else np.array([0.0, 1.0]),
        backends=backends,
        ledger=Ledger(tmp_path / "ledger.jsonl"),
        gate=Gate(generate=lambda p: "distilled", compost_dir=tmp_path / "compost"),
        escalations=EscalationStore(tmp_path / "escalations"),
        toll_enabled=False,
    )
    client = TestClient(app)

    # 1. Test Anthropic backend serving /v1/chat/completions (OpenAI client dialect)
    resp1 = client.post(
        "/v1/chat/completions",
        json={
            "model": "auto",
            "messages": [{"role": "user", "content": "ant please run ls"}],
            "tools": [{"type": "function", "function": {"name": "run_cmd"}}],
        },
    )
    assert resp1.status_code == 200
    d1 = resp1.json()
    assert d1["choices"][0]["message"]["tool_calls"][0]["function"]["name"] == "run_cmd"
    assert d1["kultivait"]["tier"] == "anthropic"

    # 2. Test OpenAI backend serving /v1/messages (Anthropic client dialect)
    resp2 = client.post(
        "/v1/messages",
        json={
            "model": "auto",
            "messages": [{"role": "user", "content": "oai please status"}],
            "tools": [{"name": "run_cmd", "input_schema": {"type": "object"}}],
        },
    )
    assert resp2.status_code == 200
    d2 = resp2.json()
    assert d2["stop_reason"] == "tool_use"
    assert d2["content"][0]["type"] == "tool_use"
    assert d2["content"][0]["name"] == "run_cmd"


def test_direct_backends_streaming_and_effort_levels():
    captured = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content.decode("utf-8")))
        body = _anthropic_sse_with_cache("ant_tc_2", "run_cmd", '{"cmd": "pwd"}', in_toks=80, out_toks=15)
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    backend = AnthropicBackend(api_key="sk-ant", client=client)

    # 1. Fast effort -> low
    streamed = list(backend.stream(
        messages=[{"role": "user", "content": "fast test"}],
        canonical_effort="fast",
    ))
    comp = [item for item in streamed if isinstance(item, Completion)][0]
    assert comp.tool_calls is not None
    assert comp.tool_calls[0]["function"]["name"] == "run_cmd"
    assert captured[0]["output_config"] == {"effort": "low"}

    # 2. Balanced effort -> medium
    list(backend.stream(
        messages=[{"role": "user", "content": "balanced test"}],
        canonical_effort="balanced",
    ))
    assert captured[1]["output_config"] == {"effort": "medium"}

