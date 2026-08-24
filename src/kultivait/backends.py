"""Model backends: local runtimes (ollama, llama.cpp) and cloud CLIs,
behind one interface.

`stream()` yields text deltas and finishes with a Completion carrying the
final usage, so callers can tally the ledger after the stream ends.
"""

import json
import os
from dataclasses import dataclass
from typing import Iterator, Protocol, runtime_checkable

DISPATCH_TEMPLATES: dict[str, list[str]] = {
    "claude": ["claude", "-p"],
    "agy": ["agy", "-p"],
    "gemini": ["gemini", "-p"],
    "codex": ["codex", "exec"],
    "opencode": ["opencode", "run"],
}

PROXY_ENV_STRIP: list[str] = [
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_API_URL",
    "OPENAI_BASE_URL",
    "OPENAI_API_BASE",
    "OPENAI_PROXY_URL",
]


@dataclass(frozen=True)
class Completion:
    text: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    local: bool
    tool_calls: "list[dict] | None" = None
    truncated: bool = False


def is_truncated(prompt_eval_count: int, num_ctx: int) -> bool:
    """ollama silently clips over-long prompts to num_ctx - 1 tokens, keeping
    the tail and amputating the head (system prompts, skill instructions).
    A prompt_eval_count pinned at the boundary is the tell."""
    return prompt_eval_count >= num_ctx - 1


@runtime_checkable
class Backend(Protocol):
    supports_tools: bool
    local: bool

    def complete(
        self,
        messages: list[dict],
        tools: "list[dict] | None" = None,
        effort_flags: "list[str] | None" = None,
        model_override: "str | None" = None,
    ) -> Completion: ...

    def stream(
        self,
        messages: list[dict],
        tools: "list[dict] | None" = None,
        effort_flags: "list[str] | None" = None,
        model_override: "str | None" = None,
    ) -> Iterator["str | Completion"]: ...


def to_ollama_messages(messages: list[dict]) -> list[dict]:
    """OpenAI-format history -> ollama native format: tool-call arguments
    become dicts, and OpenAI's id plumbing (ids, tool_call_id) is dropped."""
    out = []
    for m in messages:
        norm = {"role": m.get("role", "user"), "content": m.get("content") or ""}
        if m.get("tool_calls"):
            norm["tool_calls"] = [
                {
                    "function": {
                        "name": tc["function"]["name"],
                        "arguments": json.loads(tc["function"]["arguments"])
                        if isinstance(tc["function"].get("arguments"), str)
                        else tc["function"].get("arguments", {}),
                    }
                }
                for tc in m["tool_calls"]
            ]
        out.append(norm)
    return out


def from_ollama_tool_calls(tool_calls: list[dict]) -> list[dict]:
    """ollama tool calls -> OpenAI format: dict arguments become JSON strings,
    and ids are generated (ollama doesn't issue them)."""
    import uuid

    return [
        {
            "id": f"call_{uuid.uuid4().hex[:8]}",
            "type": "function",
            "function": {
                "name": tc["function"]["name"],
                "arguments": json.dumps(tc["function"].get("arguments", {})),
            },
        }
        for tc in tool_calls
    ]


