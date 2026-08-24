import json
import pytest
import httpx

from kultivait.api_backends import (
    AnthropicBackend,
    OpenAIBackend,
    OpenRouterBackend,
    ApiRetryableError,
    ApiNonRetryableError,
    anthropic_messages_to_openai,
    anthropic_tools_to_openai,
    cc_messages_to_anthropic,
    cc_tools_to_anthropic,
    extract_canonical_effort,
    iter_sse,
    resolve_max_tokens,
)
from kultivait.backends import Backend, Completion


# ----------------------------------------------------------------------
# Fixture Builders
# ----------------------------------------------------------------------

def _sse_bytes(lines: list[str]) -> bytes:
    return ("\n".join(lines) + "\n\n").encode("utf-8")


def _anthropic_tool_stream(tool_id: str, name: str, args_json: str) -> bytes:
    lines = [
        "event: message_start",
        'data: {"type":"message_start","message":{"usage":{"input_tokens":50,"cache_creation_input_tokens":10,"cache_read_input_tokens":20}}}',
        "",
        "event: content_block_start",
        f'data: {{"type":"content_block_start","index":0,"content_block":{{"type":"tool_use","id":"{tool_id}","name":"{name}","input":{{}}}}}}',
        "",
    ]
    for i in range(0, len(args_json), 8):
        frag = args_json[i : i + 8].replace('"', '\\"')
        lines += [
            "event: content_block_delta",
            f'data: {{"type":"content_block_delta","index":0,"delta":{{"type":"input_json_delta","partial_json":"{frag}"}}}}',
            "",
        ]
    lines += [
        "event: content_block_stop",
        'data: {"type":"content_block_stop","index":0}',
        "",
        "event: message_delta",
        'data: {"type":"message_delta","usage":{"output_tokens":35}}',
        "",
        "event: message_stop",
        'data: {"type":"message_stop"}',
        "",
    ]
    return _sse_bytes(lines)


def _anthropic_text_stream(text: str) -> bytes:
    lines = [
        "event: message_start",
        'data: {"type":"message_start","message":{"usage":{"input_tokens":100}}}',
        "",
        "event: content_block_start",
        'data: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}',
        "",
    ]
    for i in range(0, len(text), 10):
        frag = text[i : i + 10].replace('"', '\\"')
        lines += [
            "event: content_block_delta",
            f'data: {{"type":"content_block_delta","index":0,"delta":{{"type":"text_delta","text":"{frag}"}}}}',
            "",
        ]
    lines += [
        "event: content_block_stop",
        'data: {"type":"content_block_stop","index":0}',
        "",
        "event: message_delta",
        'data: {"type":"message_delta","usage":{"output_tokens":45}}',
        "",
        "event: message_stop",
        'data: {"type":"message_stop"}',
        "",
    ]
    return _sse_bytes(lines)


def _openai_tool_stream(tool_id: str, name: str, args_json: str) -> bytes:
    chunks = [
        f'data: {{"choices":[{{"index":0,"delta":{{"tool_calls":[{{"index":0,"id":"{tool_id}","type":"function","function":{{"name":"{name}","arguments":""}}}}]}}}}]}}'
    ]
    for i in range(0, len(args_json), 8):
        frag = args_json[i : i + 8].replace('"', '\\"')
        chunks.append(
            f'data: {{"choices":[{{"index":0,"delta":{{"tool_calls":[{{"index":0,"function":{{"arguments":"{frag}"}}}}]}}}}]}}'
        )
    chunks += [
        'data: {"choices":[{"index":0,"delta":{},"finish_reason":"tool_calls"}]}',
        'data: {"choices":[],"usage":{"prompt_tokens":60,"completion_tokens":40,"total_tokens":100}}',
        "data: [DONE]",
    ]
    return _sse_bytes([c for chunk in chunks for c in (chunk, "")])


def _openai_text_stream(text: str) -> bytes:
    chunks = []
    for i in range(0, len(text), 12):
        frag = text[i : i + 12].replace('"', '\\"')
        chunks.append(f'data: {{"choices":[{{"index":0,"delta":{{"content":"{frag}"}}}}]}}')
    chunks += [
        'data: {"choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}',
        'data: {"choices":[],"usage":{"prompt_tokens":90,"completion_tokens":28,"total_tokens":118}}',
        "data: [DONE]",
    ]
    return _sse_bytes([c for chunk in chunks for c in (chunk, "")])


