"""Direct REST API frontier provider backends: Anthropic, OpenAI, OpenRouter.

Conforms to Backend protocol with supports_tools = True, local = False.
Features per-dialect SSE event normalizers, buffered relay, aggressive same-target
retry on 429/529/5xx, per-provider effort self-projection, and dual-track cost accounting.
"""

from __future__ import annotations

import json
import os
import random
import time
from typing import Callable, Iterator

import httpx

from kultivait.backends import Completion
from kultivait.config import PROVIDER_DEFAULTS
from kultivait.credentials import resolve_provider_key

# ----------------------------------------------------------------------
# Errors
# ----------------------------------------------------------------------


class ApiError(Exception):
    def __init__(self, message: str, status_code: int = 500, retry_after: float | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


class ApiRetryableError(ApiError):
    """Retryable errors: 429, 529, 5xx, or network timeouts."""
    pass


class ApiNonRetryableError(ApiError):
    """Non-retryable errors: 400, 401, 403, 404, 422 (fail-fast)."""
    pass


# ----------------------------------------------------------------------
# Dialect & Schema Translation Pure Helpers (Seeded from #32 probe)
# ----------------------------------------------------------------------


def cc_tools_to_anthropic(tools: list[dict] | None) -> list[dict]:
    """Convert OpenAI/ChatCompletions function tools to Anthropic flat input_schema."""
    if not tools:
        return []
    out = []
    for t in tools:
        if "input_schema" in t:
            out.append(t)
        elif t.get("type") == "function" and "function" in t:
            fn = t["function"]
            out.append(
                {
                    "name": fn.get("name", ""),
                    "description": fn.get("description", ""),
                    "input_schema": fn.get("parameters", {}),
                }
            )
        else:
            out.append(t)
    return out


def anthropic_tools_to_openai(tools: list[dict] | None) -> list[dict]:
    """Convert Anthropic flat input_schema tools to OpenAI nested function tools."""
    if not tools:
        return []
    out = []
    for t in tools:
        if t.get("type") == "function" and "function" in t:
            out.append(t)
        elif "input_schema" in t:
            out.append(
                {
                    "type": "function",
                    "function": {
                        "name": t.get("name", ""),
                        "description": t.get("description", ""),
                        "parameters": t.get("input_schema", {}),
                    },
                }
            )
        else:
            out.append(t)
    return out


def cc_messages_to_anthropic(messages: list[dict]) -> tuple[list[dict], str]:
    """Convert OpenAI/CC-formatted messages to Anthropic messages + hoisted system string."""
    out: list[dict] = []
    system_parts: list[str] = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content")
        if role == "system":
            if isinstance(content, str) and content.strip():
                system_parts.append(content.strip())
            elif isinstance(content, list):
                for b in content:
                    if isinstance(b, dict) and b.get("text"):
                        system_parts.append(b["text"].strip())
                    elif isinstance(b, str) and b.strip():
                        system_parts.append(b.strip())
        elif role == "assistant" and m.get("tool_calls"):
            blocks: list[dict] = []
            if isinstance(content, str) and content:
                blocks.append({"type": "text", "text": content})
            elif isinstance(content, list):
                blocks.extend(content)
            for tc in m["tool_calls"]:
                fn = tc.get("function", {})
                args = fn.get("arguments")
                parsed_args = {}
                if isinstance(args, str):
                    try:
                        parsed_args = json.loads(args or "{}")
                    except Exception:
                        parsed_args = {}
                elif isinstance(args, dict):
                    parsed_args = args
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": tc.get("id", ""),
                        "name": fn.get("name", ""),
                        "input": parsed_args,
                    }
                )
            out.append({"role": "assistant", "content": blocks})
        elif role == "tool":
            out.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": m.get("tool_call_id", ""),
                            "content": content if isinstance(content, str) else json.dumps(content or ""),
                        }
                    ],
                }
            )
        else:
            out.append({"role": role, "content": content or ""})
    return out, "\n\n".join(system_parts)