class OllamaBackend:
    """Local model via the ollama chat API. Free by definition."""

    supports_tools = True
    local = True

    def __init__(
        self, model: str, base_url: str = "http://localhost:11434", num_ctx: int = 32768
    ):
        self.model = model
        self.base_url = base_url
        self.num_ctx = num_ctx

    def _payload(self, messages: list[dict], tools: "list[dict] | None", stream: bool) -> dict:
        # ollama defaults to a small context and silently truncates longer
        # prompts; agent clients send envelopes well past the default, so
        # classification would run on a prompt the model never fully sees.
        payload = {
            "model": self.model,
            "messages": to_ollama_messages(messages),
            "stream": stream,
            "options": {"num_ctx": self.num_ctx},
        }
        if tools:
            payload["tools"] = tools
        return payload

    def complete(
        self,
        messages: list[dict],
        tools: "list[dict] | None" = None,
        effort_flags: "list[str] | None" = None,
        model_override: "str | None" = None,
        **kwargs,
    ) -> Completion:
        import httpx

        r = httpx.post(
            f"{self.base_url}/api/chat",
            json=self._payload(messages, tools, stream=False),
            timeout=300,
        )
        r.raise_for_status()
        data = r.json()
        raw_calls = data["message"].get("tool_calls") or []
        tokens_in = data.get("prompt_eval_count", 0)
        return Completion(
            text=data["message"]["content"],
            tokens_in=tokens_in,
            tokens_out=data.get("eval_count", 0),
            cost_usd=0.0,
            local=True,
            tool_calls=from_ollama_tool_calls(raw_calls) if raw_calls else None,
            truncated=is_truncated(tokens_in, self.num_ctx),
        )

    def stream(
        self,
        messages: list[dict],
        tools: "list[dict] | None" = None,
        effort_flags: "list[str] | None" = None,
        model_override: "str | None" = None,
        **kwargs,
    ) -> Iterator["str | Completion"]:
        import httpx

        parts: list[str] = []
        raw_calls: list[dict] = []
        with httpx.stream(
            "POST",
            f"{self.base_url}/api/chat",
            json=self._payload(messages, tools, stream=True),
            timeout=300,
        ) as r:
            r.raise_for_status()
            data = {}
            for line in r.iter_lines():
                if not line.strip():
                    continue
                data = json.loads(line)
                message = data.get("message", {})
                raw_calls.extend(message.get("tool_calls") or [])
                delta = message.get("content", "")
                if delta:
                    parts.append(delta)
                    yield delta
        tokens_in = data.get("prompt_eval_count", 0)
        yield Completion(
            text="".join(parts),
            tokens_in=tokens_in,
            tokens_out=data.get("eval_count", 0),
            cost_usd=0.0,
            local=True,
            tool_calls=from_ollama_tool_calls(raw_calls) if raw_calls else None,
            truncated=is_truncated(tokens_in, self.num_ctx),
        )