def _openrouter_stream_with_comments_and_cost(text: str, cost: float) -> bytes:
    chunks = [
        ": OPENROUTER PROCESSING",
        ": keep-alive",
        'data: {"choices":[{"index":0,"delta":{"content":"' + text[:5] + '"}}]}',
        'data: {"choices":[{"index":0,"delta":{"content":"' + text[5:] + '"}}]}',
        f'data: {{"choices":[],"usage":{{"prompt_tokens":50,"completion_tokens":25,"cost":{cost}}}}}',
        "data: [DONE]",
    ]
    return _sse_bytes([c for chunk in chunks for c in (chunk, "")])


# ----------------------------------------------------------------------
# Protocol & Translation Tests
# ----------------------------------------------------------------------

def test_backend_protocol_conformance():
    a = AnthropicBackend(api_key="test")
    o = OpenAIBackend(api_key="test")
    r = OpenRouterBackend(api_key="test")

    assert isinstance(a, Backend)
    assert isinstance(o, Backend)
    assert isinstance(r, Backend)

    assert a.supports_tools is True and a.local is False
    assert o.supports_tools is True and o.local is False
    assert r.supports_tools is True and r.local is False


def test_tool_schema_translations():
    cc_tools = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Fetch weather",
                "parameters": {"type": "object", "properties": {"city": {"type": "string"}}},
            },
        }
    ]

    anthropic_tools = cc_tools_to_anthropic(cc_tools)
    assert len(anthropic_tools) == 1
    assert anthropic_tools[0]["name"] == "get_weather"
    assert anthropic_tools[0]["description"] == "Fetch weather"
    assert anthropic_tools[0]["input_schema"] == {"type": "object", "properties": {"city": {"type": "string"}}}

    # Round trip back
    back_to_cc = anthropic_tools_to_openai(anthropic_tools)
    assert len(back_to_cc) == 1
    assert back_to_cc[0]["type"] == "function"
    assert back_to_cc[0]["function"]["name"] == "get_weather"
    assert back_to_cc[0]["function"]["parameters"] == {"type": "object", "properties": {"city": {"type": "string"}}}