def anthropic_messages_to_openai(messages: list[dict], system: str = "") -> list[dict]:
    """Convert Anthropic-formatted messages to OpenAI messages."""
    out: list[dict] = []
    if system:
        out.append({"role": "system", "content": system})
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content")
        if role == "assistant" and isinstance(content, list):
            text = ""
            calls = []
            for b in content:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text":
                    text += b.get("text", "")
                elif b.get("type") == "tool_use":
                    calls.append(
                        {
                            "id": b.get("id", ""),
                            "type": "function",
                            "function": {
                                "name": b.get("name", ""),
                                "arguments": json.dumps(b.get("input", {})),
                            },
                        }
                    )
            msg: dict = {"role": "assistant", "content": text or None}
            if calls:
                msg["tool_calls"] = calls
            out.append(msg)
        elif role == "user" and isinstance(content, list):
            for b in content:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "tool_result":
                    res_content = b.get("content", "")
                    if not isinstance(res_content, str):
                        res_content = json.dumps(res_content)
                    out.append(
                        {
                            "role": "tool",
                            "tool_call_id": b.get("tool_use_id", ""),
                            "content": res_content,
                        }
                    )
                elif b.get("type") == "text":
                    out.append({"role": "user", "content": b.get("text", "")})
        else:
            out.append({"role": role, "content": content or ""})
    return out


# ----------------------------------------------------------------------
# SSE Normalizer Iterator
# ----------------------------------------------------------------------


def iter_sse(resp: httpx.Response) -> Iterator[tuple[str | None, dict | None]]:
    """Iterate over SSE stream lines yielding (event_name, parsed_json_payload).
    Skips comment lines (e.g. OpenRouter `: OPENROUTER PROCESSING`) and [DONE]."""
    event = None
    data = []
    for line in resp.iter_lines():
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].strip())
        elif line == "" and data:
            payload = "\n".join(data)
            if payload != "[DONE]":
                try:
                    yield event, json.loads(payload)
                except json.JSONDecodeError:
                    pass
            event = None
            data = []
    if data:
        payload = "\n".join(data)
        if payload != "[DONE]":
            try:
                yield event, json.loads(payload)
            except json.JSONDecodeError:
                pass


# ----------------------------------------------------------------------
# Effort & Token Clamping Helpers
# ----------------------------------------------------------------------

OPENAI_EFFORT_MAP = {"fast": "low", "balanced": "medium", "deep": "xhigh"}
ANTHROPIC_EFFORT_MAP = {"fast": "low", "balanced": "medium", "deep": "high"}
OPENROUTER_EFFORT_MAP = {"fast": "low", "balanced": "medium", "deep": "xhigh"}


def extract_canonical_effort(
    effort_flags: list[str] | None,
    canonical_effort: str | None = None,
) -> str:
    """Extract canonical effort level ('fast' | 'balanced' | 'deep') from flags or kwarg."""
    if canonical_effort in ("fast", "balanced", "deep"):
        return canonical_effort
    if not effort_flags:
        return "balanced"
    flags_str = " ".join(effort_flags).lower()
    if "fast" in flags_str or "low" in flags_str:
        return "fast"
    if "deep" in flags_str or "high" in flags_str or "xhigh" in flags_str:
        return "deep"
    if "balanced" in flags_str or "medium" in flags_str:
        return "balanced"
    return "balanced"


def resolve_max_tokens(
    client_max_tokens: int | None,
    provider: str,
    canonical_effort: str,
) -> tuple[str, int]:
    """Resolve token field name and token limit per ADR 0008:
    - Never lower client-specified limit.
    - Default from PROVIDER_DEFAULTS.
    - Guarantee headroom (>= 16384) for deep effort.
    """
    defaults = PROVIDER_DEFAULTS.get(provider)
    if defaults:
        field_name = defaults.token_field
        table_default = defaults.max_output_tokens
    else:
        field_name = "max_tokens" if provider != "openai" else "max_completion_tokens"
        table_default = 8192 if provider != "openai" else 16384

    if client_max_tokens is not None and client_max_tokens > 0:
        token_limit = client_max_tokens
    else:
        token_limit = table_default

    if canonical_effort == "deep" and token_limit < 16384:
        token_limit = 16384

    return field_name, token_limit


