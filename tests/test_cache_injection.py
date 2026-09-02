"""C2 (#83) tests: breakpoint injection, stripping, session_id, minimum skip."""

import json

import httpx
import pytest

from kultivait.api_backends import (
    AnthropicBackend,
    OpenRouterBackend,
    apply_cache_policy,
    estimate_prefix_tokens,
    strip_client_cache_control,
)


def _capture_stream(handler_state):
    """Handler capturing the request body; returns a minimal OK SSE stream."""
    def handler(request: httpx.Request) -> httpx.Response:
        handler_state.append(json.loads(request.content.decode()))
        lines = [
            'data: {"choices":[{"index":0,"delta":{"content":"ok"}}]}',
            'data: {"choices":[],"usage":{"prompt_tokens":10,"completion_tokens":2}}',
            "data: [DONE]",
            "",
        ]
        return httpx.Response(200, content=("\n".join(c for l in lines for c in (l, "")) + "\n").encode(),
                              headers={"content-type": "text/event-stream"})
    return handler


BIG_SYSTEM = "You are a meticulous engineer. " * 300          # ~1,800 tokens
BIG_TOOLS = [{"type": "function", "function": {
    "name": f"tool_{i}", "description": "A tool with a long description. " * 20,
    "parameters": {"type": "object", "properties": {"a": {"type": "string"}}}}}
    for i in range(6)]                                        # >1,024 tokens combined
SMALL_SYSTEM = "Be terse."
SMALL_TOOLS = [{"type": "function", "function": {
    "name": "t", "description": "tiny", "parameters": {"type": "object", "properties": {}}}}]


# ---------------------------------------------------------------- pure helpers


def test_estimates_prefix_tokens_tools_plus_system():
    est = estimate_prefix_tokens(BIG_TOOLS, BIG_SYSTEM)
    assert est > 1024
    assert estimate_prefix_tokens(SMALL_TOOLS, SMALL_SYSTEM) < 1024


def test_strip_client_cache_control_removes_all_markers():
    tools = [{"type": "function", "function": {"name": "x", "parameters": {}},
              "cache_control": {"type": "ephemeral"}}]
    msgs = [{"role": "system", "content": "sys", "cache_control": {"type": "ephemeral"}},
            {"role": "user", "content": "u"}]
    t2, m2 = strip_client_cache_control(tools, msgs)
    assert "cache_control" not in json.dumps(t2)
    assert "cache_control" not in json.dumps(m2)


def test_apply_cache_policy_big_prefix_injects_both_levels():
    body = {"messages": [{"role": "user", "content": "hi"}], "system": BIG_SYSTEM,
            "tools": [dict(t) for t in BIG_TOOLS]}
    policy = apply_cache_policy(body, prefix_tokens=estimate_prefix_tokens(BIG_TOOLS, BIG_SYSTEM))
    # tools array: breakpoint on the LAST tool (prefix level 1, per ADR 0018 / #78)
    assert policy["tools"][-1].get("cache_control") == {"type": "ephemeral"}
    # system: block-level cache_control (explicit second level for multi-turn stability)
    assert policy["system"][0].get("cache_control") == {"type": "ephemeral"}
    # system became the Anthropic block form (list of blocks)
    assert policy["system"][0]["type"] == "text"


def test_apply_cache_policy_small_prefix_skips_silently():
    body = {"messages": [{"role": "user", "content": "hi"}], "system": SMALL_SYSTEM,
            "tools": [dict(t) for t in SMALL_TOOLS]}
    policy = apply_cache_policy(body, prefix_tokens=estimate_prefix_tokens(SMALL_TOOLS, SMALL_SYSTEM))
    assert all("cache_control" not in t for t in policy.get("tools", []))
    assert "cache_control" not in json.dumps(policy.get("system", ""))


def test_apply_cache_policy_adds_session_id():
    body = {"messages": [{"role": "user", "content": "hi"}], "system": BIG_SYSTEM,
            "tools": [dict(t) for t in BIG_TOOLS]}
    policy = apply_cache_policy(body, prefix_tokens=2000, session_id="fp123abc")
    assert policy["session_id"] == "fp123abc"