def test_messages_translations():
    cc_messages = [
        {"role": "system", "content": "You are an assistant."},
        {"role": "user", "content": "Check weather in Berlin."},
        {
            "role": "assistant",
            "content": "Checking...",
            "tool_calls": [
                {
                    "id": "call_123",
                    "type": "function",
                    "function": {"name": "get_weather", "arguments": '{"city": "Berlin"}'},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_123", "content": '{"temp": 21}'},
    ]

    a_msgs, system = cc_messages_to_anthropic(cc_messages)
    assert system == "You are an assistant."
    assert len(a_msgs) == 3
    assert a_msgs[0] == {"role": "user", "content": "Check weather in Berlin."}
    assert a_msgs[1]["role"] == "assistant"
    assert a_msgs[1]["content"][0] == {"type": "text", "text": "Checking..."}
    assert a_msgs[1]["content"][1]["type"] == "tool_use"
    assert a_msgs[1]["content"][1]["id"] == "call_123"
    assert a_msgs[1]["content"][1]["input"] == {"city": "Berlin"}

    assert a_msgs[2]["role"] == "user"
    assert a_msgs[2]["content"][0]["type"] == "tool_result"
    assert a_msgs[2]["content"][0]["tool_use_id"] == "call_123"
    assert a_msgs[2]["content"][0]["content"] == '{"temp": 21}'

    # Round trip to OpenAI format
    o_msgs = anthropic_messages_to_openai(a_msgs, system=system)
    assert o_msgs[0] == {"role": "system", "content": "You are an assistant."}
    assert o_msgs[1] == {"role": "user", "content": "Check weather in Berlin."}
    assert o_msgs[2]["role"] == "assistant"
    assert o_msgs[2]["tool_calls"][0]["id"] == "call_123"
    assert o_msgs[2]["tool_calls"][0]["function"]["name"] == "get_weather"
    assert json.loads(o_msgs[2]["tool_calls"][0]["function"]["arguments"]) == {"city": "Berlin"}
    assert o_msgs[3] == {"role": "tool", "tool_call_id": "call_123", "content": '{"temp": 21}'}


# ----------------------------------------------------------------------
# AnthropicBackend Tests
# ----------------------------------------------------------------------

def test_anthropic_complete_and_stream_with_tools():
    captured_requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(json.loads(request.content.decode("utf-8")))
        if len(captured_requests) == 1:
            body = _anthropic_tool_stream("toolu_01", "get_weather", '{"city": "Paris"}')
        else:
            body = _anthropic_text_stream("The weather in Paris is 22C.")
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    backend = AnthropicBackend(
        api_key="sk-ant-test",
        client=client,
        price_in=3.0,
        price_out=15.0,
    )

    # Turn 1: Complete with tools
    comp1 = backend.complete(
        messages=[{"role": "user", "content": "Weather in Paris?"}],
        tools=[{"type": "function", "function": {"name": "get_weather", "parameters": {}}}],
        canonical_effort="deep",
    )

    assert comp1.local is False
    assert comp1.tool_calls is not None
    assert comp1.tool_calls[0]["id"] == "toolu_01"
    assert comp1.tool_calls[0]["function"]["name"] == "get_weather"
    assert comp1.tool_calls[0]["function"]["arguments"] == '{"city": "Paris"}'

    # Check 3-way input split tokens: input (50) + cache_creation (10) + cache_read (20) = 80
    assert comp1.tokens_in == 80
    assert comp1.tokens_out == 35
    # Cost: (50*3.0 + 10*(3.0*1.25) + 20*(3.0*0.1) + 35*15.0) / 1e6 = (150 + 37.5 + 6.0 + 525) / 1e6 = 718.5 / 1e6 = 0.0007185
    assert pytest.approx(comp1.cost_usd, rel=1e-4) == 0.0007185

    # Check request body formatting: output_config.effort = "high" (deep->high), max_tokens = 16384 (deep headroom)
    req1 = captured_requests[0]
    assert req1["output_config"] == {"effort": "high"}
    assert req1["max_tokens"] >= 16384

    # Turn 2: Stream final text
    deltas_and_comp = list(backend.stream(
        messages=[
            {"role": "user", "content": "Weather in Paris?"},
            {"role": "assistant", "tool_calls": comp1.tool_calls},
            {"role": "tool", "tool_call_id": "toolu_01", "content": '{"temp": 22}'},
        ],
        canonical_effort="fast",
    ))
    text_deltas = [d for d in deltas_and_comp if isinstance(d, str)]
    comp2 = [d for d in deltas_and_comp if isinstance(d, Completion)][0]

    assert "".join(text_deltas) == "The weather in Paris is 22C."
    assert comp2.text == "The weather in Paris is 22C."
    assert captured_requests[1]["output_config"] == {"effort": "low"}


# ----------------------------------------------------------------------
# OpenAIBackend Tests
# ----------------------------------------------------------------------

def test_openai_complete_and_stream_with_tools():
    captured_requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(json.loads(request.content.decode("utf-8")))
        if len(captured_requests) == 1:
            body = _openai_tool_stream("call_oai_1", "calc", '{"expr": "2+2"}')
        else:
            body = _openai_text_stream("2+2 equals 4.")
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    backend = OpenAIBackend(
        api_key="sk-oai-test",
        client=client,
        price_in=2.5,
        price_out=10.0,
    )

    # Turn 1: Complete
    comp1 = backend.complete(
        messages=[{"role": "user", "content": "What is 2+2?"}],
        canonical_effort="deep",
    )

    assert comp1.tool_calls is not None
    assert comp1.tool_calls[0]["id"] == "call_oai_1"
    assert comp1.tool_calls[0]["function"]["name"] == "calc"
    assert comp1.tool_calls[0]["function"]["arguments"] == '{"expr": "2+2"}'
    assert comp1.tokens_in == 60
    assert comp1.tokens_out == 40
    # Cost: (60*2.5 + 40*10.0) / 1e6 = (150 + 400) / 1e6 = 550 / 1e6 = 0.000550
    assert pytest.approx(comp1.cost_usd, rel=1e-4) == 0.000550

    # Check request body formatting: reasoning_effort = "xhigh" (deep->xhigh), max_completion_tokens
    req1 = captured_requests[0]
    assert req1["reasoning_effort"] == "xhigh"
    assert "max_completion_tokens" in req1

    # Turn 2: Stream
    streamed = list(backend.stream(
        messages=[{"role": "user", "content": "What is 2+2?"}],
        canonical_effort="balanced",
    ))
    text_deltas = [s for s in streamed if isinstance(s, str)]
    comp2 = [s for s in streamed if isinstance(s, Completion)][0]

    assert "".join(text_deltas) == "2+2 equals 4."
    assert comp2.text == "2+2 equals 4."
    assert captured_requests[1]["reasoning_effort"] == "medium"


# ----------------------------------------------------------------------
# OpenRouterBackend Tests
# ----------------------------------------------------------------------

def test_openrouter_extracts_cost_and_skips_comments():
    captured_requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(json.loads(request.content.decode("utf-8")))
        body = _openrouter_stream_with_comments_and_cost("Hello from OpenRouter!", cost=0.001234)
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    backend = OpenRouterBackend(
        api_key="sk-or-test",
        client=client,
    )

    comp = backend.complete(
        messages=[{"role": "user", "content": "Say hello"}],
        canonical_effort="deep",
    )

    assert comp.text == "Hello from OpenRouter!"
    assert comp.cost_usd == 0.001234
    assert captured_requests[0]["reasoning_effort"] == "xhigh"


# ----------------------------------------------------------------------
# Retry & Buffered Relay Tests
# ----------------------------------------------------------------------

def test_retry_on_429_with_retry_after_header():
    attempts = 0
    slept_times = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return httpx.Response(
                429,
                content=b'{"error": "rate limit"}',
                headers={"Retry-After": "0.05"},
            )
        return httpx.Response(
            200,
            content=_openai_text_stream("Success after retry"),
            headers={"content-type": "text/event-stream"},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    backend = OpenAIBackend(api_key="sk-test", client=client)

    # Monkeypatch sleep to record sleep durations without waiting
    import kultivait.api_backends as ab
    comp = backend.complete(messages=[{"role": "user", "content": "hi"}])

    assert attempts == 3
    assert comp.text == "Success after retry"


def test_fail_fast_on_401_auth_error():
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(401, content=b'{"error": "invalid api key"}')

    client = httpx.Client(transport=httpx.MockTransport(handler))
    backend = AnthropicBackend(api_key="sk-invalid", client=client)

    with pytest.raises(ApiNonRetryableError, match="HTTP 401"):
        backend.complete(messages=[{"role": "user", "content": "hi"}])

    # Must fail fast on 1 attempt, never hammered
    assert attempts == 1


def test_buffered_relay_discards_failed_attempt_content():
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            # Flaky 500 error
            return httpx.Response(500, content=b'{"error": "internal error"}')
        return httpx.Response(
            200,
            content=_openai_text_stream("Clean whole text"),
            headers={"content-type": "text/event-stream"},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    backend = OpenAIBackend(api_key="sk-test", client=client)

    streamed = list(backend.stream(messages=[{"role": "user", "content": "hi"}]))
    text_deltas = [s for s in streamed if isinstance(s, str)]
    comp = [s for s in streamed if isinstance(s, Completion)][0]

    assert "".join(text_deltas) == "Clean whole text"
    assert comp.text == "Clean whole text"
    assert attempts == 2


def test_openrouter_fallback_cost_calculation():
    def handler(request: httpx.Request) -> httpx.Response:
        body = _openai_text_stream("Fallback price response")
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    backend = OpenRouterBackend(
        api_key="sk-or-test",
        client=client,
        price_in=3.0,
        price_out=15.0,
    )

    comp = backend.complete(messages=[{"role": "user", "content": "hello"}])
    assert comp.text == "Fallback price response"
    # prompt_tokens=90, completion_tokens=28
    # cost: (90*3.0 + 28*15.0) / 1e6 = (270 + 420) / 1e6 = 690 / 1e6 = 0.000690
    assert pytest.approx(comp.cost_usd, rel=1e-4) == 0.000690


def test_anthropic_custom_max_tokens_never_lowered():
    captured = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(
            200,
            content=_anthropic_text_stream("ok"),
            headers={"content-type": "text/event-stream"},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    backend = AnthropicBackend(api_key="sk-test", client=client)

    backend.complete(
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=4096,
        canonical_effort="balanced",
    )
    assert captured[0]["max_tokens"] == 4096


def test_missing_api_key_raises_non_retryable_error(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("kultivait.credentials._get_keychain_key", lambda s, a: None)
    monkeypatch.setattr("kultivait.credentials._get_file_key", lambda p, credentials_path=None: None)

    backend = OpenAIBackend(api_key=None)
    with pytest.raises(ApiNonRetryableError, match="No OpenAI API key configured"):
        backend.complete(messages=[{"role": "user", "content": "hi"}])


def test_extract_canonical_effort_and_resolve_tokens():
    assert extract_canonical_effort(["--effort", "high"]) == "deep"
    assert extract_canonical_effort(["-c", "model_reasoning_effort=low"]) == "fast"
    assert extract_canonical_effort(["-c", "model_reasoning_effort=medium"]) == "balanced"
    assert extract_canonical_effort(None, canonical_effort="deep") == "deep"

    field, limit = resolve_max_tokens(None, "anthropic", "fast")
    assert field == "max_tokens"
    assert limit == 8192

    field, limit = resolve_max_tokens(None, "openai", "deep")
    assert field == "max_completion_tokens"
    assert limit >= 16384


def test_backends_module_getattr_exports():
    import kultivait.backends as backends

    assert backends.AnthropicBackend is AnthropicBackend
    assert backends.OpenAIBackend is OpenAIBackend
    assert backends.OpenRouterBackend is OpenRouterBackend
    assert backends.cc_messages_to_anthropic is cc_messages_to_anthropic
    assert backends.anthropic_messages_to_openai is anthropic_messages_to_openai

