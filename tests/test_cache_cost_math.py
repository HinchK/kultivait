"""C1 (#82) tests: OpenAI write tokens, TTL-aware write pricing, GA headers."""

import json

import httpx
import pytest

from kultivait.api_backends import AnthropicBackend, OpenAIBackend, OpenRouterBackend


def _openai_tool_stream(cached: int = 0, cache_write: int = 0, prompt: int = 1000,
                        completion: int = 50) -> bytes:
    """OpenAI-dialect SSE with usage carrying prompt_tokens_details."""
    chunks = [
        'data: {"choices":[{"index":0,"delta":{"content":"ok"}}]}',
        'data: {"choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}',
        "data: " + json.dumps({"choices": [], "usage": {
            "prompt_tokens": prompt, "completion_tokens": completion,
            "prompt_tokens_details": {
                "cached_tokens": cached, "cache_write_tokens": cache_write}}}),
        "data: [DONE]",
    ]
    return ("\n".join(c for chunk in chunks for c in (chunk, "")) + "\n").encode()


def _anthropic_cached_stream(cache_create: int, cache_read: int, input_t: int,
                             output_t: int = 40) -> bytes:
    start_usage = {"input_tokens": input_t, "cache_creation_input_tokens": cache_create,
                   "cache_read_input_tokens": cache_read}
    lines = [
        "event: message_start",
        "data: " + json.dumps({"type": "message_start", "message": {"usage": start_usage}}),
        "",
        "event: content_block_start",
        'data: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}',
        "",
        "event: content_block_delta",
        'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"ok"}}',
        "",
        "event: content_block_stop", 'data: {"type":"content_block_stop","index":0}', "",
        "event: message_delta",
        f'data: {{"type":"message_delta","delta":{{"stop_reason":"end_turn"}},'
        f'"usage":{{"output_tokens":{output_t}}}}}',
        "",
        "event: message_stop", 'data: {"type":"message_stop"}', "",
    ]
    return ("\n".join(l for line in lines for l in (line, "")) + "\n").encode()


# ---------------------------------------------------------- OpenAI write tokens


def test_openai_write_tokens_priced_as_writes_not_plain_input():
    client = httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, content=_openai_tool_stream(
            cached=0, cache_write=2000, prompt=1000),
            headers={"content-type": "text/event-stream"})))
    be = OpenAIBackend(api_key="sk-test", client=client, price_in=2.5, price_out=10.0)
    c = be.complete([{"role": "user", "content": "hi"}])
    # 5m default: 1000*2.5 (plain) + 2000*2.5*1.25 (write) + 50*10 / 1e6
    expected = (1000 * 2.5 + 2000 * 2.5 * 1.25 + 50 * 10.0) / 1e6
    assert pytest.approx(c.cost_usd, rel=1e-4) == expected
    assert c.cost_usd > (1000 * 2.5 + 50 * 10.0) / 1e6  # the surcharge is real


def test_openai_1h_write_multiplier_doubles_the_premium():
    client = httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, content=_openai_tool_stream(
            cached=0, cache_write=2000, prompt=1000),
            headers={"content-type": "text/event-stream"})))
    be = OpenAIBackend(api_key="sk-test", client=client, price_in=2.5, price_out=10.0,
                       cache_ttl="1h")
    c = be.complete([{"role": "user", "content": "hi"}])
    expected = (1000 * 2.5 + 2000 * 2.5 * 2.0 + 50 * 10.0) / 1e6
    assert pytest.approx(c.cost_usd, rel=1e-4) == expected


def test_openai_cached_read_multiplier_model_aware():
    # gpt-5.6 family: cached reads at 0.1x per the #26 pricing table
    client = httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, content=_openai_tool_stream(
            cached=8000, cache_write=0, prompt=10000, completion=10),
            headers={"content-type": "text/event-stream"})))
    be = OpenAIBackend(api_key="sk-test", client=client, model="gpt-5.6-terra",
                       price_in=2.0, price_out=12.0)
    c = be.complete([{"role": "user", "content": "hi"}])
    # uncached = 10000 - 8000 = 2000 at full; cached at 0.1x; writes 0
    expected = (2000 * 2.0 + 8000 * 2.0 * 0.1 + 10 * 12.0) / 1e6
    assert pytest.approx(c.cost_usd, rel=1e-4) == expected


