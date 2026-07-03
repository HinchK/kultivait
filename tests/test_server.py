import numpy as np
from fastapi.testclient import TestClient

from kultivait.backends import Completion
from kultivait.gates import Gate
from kultivait.ledger import Ledger
from kultivait.router import Router
from kultivait.server import create_app

CENTROIDS = {
    "llama3.1:8b": np.array([1.0, 0.0]),
    "claude": np.array([0.0, 1.0]),
}
ORDER = ["llama3.1:8b", "claude"]


class FakeBackend:
    def __init__(self, name, local):
        self.name = name
        self.local = local
        self.calls = []

    def _completion(self):
        return Completion(
            text=f"answered by {self.name}",
            tokens_in=10,
            tokens_out=5,
            cost_usd=0.0 if self.local else 0.01,
            local=self.local,
        )

    def complete(self, messages):
        self.calls.append(messages)
        return self._completion()

    def stream(self, messages):
        self.calls.append(messages)
        yield "answered by "
        yield self.name
        yield self._completion()


def make_client(tmp_path, embed):
    backends = {
        "llama3.1:8b": FakeBackend("llama3.1:8b", local=True),
        "claude": FakeBackend("claude", local=False),
    }
    app = create_app(
        router=Router(centroids=CENTROIDS, capability_order=ORDER),
        embed=embed,
        backends=backends,
        ledger=Ledger(tmp_path / "ledger.jsonl"),
        gate=Gate(generate=lambda p: "FINDINGS: distilled.", compost_dir=tmp_path / "compost"),
    )
    return TestClient(app), backends


def parse_sse(body: str) -> list:
    import json

    events = []
    for line in body.splitlines():
        if line.startswith("data: "):
            payload = line[len("data: ") :]
            events.append("[DONE]" if payload == "[DONE]" else json.loads(payload))
    return events


def test_openai_streaming_emits_deltas_then_done(tmp_path):
    client, _ = make_client(tmp_path, embed=lambda text: np.array([0.9, 0.1]))
    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "auto",
            "stream": True,
            "messages": [{"role": "user", "content": "rename this var"}],
        },
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(resp.text)
    deltas = [
        e["choices"][0]["delta"].get("content", "")
        for e in events
        if e != "[DONE]" and e["choices"]
    ]
    assert "".join(deltas) == "answered by llama3.1:8b"
    assert events[-1] == "[DONE]"
    # every chunk carries the routed model
    assert all(e["model"] == "llama3.1:8b" for e in events if e != "[DONE]")


def test_openai_streaming_records_ledger_after_stream(tmp_path):
    client, _ = make_client(tmp_path, embed=lambda text: np.array([0.9, 0.1]))
    resp = client.post(
        "/v1/chat/completions",
        json={"model": "auto", "stream": True, "messages": [{"role": "user", "content": "x"}]},
    )
    assert resp.headers["content-type"].startswith("text/event-stream")
    stats = client.get("/harvest").json()
    assert stats["prompts"] == 1
    assert stats["local_prompts"] == 1


def test_anthropic_messages_routes_and_returns_anthropic_shape(tmp_path):
    client, backends = make_client(tmp_path, embed=lambda text: np.array([0.9, 0.1]))
    resp = client.post(
        "/v1/messages",
        json={
            "model": "auto",
            "max_tokens": 1024,
            # content blocks, as Claude Code sends them
            "messages": [
                {"role": "user", "content": [{"type": "text", "text": "rename this var"}]}
            ],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["type"] == "message"
    assert body["role"] == "assistant"
    assert body["content"] == [{"type": "text", "text": "answered by llama3.1:8b"}]
    assert body["stop_reason"] == "end_turn"
    assert body["usage"] == {"input_tokens": 10, "output_tokens": 5}
    assert len(backends["llama3.1:8b"].calls) == 1
    # backends must receive plain-string content, never Anthropic content blocks
    sent = backends["llama3.1:8b"].calls[0]
    assert sent == [{"role": "user", "content": "rename this var"}]


def test_anthropic_system_param_becomes_system_message(tmp_path):
    client, backends = make_client(tmp_path, embed=lambda text: np.array([0.9, 0.1]))
    client.post(
        "/v1/messages",
        json={
            "model": "auto",
            "max_tokens": 64,
            "system": "You are terse.",
            "messages": [{"role": "user", "content": "rename this var"}],
        },
    )
    sent = backends["llama3.1:8b"].calls[0]
    assert sent[0] == {"role": "system", "content": "You are terse."}
    assert sent[1] == {"role": "user", "content": "rename this var"}


def test_anthropic_streaming_emits_event_sequence(tmp_path):
    client, _ = make_client(tmp_path, embed=lambda text: np.array([0.9, 0.1]))
    resp = client.post(
        "/v1/messages",
        json={
            "model": "auto",
            "max_tokens": 1024,
            "stream": True,
            "messages": [{"role": "user", "content": "rename this var"}],
        },
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(resp.text)
    types = [e["type"] for e in events]
    assert types[0] == "message_start"
    assert types[-1] == "message_stop"
    assert "content_block_start" in types and "content_block_stop" in types
    text = "".join(
        e["delta"]["text"] for e in events if e["type"] == "content_block_delta"
    )
    assert text == "answered by llama3.1:8b"
    stats = client.get("/harvest").json()
    assert stats["prompts"] == 1


def test_gate_endpoint_distills_and_composts(tmp_path):
    client, _ = make_client(tmp_path, embed=lambda text: np.array([1.0, 0.0]))
    resp = client.post(
        "/gate",
        json={
            "transcript": "we explored many files and walked dead ends. " * 20,
            "from_phase": "explore",
            "to_phase": "plan",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["brief"] == "FINDINGS: distilled."
    assert body["tokens_before"] >= body["tokens_after"]
    assert (tmp_path / "compost" / f"{body['compost_id']}.txt").exists()


def test_routes_chat_completion_to_classified_backend(tmp_path):
    client, backends = make_client(tmp_path, embed=lambda text: np.array([0.9, 0.1]))
    resp = client.post(
        "/v1/chat/completions",
        json={"model": "auto", "messages": [{"role": "user", "content": "rename this var"}]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["choices"][0]["message"]["content"] == "answered by llama3.1:8b"
    assert body["model"] == "llama3.1:8b"
    assert body["kultivait"]["tier"] == "llama3.1:8b"
    assert len(backends["llama3.1:8b"].calls) == 1
    assert len(backends["claude"].calls) == 0


def test_completion_is_recorded_in_ledger(tmp_path):
    client, _ = make_client(tmp_path, embed=lambda text: np.array([0.1, 0.9]))
    client.post(
        "/v1/chat/completions",
        json={"model": "auto", "messages": [{"role": "user", "content": "refactor everything"}]},
    )
    stats = client.get("/harvest").json()
    assert stats["prompts"] == 1
    assert stats["local_prompts"] == 0
    assert stats["spent_usd"] == 0.01