def merge_tool_call_deltas(acc: "dict[int, dict]", deltas: "list[dict]") -> None:
    """OpenAI streaming splits each tool call across chunks, keyed by index:
    the first fragment carries id/name, later ones append argument text."""
    for d in deltas:
        slot = acc.setdefault(
            d.get("index", 0),
            {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
        )
        if d.get("id"):
            slot["id"] = d["id"]
        fn = d.get("function") or {}
        if fn.get("name"):
            slot["function"]["name"] += fn["name"]
        if fn.get("arguments"):
            slot["function"]["arguments"] += fn["arguments"]


class LlamaCppBackend:
    """Local model via llama-server's OpenAI-compatible API. Free by definition.

    Speaks OpenAI format natively, so no message or tool-call translation.
    Context size is fixed at server launch (--ctx-size), not per request, and
    llama.cpp doesn't pin token counts when clipping, so truncation detection
    (an ollama quirk) is unavailable: `truncated` is always False. Tool calls
    require the server to be launched with --jinja. In router mode the
    request's `model` field selects which model the server loads.
    """

    supports_tools = True
    local = True

    def __init__(self, model: str, base_url: str = "http://localhost:8080"):
        self.model = model
        self.base_url = base_url

    def _payload(self, messages: list[dict], tools: "list[dict] | None", stream: bool) -> dict:
        payload = {"model": self.model, "messages": messages, "stream": stream}
        if tools:
            payload["tools"] = tools
        return payload

    @staticmethod
    def _parse(data: dict) -> Completion:
        message = data["choices"][0]["message"]
        usage = data.get("usage") or {}
        return Completion(
            text=message.get("content") or "",
            tokens_in=usage.get("prompt_tokens", 0),
            tokens_out=usage.get("completion_tokens", 0),
            cost_usd=0.0,
            local=True,
            tool_calls=message.get("tool_calls") or None,
            truncated=False,
        )

    def complete(
        self,
        messages: list[dict],
        tools: "list[dict] | None" = None,
        effort_flags: "list[str] | None" = None,
        model_override: "str | None" = None,
        **kwargs,
    ) -> Completion:
        import httpx

        r = httpx.post(
            f"{self.base_url}/v1/chat/completions",
            json=self._payload(messages, tools, stream=False),
            timeout=300,
        )
        r.raise_for_status()
        return self._parse(r.json())

    def stream(
        self,
        messages: list[dict],
        tools: "list[dict] | None" = None,
        effort_flags: "list[str] | None" = None,
        model_override: "str | None" = None,
        **kwargs,
    ) -> Iterator["str | Completion"]:
        import httpx

        parts: list[str] = []
        calls: dict[int, dict] = {}
        usage: dict = {}
        payload = self._payload(messages, tools, stream=True)
        payload["stream_options"] = {"include_usage": True}
        with httpx.stream(
            "POST",
            f"{self.base_url}/v1/chat/completions",
            json=payload,
            timeout=300,
        ) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                body = line[len("data:"):].strip()
                if body == "[DONE]":
                    break
                chunk = json.loads(body)
                if chunk.get("usage"):
                    usage = chunk["usage"]
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                merge_tool_call_deltas(calls, delta.get("tool_calls") or [])
                text = delta.get("content") or ""
                if text:
                    parts.append(text)
                    yield text
            tool_calls = [calls[i] for i in sorted(calls)] or None
            yield Completion(
                text="".join(parts),
                tokens_in=usage.get("prompt_tokens", 0),
                tokens_out=usage.get("completion_tokens", 0),
                cost_usd=0.0,
                local=True,
                tool_calls=tool_calls,
                truncated=False,
            )


def _parse_claude_json(
    stdout: str, prompt: str, price_in: float, price_out: float
) -> tuple[str, int, int, float] | None:
    try:
        data = json.loads(stdout.strip())
        if not isinstance(data, dict):
            return None
        if data.get("is_error"):
            err_msg = data.get("result") or data.get("error") or "claude reported error"
            raise RuntimeError(f"claude error: {err_msg}")
        text = str(data.get("result", ""))
        usage = data.get("usage", {})
        tokens_in = int(usage.get("input_tokens", max(1, len(prompt) // 4)))
        tokens_out = int(usage.get("output_tokens", max(1, len(text) // 4)))
        total_cost = data.get("total_cost_usd")
        if total_cost is not None and float(total_cost) > 0:
            cost_usd = float(total_cost)
        else:
            cost_usd = (tokens_in * price_in + tokens_out * price_out) / 1e6
        return text, tokens_in, tokens_out, cost_usd
    except RuntimeError:
        raise
    except Exception:
        return None


def _parse_codex_jsonl(
    stdout: str, prompt: str, price_in: float, price_out: float
) -> tuple[str, int, int, float] | None:
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    if not lines:
        return None
    assistant_texts: list[str] = []
    tokens_in = None
    tokens_out = None

    for line in lines:
        try:
            event = json.loads(line)
        except Exception:
            continue
        if not isinstance(event, dict):
            continue

        if event.get("type") == "error":
            err = event.get("message") or event.get("error") or "codex error"
            raise RuntimeError(f"codex error: {err}")

        item = event.get("item") or event
        if isinstance(item, dict):
            role = item.get("role")
            content = item.get("content")
            if role == "assistant" and content:
                if isinstance(content, str):
                    assistant_texts.append(content)
                elif isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict) and part.get("text"):
                            assistant_texts.append(part["text"])
                        elif isinstance(part, str):
                            assistant_texts.append(part)
            elif item.get("type") == "agent_message" and item.get("text"):
                assistant_texts.append(item["text"])
            elif item.get("type") == "message" and role == "assistant":
                if item.get("text"):
                    assistant_texts.append(item["text"])

        usage = event.get("usage")
        if isinstance(usage, dict):
            inp = usage.get("input", usage.get("input_tokens", 0))
            cached = usage.get("cached", usage.get("cached_tokens", 0))
            out = usage.get("output", usage.get("output_tokens", 0))
            tokens_in = int(inp) + int(cached)
            tokens_out = int(out)

    if tokens_in is None and not assistant_texts:
        return None

    text = "\n".join(assistant_texts).strip() if assistant_texts else stdout.strip()
    if tokens_in is None:
        tokens_in = max(1, len(prompt) // 4)
    if tokens_out is None:
        tokens_out = max(1, len(text) // 4)
    cost_usd = (tokens_in * price_in + tokens_out * price_out) / 1e6
    return text, tokens_in, tokens_out, cost_usd


class CLIBackend:
    """Cloud model behind a print-mode CLI (`claude -p`, `agy -p`, `codex exec`, `opencode run`).

    CLIs don't report token usage unless supported (--output-format json or --json),
    otherwise tokens are estimated at ~4 chars/token and cost from the configured
    per-million pricing. They run their own agent loops, so client-side tool calls
    are unsupported.
    """

    supports_tools = False
    local = False

    def __init__(self, command: list[str], price_in: float, price_out: float):
        self.command = command
        self.price_in = price_in
        self.price_out = price_out

    def _build_argv(
        self,
        prompt: str,
        effort_flags: "list[str] | None" = None,
        model_override: "str | None" = None,
    ) -> list[str]:
        cli = self.command[0] if self.command else ""
        template = list(DISPATCH_TEMPLATES.get(cli, [*self.command, "-p"]))
        flags: list[str] = list(effort_flags or [])
        if model_override:
            flags.extend(["-m", model_override])

        if cli == "claude":
            flags.extend(["--output-format", "json"])
        elif cli == "codex":
            flags.append("--json")

        if cli in ("codex", "opencode"):
            return [*template, *flags, prompt]
        else:
            return [*template, prompt, *flags]

    def complete(
        self,
        messages: list[dict],
        tools: "list[dict] | None" = None,
        effort_flags: "list[str] | None" = None,
        model_override: "str | None" = None,
        **kwargs,
    ) -> Completion:
        import subprocess

        cli = self.command[0] if self.command else ""
        prompt = "\n\n".join(
            f"[{m.get('role', 'user')}] {m.get('content', '')}" for m in messages
        )
        argv = self._build_argv(prompt, effort_flags=effort_flags, model_override=model_override)
        env = {k: v for k, v in os.environ.items() if k not in PROXY_ENV_STRIP}

        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=600,
            env=env,
        )

        if cli == "claude" and result.stdout:
            parsed = _parse_claude_json(result.stdout, prompt, self.price_in, self.price_out)
            if parsed is not None:
                text, tokens_in, tokens_out, cost_usd = parsed
                return Completion(
                    text=text,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    cost_usd=cost_usd,
                    local=False,
                )

        if result.returncode != 0:
            raise RuntimeError(
                f"{cli} exited {result.returncode}: {result.stderr.strip()[:500]}"
            )

        if cli == "codex" and result.stdout:
            parsed = _parse_codex_jsonl(result.stdout, prompt, self.price_in, self.price_out)
            if parsed is not None:
                text, tokens_in, tokens_out, cost_usd = parsed
                return Completion(
                    text=text,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    cost_usd=cost_usd,
                    local=False,
                )

        text = result.stdout.strip()
        tokens_in = max(1, len(prompt) // 4)
        tokens_out = max(1, len(text) // 4)
        cost = (tokens_in * self.price_in + tokens_out * self.price_out) / 1e6
        return Completion(
            text=text,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost,
            local=False,
        )

    def stream(
        self,
        messages: list[dict],
        tools: "list[dict] | None" = None,
        effort_flags: "list[str] | None" = None,
        model_override: "str | None" = None,
        **kwargs,
    ) -> Iterator["str | Completion"]:
        completion = self.complete(
            messages,
            tools=tools,
            effort_flags=effort_flags,
            model_override=model_override,
        )
        yield completion.text
        yield completion


def __getattr__(name: str):
    if name in (
        "AnthropicBackend",
        "OpenAIBackend",
        "OpenRouterBackend",
        "anthropic_messages_to_openai",
        "anthropic_tools_to_openai",
        "cc_messages_to_anthropic",
        "cc_tools_to_anthropic",
    ):
        import kultivait.api_backends as ab
        return getattr(ab, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