# ----------------------------------------------------------------------
# Retry & Buffered Relay Core
# ----------------------------------------------------------------------


def _parse_retry_after(headers: httpx.Headers) -> float | None:
    val = headers.get("retry-after") or headers.get("Retry-After")
    if val:
        try:
            return float(val)
        except ValueError:
            pass
    reset = headers.get("x-ratelimit-reset") or headers.get("X-RateLimit-Reset")
    if reset:
        try:
            r = float(reset)
            if r > 1e9:
                return max(0.0, r - time.time())
            return max(0.0, r)
        except ValueError:
            pass
    ms = headers.get("retry-after-ms")
    if ms:
        try:
            return float(ms) / 1000.0
        except ValueError:
            pass
    return None


def execute_with_retry(
    request_fn: Callable[[], tuple[str, list[str], list[dict] | None, dict]],
    max_attempts: int = 5,
    max_total_budget_s: float = 120.0,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> tuple[str, list[str], list[dict] | None, dict]:
    """Execute request_fn with aggressive retry (up to max_attempts) on 429/529/5xx and network errors."""
    total_slept = 0.0
    for attempt in range(1, max_attempts + 1):
        try:
            return request_fn()
        except ApiRetryableError as e:
            if attempt >= max_attempts:
                raise
            retry_after = e.retry_after
            if retry_after is not None and retry_after > 0:
                wait_s = retry_after
            else:
                wait_s = (1.0 * (2 ** (attempt - 1))) + random.uniform(0.0, 0.5)

            if total_slept + wait_s > max_total_budget_s:
                raise
            total_slept += wait_s
            sleep_fn(wait_s)
        except httpx.RequestError as e:
            if attempt >= max_attempts:
                raise ApiNonRetryableError(f"Connection error: {e}") from e
            wait_s = (1.0 * (2 ** (attempt - 1))) + random.uniform(0.0, 0.5)
            if total_slept + wait_s > max_total_budget_s:
                raise
            total_slept += wait_s
            sleep_fn(wait_s)


# ----------------------------------------------------------------------
# 1. AnthropicBackend
# ----------------------------------------------------------------------


class AnthropicBackend:
    supports_tools: bool = True
    local: bool = False

    def __init__(
        self,
        model: str = "claude-3-7-sonnet-20250219",
        api_key: str | None = None,
        price_in: float = 3.0,
        price_out: float = 15.0,
        base_url: str = "https://api.anthropic.com/v1",
        client: httpx.Client | None = None,
        timeout_s: float = 90.0,
        **kwargs,
    ):
        self.model = model
        self.api_key = api_key
        self.price_in = price_in
        self.price_out = price_out
        self.base_url = base_url.rstrip("/")
        self.client = client
        self.timeout_s = timeout_s
        self.effort_flags_seen: list[list[str]] = []

    def _get_key(self) -> str:
        key = self.api_key or resolve_provider_key("anthropic")
        if not key:
            raise ApiNonRetryableError("No Anthropic API key configured (env, keychain, or credentials.toml)")
        return key

    def _execute_turn(
        self,
        client: httpx.Client,
        body: dict,
        headers: dict,
    ) -> tuple[str, list[str], list[dict] | None, dict]:
        url = f"{self.base_url}/messages"
        with client.stream("POST", url, json=body, headers=headers, timeout=self.timeout_s) as r:
            if r.status_code != 200:
                err_text = r.read().decode("utf-8", errors="replace")[:500]
                retry_after = _parse_retry_after(r.headers)
                if r.status_code in (429, 529, 500, 502, 503, 504):
                    raise ApiRetryableError(
                        f"Anthropic HTTP {r.status_code}: {err_text}",
                        status_code=r.status_code,
                        retry_after=retry_after,
                    )
                raise ApiNonRetryableError(
                    f"Anthropic HTTP {r.status_code}: {err_text}",
                    status_code=r.status_code,
                )

            text_parts: list[str] = []
            blocks: dict[int, dict] = {}
            usage: dict = {}

            for event, data in iter_sse(r):
                if not data:
                    continue
                t = data.get("type", event)
                if t == "error":
                    err_info = data.get("error", {})
                    raise ApiNonRetryableError(f"Anthropic stream error: {err_info}")
                elif t == "message_start":
                    msg = data.get("message", {})
                    usage.update(msg.get("usage", {}))
                elif t == "content_block_start":
                    idx = data.get("index", len(blocks))
                    b = data.get("content_block", {})
                    blocks[idx] = dict(b)
                    if b.get("type") == "tool_use":
                        blocks[idx]["_args"] = ""
                elif t == "content_block_delta":
                    idx = data.get("index", 0)
                    d = data.get("delta", {})
                    if d.get("type") == "text_delta":
                        t_delta = d.get("text", "")
                        text_parts.append(t_delta)
                    elif d.get("type") == "input_json_delta":
                        blocks.setdefault(idx, {"type": "tool_use", "_args": ""})
                        blocks[idx]["_args"] = blocks[idx].get("_args", "") + d.get("partial_json", "")
                elif t == "message_delta":
                    usage.update(data.get("usage", {}))

            tool_calls = []
            for b in blocks.values():
                if b.get("type") == "tool_use":
                    tool_calls.append(
                        {
                            "id": b.get("id", ""),
                            "type": "function",
                            "function": {
                                "name": b.get("name", ""),
                                "arguments": b.get("_args", "{}"),
                            },
                        }
                    )

            return "".join(text_parts), text_parts, tool_calls or None, usage

    def complete(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        effort_flags: list[str] | None = None,
        model_override: str | None = None,
        canonical_effort: str | None = None,
        max_tokens: int | None = None,
        **kwargs,
    ) -> Completion:
        if effort_flags:
            self.effort_flags_seen.append(list(effort_flags))

        api_key = self._get_key()
        can_eff = extract_canonical_effort(effort_flags, canonical_effort)
        prov_eff = ANTHROPIC_EFFORT_MAP.get(can_eff, "medium")
        tok_field, tok_limit = resolve_max_tokens(max_tokens, "anthropic", can_eff)

        a_msgs, system = cc_messages_to_anthropic(messages)
        a_tools = cc_tools_to_anthropic(tools)

        body: dict = {
            "model": model_override or self.model,
            "messages": a_msgs,
            tok_field: tok_limit,
            "stream": True,
        }
        if system:
            body["system"] = system
        if a_tools:
            body["tools"] = a_tools
        if prov_eff:
            body["output_config"] = {"effort": prov_eff}

        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        http_client = self.client or httpx.Client(timeout=self.timeout_s)
        try:
            text, _, tool_calls, usage = execute_with_retry(
                lambda: self._execute_turn(http_client, body, headers)
            )
        finally:
            if not self.client:
                http_client.close()

        input_toks = int(usage.get("input_tokens", 0))
        cache_create = int(usage.get("cache_creation_input_tokens", 0))
        cache_read = int(usage.get("cache_read_input_tokens", 0))
        output_toks = int(usage.get("output_tokens", 0))
        total_tokens_in = input_toks + cache_create + cache_read
        total_tokens_out = output_toks

        cost_usd = (
            input_toks * self.price_in
            + cache_create * (self.price_in * 1.25)
            + cache_read * (self.price_in * 0.1)
            + output_toks * self.price_out
        ) / 1e6

        return Completion(
            text=text,
            tokens_in=total_tokens_in,
            tokens_out=total_tokens_out,
            cost_usd=cost_usd,
            local=False,
            tool_calls=tool_calls,
        )

    def stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        effort_flags: list[str] | None = None,
        model_override: str | None = None,
        canonical_effort: str | None = None,
        max_tokens: int | None = None,
        **kwargs,
    ) -> Iterator[str | Completion]:
        if effort_flags:
            self.effort_flags_seen.append(list(effort_flags))

        api_key = self._get_key()
        can_eff = extract_canonical_effort(effort_flags, canonical_effort)
        prov_eff = ANTHROPIC_EFFORT_MAP.get(can_eff, "medium")
        tok_field, tok_limit = resolve_max_tokens(max_tokens, "anthropic", can_eff)

        a_msgs, system = cc_messages_to_anthropic(messages)
        a_tools = cc_tools_to_anthropic(tools)

        body: dict = {
            "model": model_override or self.model,
            "messages": a_msgs,
            tok_field: tok_limit,
            "stream": True,
        }
        if system:
            body["system"] = system
        if a_tools:
            body["tools"] = a_tools
        if prov_eff:
            body["output_config"] = {"effort": prov_eff}

        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        http_client = self.client or httpx.Client(timeout=self.timeout_s)
        try:
            text, text_deltas, tool_calls, usage = execute_with_retry(
                lambda: self._execute_turn(http_client, body, headers)
            )
        finally:
            if not self.client:
                http_client.close()

        for delta in text_deltas:
            if delta:
                yield delta

        input_toks = int(usage.get("input_tokens", 0))
        cache_create = int(usage.get("cache_creation_input_tokens", 0))
        cache_read = int(usage.get("cache_read_input_tokens", 0))
        output_toks = int(usage.get("output_tokens", 0))
        total_tokens_in = input_toks + cache_create + cache_read
        total_tokens_out = output_toks

        cost_usd = (
            input_toks * self.price_in
            + cache_create * (self.price_in * 1.25)
            + cache_read * (self.price_in * 0.1)
            + output_toks * self.price_out
        ) / 1e6

        yield Completion(
            text=text,
            tokens_in=total_tokens_in,
            tokens_out=total_tokens_out,
            cost_usd=cost_usd,
            local=False,
            tool_calls=tool_calls,
        )