# ---------------------------------------------------------------- wire behavior: OpenRouter


def test_openrouter_sends_breakpoints_and_session_id():
    state = []
    be = OpenRouterBackend(model="anthropic/claude-sonnet-5", api_key="k",
                           client=httpx.Client(transport=httpx.MockTransport(_capture_stream(state))),
                           price_in=2.0, price_out=10.0)
    be.complete([{"role": "system", "content": BIG_SYSTEM},
                 {"role": "user", "content": "q"}],
                tools=BIG_TOOLS, fingerprint="fpXYZ789")
    body = state[0]
    assert body.get("session_id") == "fpXYZ789"
    assert body["tools"][-1].get("cache_control") == {"type": "ephemeral"}
    # OpenAI dialect: the system rides as the first message, block-marked
    sys_msg = body["messages"][0]
    assert sys_msg["role"] == "system" and isinstance(sys_msg["content"], list)
    assert sys_msg["content"][0].get("cache_control") == {"type": "ephemeral"}


def test_openrouter_small_prefix_no_injection_no_session():
    state = []
    be = OpenRouterBackend(model="anthropic/claude-sonnet-5", api_key="k",
                           client=httpx.Client(transport=httpx.MockTransport(_capture_stream(state))),
                           price_in=2.0, price_out=10.0)
    be.complete([{"role": "system", "content": SMALL_SYSTEM},
                 {"role": "user", "content": "q"}],
                tools=SMALL_TOOLS, fingerprint="fpSMALL")
    body = state[0]
    assert "session_id" not in body
    assert "cache_control" not in json.dumps(body.get("tools", []))


def test_client_cache_control_stripped_before_injection():
    state = []
    dirty_tools = [dict(SMALL_TOOLS[0]), dict(BIG_TOOLS[0])]
    dirty_tools[0]["cache_control"] = {"type": "ephemeral", "ttl": "1h"}
    dirty_msgs = [{"role": "system", "content": BIG_SYSTEM,
                   "cache_control": {"type": "ephemeral"}}]
    be = OpenRouterBackend(model="anthropic/claude-sonnet-5", api_key="k",
                           client=httpx.Client(transport=httpx.MockTransport(_capture_stream(state))),
                           price_in=2.0, price_out=10.0)
    be.complete(dirty_msgs + [{"role": "user", "content": "q"}],
                tools=dirty_tools, fingerprint="fpDIRTY")
    body = state[0]
    # client markers gone; only the proxy's canonical 5m markers remain
    assert body["tools"][0].get("cache_control") is None
    assert body["tools"][-1].get("cache_control") == {"type": "ephemeral"}
    sys_msg = body["messages"][0]
    assert sys_msg["content"][0].get("cache_control") == {"type": "ephemeral"}  # proxy canonical, 5m


# ---------------------------------------------------------------- direct Anthropic


def test_anthropic_direct_native_breakpoints():
    state = []
    be = AnthropicBackend(api_key="sk-ant",
                          client=httpx.Client(transport=httpx.MockTransport(_capture_stream(state))),
                          price_in=2.0, price_out=10.0)
    be.complete([{"role": "system", "content": BIG_SYSTEM},
                 {"role": "user", "content": "q"}],
                tools=BIG_TOOLS, fingerprint="fpANT")
    body = state[0]
    assert body["tools"][-1].get("cache_control") == {"type": "ephemeral"}
    assert isinstance(body["system"], list) and body["system"][0].get("cache_control") == {"type": "ephemeral"}
    assert "session_id" not in body  # session_id is OpenRouter-only


def test_1h_ttl_rides_the_canonical_markers():
    state = []
    be = OpenRouterBackend(model="anthropic/claude-sonnet-5", api_key="k",
                           client=httpx.Client(transport=httpx.MockTransport(_capture_stream(state))),
                           price_in=2.0, price_out=10.0, cache_ttl="1h")
    be.complete([{"role": "system", "content": BIG_SYSTEM},
                 {"role": "user", "content": "q"}],
                tools=BIG_TOOLS, fingerprint="fp1H")
    body = state[0]
    assert body["tools"][-1]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    sys_msg = body["messages"][0]
    assert sys_msg["content"][0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
