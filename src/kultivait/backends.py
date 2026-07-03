"""Model backends: local ollama and cloud CLIs, behind one interface.

`stream()` yields text deltas and finishes with a Completion carrying the
final usage, so callers can tally the ledger after the stream ends.
"""

import json
from dataclasses import dataclass
from typing import Iterator, Protocol


@dataclass(frozen=True)
class Completion:
    text: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    local: bool


class Backend(Protocol):
    def complete(self, messages: list[dict]) -> Completion: ...

    def stream(self, messages: list[dict]) -> Iterator["str | Completion"]: ...


class OllamaBackend:
    """Local model via the ollama chat API. Free by definition."""

    def __init__(self, model: str, base_url: str = "http://localhost:11434"):
        self.model = model
        self.base_url = base_url

    def complete(self, messages: list[dict]) -> Completion:
        import httpx

        r = httpx.post(
            f"{self.base_url}/api/chat",
            json={"model": self.model, "messages": messages, "stream": False},
            timeout=300,
        )
        r.raise_for_status()
        data = r.json()
        return Completion(
            text=data["message"]["content"],
            tokens_in=data.get("prompt_eval_count", 0),
            tokens_out=data.get("eval_count", 0),
            cost_usd=0.0,
            local=True,
        )

    def stream(self, messages: list[dict]) -> Iterator["str | Completion"]:
        import httpx

        parts = []
        with httpx.stream(
            "POST",
            f"{self.base_url}/api/chat",
            json={"model": self.model, "messages": messages, "stream": True},
            timeout=300,
        ) as r:
            r.raise_for_status()
            data = {}
            for line in r.iter_lines():
                if not line.strip():
                    continue
                data = json.loads(line)
                delta = data.get("message", {}).get("content", "")
                if delta:
                    parts.append(delta)
                    yield delta
        yield Completion(
            text="".join(parts),
            tokens_in=data.get("prompt_eval_count", 0),
            tokens_out=data.get("eval_count", 0),
            cost_usd=0.0,
            local=True,
        )


class CLIBackend:
    """Cloud model behind a print-mode CLI (`claude -p`, `agy -p`).

    CLIs don't report token usage, so tokens are estimated at ~4 chars/token
    and cost from the configured per-million pricing.
    """

    def __init__(self, command: list[str], price_in: float, price_out: float):
        self.command = command
        self.price_in = price_in
        self.price_out = price_out

    def complete(self, messages: list[dict]) -> Completion:
        import subprocess

        prompt = "\n\n".join(
            f"[{m.get('role', 'user')}] {m.get('content', '')}" for m in messages
        )
        result = subprocess.run(
            [*self.command, "-p", prompt],
            capture_output=True,
            text=True,
            timeout=600,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"{self.command[0]} exited {result.returncode}: {result.stderr.strip()[:500]}"
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

    def stream(self, messages: list[dict]) -> Iterator["str | Completion"]:
        # A print-mode CLI produces output only on exit, so this "stream"
        # is a single delta — correct for clients, just not incremental.
        completion = self.complete(messages)
        yield completion.text
        yield completion