# ----------------------------------------------------------------------
# 2. OpenAIBackend
# ----------------------------------------------------------------------


class OpenAIBackend:
    supports_tools: bool = True
    local: bool = False

    def __init__(
        self,
        model: str = "gpt-4o",
        api_key: str | None = None,
        price_in: float = 2.5,
        price_out: float = 10.0,
        base_url: str = "https://api.openai.com/v1",
        client: httpx.Client | None = None,
        timeout_s: float = 90.0,
        **kwargs,
    ):
        self.model = model
        self.api_key = api_key
        self.price_in = price_in
        self.price_out = price_out
        self.base_url = base_url.rstrip("/")
        self.client = client
        self.timeout_s = timeout_s
        self.effort_flags_seen: list[list[str]] = []

    def _get_key(self) -> str:
        key = self.api_key or resolve_provider_key("openai")
        if not key:
            raise ApiNonRetryableError("No OpenAI API key configured (env, keychain, or credentials.toml)")
        return key

    def _execute_turn(
        self,
        client: httpx.Client,
        body: dict,
        headers: dict,
    ) -> tuple[str, list[str], list[dict] | None, dict]:
        url = f"{self.base_url}/chat/completions"
        with client.stream("POST", url, json=body, headers=headers, timeout=self.timeout_s) as r:
            if r.status_code != 200:
                err_text = r.read().decode("utf-8", errors="replace")[:500]
                retry_after = _parse_retry_after(r.headers)
                if r.status_code in (429, 500, 502, 503, 504):
                    raise ApiRetryableError(
                        f"OpenAI HTTP {r.status_code}: {err_text}",
                        status_code=r.status_code,
                        retry_after=retry_after,
                    )
                raise ApiNonRetryableError(
                    f"OpenAI HTTP {r.status_code}: {err_text}",
                    status_code=r.status_code,
                )

            text_parts: list[str] = []
            calls: dict[int, dict] = {}
            usage: dict = {}

            for event, data in iter_sse(r):
                if not data:
                    continue
                if "error" in data:
                    raise ApiNonRetryableError(f"OpenAI stream error: {data['error']}")
                if data.get("usage"):
                    usage.update(data["usage"])
                for ch in data.get("choices", []):
                    delta = ch.get("delta", {})
                    c_text = delta.get("content") or ""
                    if c_text:
                        text_parts.append(c_text)
                    for tc in delta.get("tool_calls") or []:
                        idx = tc.get("index", 0)
                        slot = calls.setdefault(
                            idx,
                            {"id": "", "name": "", "_args": ""},
                        )
                        if tc.get("id"):
                            slot["id"] = tc["id"]
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            slot["name"] += fn["name"]
                        if fn.get("arguments"):
                            slot["_args"] += fn["arguments"]

            tool_calls = [
                {
                    "id": c["id"],
                    "type": "function",
                    "function": {"name": c["name"], "arguments": c["_args"]},
                }
                for c in calls.values()
            ]

            return "".join(text_parts), text_parts, tool_calls or None, usage

    def complete(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        effort_flags: list[str] | None = None,
        model_override: str | None = None,
        canonical_effort: str | None = None,
        max_tokens: int | None = None,
        **kwargs,
    ) -> Completion:
        if effort_flags:
            self.effort_flags_seen.append(list(effort_flags))

        api_key = self._get_key()
        can_eff = extract_canonical_effort(effort_flags, canonical_effort)
        prov_eff = OPENAI_EFFORT_MAP.get(can_eff, "medium")
        tok_field, tok_limit = resolve_max_tokens(max_tokens, "openai", can_eff)

        o_msgs = anthropic_messages_to_openai(messages)
        o_tools = anthropic_tools_to_openai(tools)

        body: dict = {
            "model": model_override or self.model,
            "messages": o_msgs,
            tok_field: tok_limit,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if o_tools:
            body["tools"] = o_tools
        if prov_eff:
            body["reasoning_effort"] = prov_eff

        headers = {
            "Authorization": f"Bearer {api_key}",
            "content-type": "application/json",
        }

        http_client = self.client or httpx.Client(timeout=self.timeout_s)
        try:
            text, _, tool_calls, usage = execute_with_retry(
                lambda: self._execute_turn(http_client, body, headers)
            )
        finally:
            if not self.client:
                http_client.close()

        prompt_toks = int(usage.get("prompt_tokens", len(json.dumps(o_msgs)) // 4))
        comp_toks = int(usage.get("completion_tokens", len(text) // 4))
        cost_usd = (prompt_toks * self.price_in + comp_toks * self.price_out) / 1e6

        return Completion(
            text=text,
            tokens_in=prompt_toks,
            tokens_out=comp_toks,
            cost_usd=cost_usd,
            local=False,
            tool_calls=tool_calls,
        )

    def stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        effort_flags: list[str] | None = None,
        model_override: str | None = None,
        canonical_effort: str | None = None,
        max_tokens: int | None = None,
        **kwargs,
    ) -> Iterator[str | Completion]:
        if effort_flags:
            self.effort_flags_seen.append(list(effort_flags))

        api_key = self._get_key()
        can_eff = extract_canonical_effort(effort_flags, canonical_effort)
        prov_eff = OPENAI_EFFORT_MAP.get(can_eff, "medium")
        tok_field, tok_limit = resolve_max_tokens(max_tokens, "openai", can_eff)

        o_msgs = anthropic_messages_to_openai(messages)
        o_tools = anthropic_tools_to_openai(tools)

        body: dict = {
            "model": model_override or self.model,
            "messages": o_msgs,
            tok_field: tok_limit,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if o_tools:
            body["tools"] = o_tools
        if prov_eff:
            body["reasoning_effort"] = prov_eff

        headers = {
            "Authorization": f"Bearer {api_key}",
            "content-type": "application/json",
        }

        http_client = self.client or httpx.Client(timeout=self.timeout_s)
        try:
            text, text_deltas, tool_calls, usage = execute_with_retry(
                lambda: self._execute_turn(http_client, body, headers)
            )
        finally:
            if not self.client:
                http_client.close()

        for delta in text_deltas:
            if delta:
                yield delta

        prompt_toks = int(usage.get("prompt_tokens", len(json.dumps(o_msgs)) // 4))
        comp_toks = int(usage.get("completion_tokens", len(text) // 4))
        cost_usd = (prompt_toks * self.price_in + comp_toks * self.price_out) / 1e6

        yield Completion(
            text=text,
            tokens_in=prompt_toks,
            tokens_out=comp_toks,
            cost_usd=cost_usd,
            local=False,
            tool_calls=tool_calls,
        )


# ----------------------------------------------------------------------
# 3. OpenRouterBackend
# ----------------------------------------------------------------------


class OpenRouterBackend:
    supports_tools: bool = True
    local: bool = False

    def __init__(
        self,
        model: str = "anthropic/claude-3.7-sonnet",
        api_key: str | None = None,
        price_in: float = 3.0,
        price_out: float = 15.0,
        base_url: str = "https://openrouter.ai/api/v1",
        client: httpx.Client | None = None,
        timeout_s: float = 90.0,
        **kwargs,
    ):
        self.model = model
        self.api_key = api_key
        self.price_in = price_in
        self.price_out = price_out
        self.base_url = base_url.rstrip("/")
        self.client = client
        self.timeout_s = timeout_s
        self.effort_flags_seen: list[list[str]] = []

    def _get_key(self) -> str:
        key = self.api_key or resolve_provider_key("openrouter")
        if not key:
            raise ApiNonRetryableError("No OpenRouter API key configured (env, keychain, or credentials.toml)")
        return key

    def _execute_turn(
        self,
        client: httpx.Client,
        body: dict,
        headers: dict,
    ) -> tuple[str, list[str], list[dict] | None, dict]:
        url = f"{self.base_url}/chat/completions"
        with client.stream("POST", url, json=body, headers=headers, timeout=self.timeout_s) as r:
            if r.status_code != 200:
                err_text = r.read().decode("utf-8", errors="replace")[:500]
                retry_after = _parse_retry_after(r.headers)
                if r.status_code in (429, 500, 502, 503, 504):
                    raise ApiRetryableError(
                        f"OpenRouter HTTP {r.status_code}: {err_text}",
                        status_code=r.status_code,
                        retry_after=retry_after,
                    )
                raise ApiNonRetryableError(
                    f"OpenRouter HTTP {r.status_code}: {err_text}",
                    status_code=r.status_code,
                )

            text_parts: list[str] = []
            calls: dict[int, dict] = {}
            usage: dict = {}

            for event, data in iter_sse(r):
                if not data:
                    continue
                if "error" in data:
                    err_val = data["error"]
                    err_code = err_val.get("code") if isinstance(err_val, dict) else 500
                    if err_code in (429, 500, 502, 503, 504):
                        raise ApiRetryableError(f"OpenRouter inline stream error: {err_val}", status_code=err_code)
                    raise ApiNonRetryableError(f"OpenRouter inline stream error: {err_val}")

                if data.get("usage"):
                    usage.update(data["usage"])
                for ch in data.get("choices", []):
                    delta = ch.get("delta", {})
                    c_text = delta.get("content") or ""
                    if c_text:
                        text_parts.append(c_text)
                    for tc in delta.get("tool_calls") or []:
                        idx = tc.get("index", 0)
                        slot = calls.setdefault(
                            idx,
                            {"id": "", "name": "", "_args": ""},
                        )
                        if tc.get("id"):
                            slot["id"] = tc["id"]
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            slot["name"] += fn["name"]
                        if fn.get("arguments"):
                            slot["_args"] += fn["arguments"]

            tool_calls = [
                {
                    "id": c["id"],
                    "type": "function",
                    "function": {"name": c["name"], "arguments": c["_args"]},
                }
                for c in calls.values()
            ]

            return "".join(text_parts), text_parts, tool_calls or None, usage

    def complete(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        effort_flags: list[str] | None = None,
        model_override: str | None = None,
        canonical_effort: str | None = None,
        max_tokens: int | None = None,
        **kwargs,
    ) -> Completion:
        if effort_flags:
            self.effort_flags_seen.append(list(effort_flags))

        api_key = self._get_key()
        can_eff = extract_canonical_effort(effort_flags, canonical_effort)
        prov_eff = OPENROUTER_EFFORT_MAP.get(can_eff, "medium")
        tok_field, tok_limit = resolve_max_tokens(max_tokens, "openrouter", can_eff)

        o_msgs = anthropic_messages_to_openai(messages)
        o_tools = anthropic_tools_to_openai(tools)

        body: dict = {
            "model": model_override or self.model,
            "messages": o_msgs,
            tok_field: tok_limit,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if o_tools:
            body["tools"] = o_tools
        if prov_eff:
            body["reasoning_effort"] = prov_eff

        headers = {
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": "https://kultivait.local",
            "X-Title": "kultivait",
            "content-type": "application/json",
        }

        http_client = self.client or httpx.Client(timeout=self.timeout_s)
        try:
            text, _, tool_calls, usage = execute_with_retry(
                lambda: self._execute_turn(http_client, body, headers)
            )
        finally:
            if not self.client:
                http_client.close()

        prompt_toks = int(usage.get("prompt_tokens", len(json.dumps(o_msgs)) // 4))
        comp_toks = int(usage.get("completion_tokens", len(text) // 4))

        if "cost" in usage and usage["cost"] is not None:
            cost_usd = float(usage["cost"])
        else:
            cost_usd = (prompt_toks * self.price_in + comp_toks * self.price_out) / 1e6

        return Completion(
            text=text,
            tokens_in=prompt_toks,
            tokens_out=comp_toks,
            cost_usd=cost_usd,
            local=False,
            tool_calls=tool_calls,
        )

    def stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        effort_flags: list[str] | None = None,
        model_override: str | None = None,
        canonical_effort: str | None = None,
        max_tokens: int | None = None,
        **kwargs,
    ) -> Iterator[str | Completion]:
        if effort_flags:
            self.effort_flags_seen.append(list(effort_flags))

        api_key = self._get_key()
        can_eff = extract_canonical_effort(effort_flags, canonical_effort)
        prov_eff = OPENROUTER_EFFORT_MAP.get(can_eff, "medium")
        tok_field, tok_limit = resolve_max_tokens(max_tokens, "openrouter", can_eff)

        o_msgs = anthropic_messages_to_openai(messages)
        o_tools = anthropic_tools_to_openai(tools)

        body: dict = {
            "model": model_override or self.model,
            "messages": o_msgs,
            tok_field: tok_limit,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if o_tools:
            body["tools"] = o_tools
        if prov_eff:
            body["reasoning_effort"] = prov_eff

        headers = {
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": "https://kultivait.local",
            "X-Title": "kultivait",
            "content-type": "application/json",
        }

        http_client = self.client or httpx.Client(timeout=self.timeout_s)
        try:
            text, text_deltas, tool_calls, usage = execute_with_retry(
                lambda: self._execute_turn(http_client, body, headers)
            )
        finally:
            if not self.client:
                http_client.close()

        for delta in text_deltas:
            if delta:
                yield delta

        prompt_toks = int(usage.get("prompt_tokens", len(json.dumps(o_msgs)) // 4))
        comp_toks = int(usage.get("completion_tokens", len(text) // 4))

        if "cost" in usage and usage["cost"] is not None:
            cost_usd = float(usage["cost"])
        else:
            cost_usd = (prompt_toks * self.price_in + comp_toks * self.price_out) / 1e6

        yield Completion(
            text=text,
            tokens_in=prompt_toks,
            tokens_out=comp_toks,
            cost_usd=cost_usd,
            local=False,
            tool_calls=tool_calls,
        )