def test_openai_mixed_hit_write_miss_full_mixture():
    client = httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, content=_openai_tool_stream(
            cached=6000, cache_write=1000, prompt=3000, completion=20),
            headers={"content-type": "text/event-stream"})))
    be = OpenAIBackend(api_key="sk-test", client=client, price_in=2.5, price_out=10.0)
    c = be.complete([{"role": "user", "content": "hi"}])
    # uncached = 3000 - 6000? No: prompt_tokens counts ALL input; uncached = prompt - cached
    uncached = max(0, 3000 - 6000)  # 0 (cached can exceed prompt when writes counted)
    expected = (uncached * 2.5 + 6000 * 2.5 * 0.5 + 1000 * 2.5 * 1.25 + 20 * 10.0) / 1e6
    assert pytest.approx(c.cost_usd, rel=1e-4) == expected


# ---------------------------------------------------------- Anthropic TTL


def test_anthropic_5m_write_still_1_25x():
    client = httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, content=_anthropic_cached_stream(100, 500, 1000),
            headers={"content-type": "text/event-stream"})))
    be = AnthropicBackend(api_key="sk-ant", client=client, price_in=2.0, price_out=10.0)
    c = be.complete([{"role": "user", "content": "hi"}])
    expected = (1000 * 2.0 + 100 * 2.0 * 1.25 + 500 * 2.0 * 0.1 + 40 * 10.0) / 1e6
    assert pytest.approx(c.cost_usd, rel=1e-4) == expected


def test_anthropic_1h_write_at_2x():
    client = httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, content=_anthropic_cached_stream(100, 500, 1000),
            headers={"content-type": "text/event-stream"})))
    be = AnthropicBackend(api_key="sk-ant", client=client, price_in=2.0, price_out=10.0,
                          cache_ttl="1h")
    c = be.complete([{"role": "user", "content": "hi"}])
    expected = (1000 * 2.0 + 100 * 2.0 * 2.0 + 500 * 2.0 * 0.1 + 40 * 10.0) / 1e6
    assert pytest.approx(c.cost_usd, rel=1e-4) == expected


def test_openrouter_backend_carries_ttl_to_openai_dialect_pricing():
    client = httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, content=_openai_tool_stream(
            cached=0, cache_write=1000, prompt=1500, completion=50),
            headers={"content-type": "text/event-stream"})))
    be = OpenRouterBackend(model="openai/gpt-5.6-terra", api_key="sk-or",
                           client=client, price_in=2.0, price_out=12.0, cache_ttl="1h")
    c = be.complete([{"role": "user", "content": "hi"}])
    # uncached 1500 at full; writes 1000 at 2.0x (1h); output 50
    expected = (1500 * 2.0 + 1000 * 2.0 * 2.0 + 50 * 12.0) / 1e6
    assert pytest.approx(c.cost_usd, rel=1e-4) == expected


# ---------------------------------------------------------- GA headers


def test_no_stale_prompt_caching_beta_header():
    sent: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        sent.update(dict(request.headers))
        return httpx.Response(200, content=_anthropic_cached_stream(0, 0, 10),
                              headers={"content-type": "text/event-stream"})

    be = AnthropicBackend(api_key="sk-ant", client=httpx.Client(transport=httpx.MockTransport(handler)),
                          price_in=2.0, price_out=10.0)
    be.complete([{"role": "user", "content": "hi"}])
    assert "anthropic-beta" not in {k.lower() for k in sent}  # caching is GA — no beta header
    assert sent.get("x-api-key") == "sk-ant"
    assert sent.get("anthropic-version") == "2023-06-01"
