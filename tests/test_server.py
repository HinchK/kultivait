import json
import threading
import time
import numpy as np
from fastapi.testclient import TestClient

from kultivait.backends import Completion
from kultivait.escalations import EscalationStore
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
    def __init__(self, name, local, tool_calls=None):
        self.name = name
        self.local = local
        self.supports_tools = local
        self.tool_calls = tool_calls
        self.calls = []
        self.tools_seen = []
        self.effort_flags_seen = []
        self.model_overrides_seen = []

    def _completion(self):
        return Completion(
            text="" if self.tool_calls else f"answered by {self.name}",
            tokens_in=10,
            tokens_out=5,
            cost_usd=0.0 if self.local else 0.01,
            local=self.local,
            tool_calls=self.tool_calls,
        )

    def complete(
        self,
        messages,
        tools=None,
        effort_flags=None,
        model_override=None,
        **kwargs,
    ):
        self.calls.append(messages)
        self.tools_seen.append(tools)
        self.effort_flags_seen.append(effort_flags)
        self.model_overrides_seen.append(model_override)
        return self._completion()

    def stream(
        self,
        messages,
        tools=None,
        effort_flags=None,
        model_override=None,
        **kwargs,
    ):
        self.calls.append(messages)
        self.tools_seen.append(tools)
        self.effort_flags_seen.append(effort_flags)
        self.model_overrides_seen.append(model_override)
        if not self.tool_calls:
            yield "answered by "
            yield self.name
        yield self._completion()


def make_client(
    tmp_path,
    embed,
    preprocess_generate=None,
    preprocess_timeout_s=15.0,
    tollbooth=None,
    toll_timeout_s=60.0,
    toll_enabled=True,
):
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
        escalations=EscalationStore(tmp_path / "escalations"),
        preprocess_generate=preprocess_generate,
        preprocess_timeout_s=preprocess_timeout_s,
        tollbooth=tollbooth,
        toll_timeout_s=toll_timeout_s,
        toll_enabled=toll_enabled,
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


def test_openai_content_parts_are_normalized_for_backends(tmp_path):
    client, backends = make_client(tmp_path, embed=lambda text: np.array([0.9, 0.1]))
    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "auto",
            # OpenAI content-parts format, as agent clients like Pi send it
            "messages": [
                {"role": "user", "content": [{"type": "text", "text": "rename this var"}]}
            ],
        },
    )
    assert resp.status_code == 200
    sent = backends["llama3.1:8b"].calls[0]
    assert sent == [{"role": "user", "content": "rename this var"}]


def test_tool_history_survives_normalization(tmp_path):
    client, backends = make_client(tmp_path, embed=lambda text: np.array([0.9, 0.1]))
    tool_call = {
        "id": "call_1",
        "type": "function",
        "function": {"name": "read", "arguments": '{"path": "a.py"}'},
    }
    client.post(
        "/v1/chat/completions",
        json={
            "model": "auto",
            "messages": [
                {"role": "user", "content": "read a.py"},
                {"role": "assistant", "content": None, "tool_calls": [tool_call]},
                {"role": "tool", "tool_call_id": "call_1", "content": "print('hi')"},
                {"role": "user", "content": "now rename the var"},
            ],
        },
    )
    sent = backends["llama3.1:8b"].calls[0]
    assert sent[1]["tool_calls"] == [tool_call]
    assert sent[2] == {"role": "tool", "tool_call_id": "call_1", "content": "print('hi')"}


TOOLS = [{"type": "function", "function": {"name": "read", "parameters": {}}}]
A_TOOL_CALL = {
    "id": "call_9",
    "type": "function",
    "function": {"name": "read", "arguments": '{"path": "a.py"}'},
}


def test_tools_are_forwarded_and_tool_calls_returned(tmp_path):
    client, backends = make_client(tmp_path, embed=lambda text: np.array([0.9, 0.1]))
    backends["llama3.1:8b"].tool_calls = [A_TOOL_CALL]
    resp = client.post(
        "/v1/chat/completions",
        json={"model": "auto", "tools": TOOLS, "messages": [{"role": "user", "content": "read a.py"}]},
    )
    body = resp.json()
    assert backends["llama3.1:8b"].tools_seen == [TOOLS]
    choice = body["choices"][0]
    assert choice["message"]["tool_calls"] == [A_TOOL_CALL]
    assert choice["finish_reason"] == "tool_calls"


def test_tools_request_falls_back_from_cloud_to_local_tier(tmp_path):
    # embed points squarely at claude (CLI backend, can't do client tool calls)
    client, backends = make_client(tmp_path, embed=lambda text: np.array([0.1, 0.9]))
    resp = client.post(
        "/v1/chat/completions",
        json={"model": "auto", "tools": TOOLS, "messages": [{"role": "user", "content": "refactor"}]},
    )
    body = resp.json()
    assert body["model"] == "llama3.1:8b"
    assert body["kultivait"]["fallback_reason"] == "tools_unsupported"
    assert len(backends["claude"].calls) == 0
    assert len(backends["llama3.1:8b"].calls) == 1


def test_virtual_tier_without_backend_falls_back_and_escalates(tmp_path):
    # Local-only setups keep a virtual frontier tier: classified, never served.
    backends = {"llama3.1:8b": FakeBackend("llama3.1:8b", local=True)}
    app = create_app(
        router=Router(centroids=CENTROIDS, capability_order=ORDER),
        embed=lambda text: np.array([0.1, 0.9]),  # classifies to "claude"
        backends=backends,
        ledger=Ledger(tmp_path / "ledger.jsonl"),
        gate=Gate(generate=lambda p: "brief", compost_dir=tmp_path / "compost"),
        escalations=EscalationStore(tmp_path / "escalations"),
    )
    client = TestClient(app)
    resp = client.post(
        "/v1/chat/completions",
        json={"model": "auto", "messages": [{"role": "user", "content": "design a migration"}]},
    )
    body = resp.json()
    assert body["model"] == "llama3.1:8b"
    assert body["kultivait"]["fallback_reason"] == "no_backend"
    listed = EscalationStore(tmp_path / "escalations").list()
    assert len(listed) == 1
    assert listed[0].requested_tier == "claude"


def test_tool_fallback_archives_escalation_with_conversation(tmp_path):
    import json

    client, _ = make_client(tmp_path, embed=lambda text: np.array([0.1, 0.9]))
    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "auto",
            "tools": TOOLS,
            "messages": [{"role": "user", "content": "draft a technical spec"}],
        },
    )
    eid = resp.json()["kultivait"]["escalation_id"]
    assert eid.startswith("esc-")
    store = EscalationStore(tmp_path / "escalations")
    listed = store.list()
    assert [e.id for e in listed] == [eid]
    assert listed[0].requested_tier == "claude"
    assert store.load_messages(eid) == [{"role": "user", "content": "draft a technical spec"}]
    # linked in the ledger entry too
    entry = json.loads((tmp_path / "ledger.jsonl").read_text())
    assert entry["escalation_id"] == eid


def test_no_escalation_archived_without_fallback(tmp_path):
    client, _ = make_client(tmp_path, embed=lambda text: np.array([0.9, 0.1]))
    resp = client.post(
        "/v1/chat/completions",
        json={"model": "auto", "tools": TOOLS, "messages": [{"role": "user", "content": "rename"}]},
    )
    assert resp.json()["kultivait"]["escalation_id"] is None
    assert EscalationStore(tmp_path / "escalations").list() == []


def test_streaming_emits_tool_calls_delta(tmp_path):
    client, backends = make_client(tmp_path, embed=lambda text: np.array([0.9, 0.1]))
    backends["llama3.1:8b"].tool_calls = [A_TOOL_CALL]
    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "auto",
            "stream": True,
            "tools": TOOLS,
            "messages": [{"role": "user", "content": "read a.py"}],
        },
    )
    events = [e for e in parse_sse(resp.text) if e != "[DONE]"]
    tool_deltas = [
        e["choices"][0]["delta"]["tool_calls"]
        for e in events
        if "tool_calls" in e["choices"][0]["delta"]
    ]
    assert tool_deltas == [[{**A_TOOL_CALL, "index": 0}]]
    assert events[-1]["choices"][0]["finish_reason"] == "tool_calls"


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


def test_ledger_entry_carries_full_decision_metadata(tmp_path):
    import json

    client, _ = make_client(tmp_path, embed=lambda text: np.array([0.1, 0.9]))
    client.post(
        "/v1/chat/completions",
        json={
            "model": "auto",
            "tools": TOOLS,
            "messages": [{"role": "user", "content": "draft a technical spec for the PDF report"}],
        },
    )
    entry = json.loads((tmp_path / "ledger.jsonl").read_text())
    assert entry["tier"] == "llama3.1:8b"          # served (tool fallback)
    assert entry["requested_tier"] == "claude"     # what the router wanted
    assert entry["fallback_reason"] == "tools_unsupported"
    assert "margin" in entry
    assert entry["snippet"].startswith("draft a technical spec")
    assert entry["truncated"] is False


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


def test_fat_margin_skips_preprocessor(tmp_path):
    import json
    calls = []

    def fake_gen(model: str, prompt: str):
        calls.append(prompt)
        return "{}", 0.05

    client, backends = make_client(
        tmp_path,
        embed=lambda text: np.array([0.9, 0.1]),
        preprocess_generate=fake_gen,
    )
    resp = client.post(
        "/v1/chat/completions",
        json={"model": "auto", "messages": [{"role": "user", "content": "rename this var"}]},
    )
    assert resp.status_code == 200
    assert len(calls) == 0  # preprocessor was NOT called
    km = resp.json()["kultivait"]
    assert km["preprocess_mark"] == "skipped"
    assert km["verdict"] == "local"
    assert km["max_fit"] == 0.0
    assert km["subtask_candidates"] == 0
    assert "fingerprint" in km and len(km["fingerprint"]) > 0

    entry = json.loads((tmp_path / "ledger.jsonl").read_text())
    assert entry["preprocess_mark"] == "skipped"
    assert entry["toll"] == "skipped"
    assert entry["fingerprint"] == km["fingerprint"]


def test_contested_runs_preprocessor_and_serves_local_verdict(tmp_path):
    import json
    calls = []
    sample_res = {
        "analysis": {"task_type": "simple_edit", "complexity": 2, "signals": []},
        "rewrite": "Rewritten prompt",
        "judge": {
            "local_sufficient": True,
            "confidence": 0.9,
            "targets": [{"target": "claude", "fit": 0.40, "effort": "low"}],
        },
    }

    def fake_gen(model: str, prompt: str):
        calls.append(prompt)
        return json.dumps(sample_res), 0.05

    client, backends = make_client(
        tmp_path,
        embed=lambda text: np.array([0.71, 0.70]),  # thin margin (< 0.02)
        preprocess_generate=fake_gen,
    )
    resp = client.post(
        "/v1/chat/completions",
        json={"model": "auto", "messages": [{"role": "user", "content": "contested task"}]},
    )
    assert resp.status_code == 200
    assert len(calls) == 1
    assert "contested task" in calls[0]
    km = resp.json()["kultivait"]
    assert km["preprocess_mark"] == "ok"
    assert km["verdict"] == "local"
    assert km["max_fit"] == 0.40
    assert resp.json()["model"] == "llama3.1:8b"
    # Local dispatch gets original message, NOT rewrite
    assert backends["llama3.1:8b"].calls[0] == [{"role": "user", "content": "contested task"}]


def test_contested_runs_preprocessor_and_serves_frontier_verdict_with_rewrite(tmp_path):
    import json
    calls = []
    sample_res = {
        "analysis": {
            "task_type": "architecture",
            "complexity": 8,
            "signals": ["multi-file"],
            "subtask_candidates": ["design queue", "write tests"],
        },
        "rewrite": "Self-contained architecture prompt for claude",
        "judge": {
            "local_sufficient": False,
            "confidence": 0.95,
            "targets": [{"target": "claude", "fit": 0.92, "effort": "high"}],
        },
    }

    def fake_gen(model: str, prompt: str):
        calls.append(prompt)
        return json.dumps(sample_res), 0.05

    client, backends = make_client(
        tmp_path,
        embed=lambda text: np.array([0.71, 0.70]),
        preprocess_generate=fake_gen,
    )
    resp = client.post(
        "/v1/chat/completions",
        json={"model": "auto", "messages": [{"role": "user", "content": "vague arch prompt"}]},
    )
    assert resp.status_code == 200
    assert len(calls) == 1
    km = resp.json()["kultivait"]
    assert km["preprocess_mark"] == "ok"
    assert km["verdict"] == "frontier"
    assert km["max_fit"] == 0.92
    assert km["subtask_candidates"] == 2
    assert km["canonical_effort"] == "deep"
    assert km["cli_effort_flags"] == ["--effort", "high"]
    assert resp.json()["model"] == "claude"
    # Frontier CLI dispatch receives rewritten text and effort flags
    assert backends["claude"].calls[0] == [
        {"role": "user", "content": "Self-contained architecture prompt for claude"}
    ]
    assert backends["claude"].effort_flags_seen[0] == ["--effort", "high"]

    entry = json.loads((tmp_path / "ledger.jsonl").read_text())
    assert entry["preprocess_mark"] == "ok"
    assert entry["verdict"] == "frontier"
    assert entry["max_fit"] == 0.92
    assert entry["canonical_effort"] == "deep"
    assert entry["cli_effort_flags"] == ["--effort", "high"]
    assert entry["toll"] == "skipped"
    assert entry["subtask_candidates"] == 2


def test_contested_preprocessor_timeout_falls_back_to_router(tmp_path):
    def fake_gen(model: str, prompt: str):
        raise TimeoutError("local model timeout")

    client, backends = make_client(
        tmp_path,
        embed=lambda text: np.array([0.71, 0.70]),
        preprocess_generate=fake_gen,
    )
    resp = client.post(
        "/v1/chat/completions",
        json={"model": "auto", "messages": [{"role": "user", "content": "timeout prompt"}]},
    )
    assert resp.status_code == 200
    km = resp.json()["kultivait"]
    assert km["preprocess_mark"] == "preprocess_timeout"
    assert km["verdict"] == "frontier"  # router escalated to claude
    assert resp.json()["model"] == "claude"
    # Fallback uses original message
    assert backends["claude"].calls[0] == [{"role": "user", "content": "timeout prompt"}]


def test_contested_preprocessor_parse_fail_falls_back_to_router(tmp_path):
    def fake_gen(model: str, prompt: str):
        return "I am just raw prose output without JSON brackets.", 0.05

    client, backends = make_client(
        tmp_path,
        embed=lambda text: np.array([0.71, 0.70]),
        preprocess_generate=fake_gen,
    )
    resp = client.post(
        "/v1/chat/completions",
        json={"model": "auto", "messages": [{"role": "user", "content": "parse fail prompt"}]},
    )
    assert resp.status_code == 200
    km = resp.json()["kultivait"]
    assert km["preprocess_mark"] == "preprocess_fail"
    assert resp.json()["model"] == "claude"
    assert backends["claude"].calls[0] == [{"role": "user", "content": "parse fail prompt"}]


def test_tool_bearing_contested_request_preprocessed_with_tool_fallback(tmp_path):
    sample_res = {
        "analysis": {
            "task_type": "compound",
            "complexity": 7,
            "signals": ["tool call required"],
            "subtask_candidates": ["run tests", "refactor"],
        },
        "rewrite": "Tool prompt rewritten",
        "judge": {
            "local_sufficient": False,
            "confidence": 0.90,
            "targets": [{"target": "claude", "fit": 0.95, "effort": "medium"}],
        },
    }

    client, backends = make_client(
        tmp_path,
        embed=lambda text: np.array([0.71, 0.70]),
        preprocess_generate=lambda m, p: (json.dumps(sample_res), 0.05),
    )
    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "auto",
            "tools": TOOLS,
            "messages": [{"role": "user", "content": "do tool task"}],
        },
    )
    assert resp.status_code == 200
    km = resp.json()["kultivait"]
    assert km["preprocess_mark"] == "ok"
    assert km["subtask_candidates"] == 2
    # Frontier requested by preprocessor, but claude does not support tools -> falls back to llama
    assert km["fallback_reason"] == "tools_unsupported"
    assert resp.json()["model"] == "llama3.1:8b"
    # Local fallback served gets original message
    assert backends["llama3.1:8b"].calls[0] == [{"role": "user", "content": "do tool task"}]


def test_contested_verdict_triggers_tollbooth_and_answers_frontier(tmp_path):
    import threading
    from kultivait.tollbooth import TollboothQueue

    sample_res = {
        "analysis": {
            "task_type": "debugging",
            "complexity": 5,
            "signals": ["test failure"],
            "subtask_candidates": ["isolate test"],
        },
        "rewrite": "Contested prompt rewritten for claude",
        "judge": {
            "local_sufficient": False,
            "confidence": 0.80,
            "targets": [{"target": "claude", "fit": 0.75, "effort": "medium"}],
        },
    }

    tollbooth = TollboothQueue(
        queue_path=tmp_path / "pending_tolls.jsonl",
        default_timeout_s=5.0,
        enabled=True,
    )
    tollbooth.register_presence("tty")

    client, backends = make_client(
        tmp_path,
        embed=lambda text: np.array([0.71, 0.70]),
        preprocess_generate=lambda m, p: (json.dumps(sample_res), 0.05),
        tollbooth=tollbooth,
    )

    def answer_when_pending():
        for _ in range(50):
            time.sleep(0.01)
            if tollbooth._pending:
                tid = list(tollbooth._pending.keys())[0]
                tollbooth.answer_ticket(tid, "claude")
                return

    t = threading.Thread(target=answer_when_pending)
    t.start()

    resp = client.post(
        "/v1/chat/completions",
        json={"model": "auto", "messages": [{"role": "user", "content": "fix my bug"}]},
    )
    t.join()

    assert resp.status_code == 200
    data = resp.json()
    km = data["kultivait"]
    assert km["verdict"] == "frontier"
    assert km["toll"] == "answered"
    assert km["route_choice"] == "human:frontier:claude"
    assert km["canonical_effort"] == "balanced"
    assert resp.json()["model"] == "claude"
    assert backends["claude"].calls[0] == [
        {"role": "user", "content": "Contested prompt rewritten for claude"}
    ]

    # Verify ledger entry
    records = [json.loads(line) for line in (tmp_path / "ledger.jsonl").read_text().splitlines()]
    assert records[-1]["toll"] == "answered"
    assert records[-1]["route_choice"] == "human:frontier:claude"
    assert records[-1]["verdict"] == "frontier"


def test_contested_verdict_tollbooth_no_presence_auto_policy_local(tmp_path):
    from kultivait.tollbooth import TollboothQueue

    sample_res = {
        "analysis": {
            "task_type": "debugging",
            "complexity": 5,
            "signals": ["test failure"],
            "subtask_candidates": [],
        },
        "rewrite": "Contested prompt rewritten",
        "judge": {
            "local_sufficient": False,
            "confidence": 0.80,
            "targets": [{"target": "claude", "fit": 0.75, "effort": "medium"}],
        },
    }

    # No presence registered
    tollbooth = TollboothQueue(
        queue_path=tmp_path / "pending_tolls.jsonl",
        default_timeout_s=5.0,
        enabled=True,
        escalations=EscalationStore(tmp_path / "escalations"),
    )

    client, backends = make_client(
        tmp_path,
        embed=lambda text: np.array([0.71, 0.70]),
        preprocess_generate=lambda m, p: (json.dumps(sample_res), 0.05),
        tollbooth=tollbooth,
    )

    resp = client.post(
        "/v1/chat/completions",
        json={"model": "auto", "messages": [{"role": "user", "content": "fix my bug"}]},
    )
    assert resp.status_code == 200
    data = resp.json()
    km = data["kultivait"]
    assert km["verdict"] == "local"
    assert km["toll"] == "expired"
    assert km["route_choice"] == "auto:local"
    assert resp.json()["model"] == "llama3.1:8b"
    assert backends["llama3.1:8b"].calls[0] == [
        {"role": "user", "content": "fix my bug"}
    ]

    # Verify missed menu archived
    menus = list((tmp_path / "escalations").glob("menu-*.json"))
    assert len(menus) == 1
    menu_data = json.loads(menus[0].read_text())
    assert menu_data["reason"] == "no_presence"
    assert menu_data["auto_choice"] == "auto:local"


def test_contested_verdict_tollbooth_human_local_choice_archives_escalation(tmp_path):
    import threading
    from kultivait.tollbooth import TollboothQueue

    sample_res = {
        "analysis": {
            "task_type": "debugging",
            "complexity": 5,
            "signals": ["test failure"],
            "subtask_candidates": [],
        },
        "rewrite": "Contested prompt rewritten",
        "judge": {
            "local_sufficient": False,
            "confidence": 0.80,
            "targets": [{"target": "claude", "fit": 0.75, "effort": "medium"}],
        },
    }

    tollbooth = TollboothQueue(
        queue_path=tmp_path / "pending_tolls.jsonl",
        default_timeout_s=5.0,
        enabled=True,
        escalations=EscalationStore(tmp_path / "escalations"),
    )
    tollbooth.register_presence("tty")

    client, backends = make_client(
        tmp_path,
        embed=lambda text: np.array([0.71, 0.70]),
        preprocess_generate=lambda m, p: (json.dumps(sample_res), 0.05),
        tollbooth=tollbooth,
    )

    def answer_local():
        for _ in range(50):
            time.sleep(0.01)
            if tollbooth._pending:
                tid = list(tollbooth._pending.keys())[0]
                tollbooth.answer_ticket(tid, "local")
                return

    t = threading.Thread(target=answer_local)
    t.start()

    resp = client.post(
        "/v1/chat/completions",
        json={"model": "auto", "messages": [{"role": "user", "content": "fix my bug"}]},
    )
    t.join()

    assert resp.status_code == 200
    data = resp.json()
    km = data["kultivait"]
    assert km["verdict"] == "local"
    assert km["toll"] == "answered"
    assert km["route_choice"] == "human:local"
    assert resp.json()["model"] == "llama3.1:8b"
    assert backends["llama3.1:8b"].calls[0] == [
        {"role": "user", "content": "fix my bug"}
    ]

    # Verify escalation created for deliberate local choice
    escs = list((tmp_path / "escalations").glob("esc-*.json"))
    assert len(escs) == 1


def test_anthropic_messages_contested_verdict_tollbooth(tmp_path):
    sample_res = {
        "analysis": {
            "task_type": "debugging",
            "complexity": 5,
            "signals": ["test failure"],
            "subtask_candidates": [],
        },
        "rewrite": "Contested prompt rewritten for claude",
        "judge": {
            "local_sufficient": False,
            "confidence": 0.80,
            "targets": [{"target": "claude", "fit": 0.75, "effort": "medium"}],
        },
    }

    from kultivait.tollbooth import TollboothQueue
    tollbooth = TollboothQueue(
        queue_path=tmp_path / "pending_tolls.jsonl",
        default_timeout_s=5.0,
        enabled=True,
    )
    tollbooth.register_presence("tty")

    client, backends = make_client(
        tmp_path,
        embed=lambda text: np.array([0.71, 0.70]),
        preprocess_generate=lambda m, p: (json.dumps(sample_res), 0.05),
        tollbooth=tollbooth,
    )

    def answer_frontier():
        for _ in range(50):
            time.sleep(0.01)
            if tollbooth._pending:
                tid = list(tollbooth._pending.keys())[0]
                tollbooth.answer_ticket(tid, "claude")
                return

    t = threading.Thread(target=answer_frontier)
    t.start()

    resp = client.post(
        "/v1/messages",
        json={"model": "auto", "messages": [{"role": "user", "content": "fix my bug"}]},
    )
    t.join()

    assert resp.status_code == 200
    assert resp.json()["model"] == "claude"
    assert backends["claude"].calls[0] == [
        {"role": "user", "content": "Contested prompt rewritten for claude"}
    ]

    records = [json.loads(line) for line in (tmp_path / "ledger.jsonl").read_text().splitlines()]
    assert records[-1]["toll"] == "answered"
    assert records[-1]["route_choice"] == "human:frontier:claude"


def test_contested_verdict_tollbooth_with_effort_override(tmp_path):
    sample_res = {
        "analysis": {
            "task_type": "debugging",
            "complexity": 5,  # normally maps to balanced
            "signals": ["complex bug"],
            "subtask_candidates": [],
        },
        "rewrite": "Contested prompt rewritten",
        "judge": {
            "local_sufficient": False,
            "confidence": 0.80,
            "targets": [{"target": "claude", "fit": 0.75, "effort": "medium"}],
        },
    }

    from kultivait.tollbooth import TollboothQueue
    tollbooth = TollboothQueue(
        queue_path=tmp_path / "pending_tolls.jsonl",
        default_timeout_s=5.0,
        enabled=True,
    )
    tollbooth.register_presence("tty")

    client, backends = make_client(
        tmp_path,
        embed=lambda text: np.array([0.71, 0.70]),
        preprocess_generate=lambda m, p: (json.dumps(sample_res), 0.05),
        tollbooth=tollbooth,
    )

    def answer_with_deep_effort():
        for _ in range(50):
            time.sleep(0.01)
            if tollbooth._pending:
                tid = list(tollbooth._pending.keys())[0]
                tollbooth.answer_ticket(tid, "claude", effort_canonical="deep")
                return

    t = threading.Thread(target=answer_with_deep_effort)
    t.start()

    resp = client.post(
        "/v1/chat/completions",
        json={"model": "auto", "messages": [{"role": "user", "content": "deep debugging needed"}]},
    )
    t.join()

    assert resp.status_code == 200
    data = resp.json()
    km = data["kultivait"]
    assert km["verdict"] == "frontier"
    assert km["toll"] == "answered"
    assert km["route_choice"] == "human:frontier:claude"
    assert km["canonical_effort"] == "deep"
    assert km["cli_effort_flags"] == ["--effort", "high"]
    assert backends["claude"].effort_flags_seen[0] == ["--effort", "high"]


def test_api_backend_tool_bearing_chat_completions_no_fallback(tmp_path):
    tool_call = {
        "id": "call_weather_1",
        "type": "function",
        "function": {"name": "get_weather", "arguments": '{"city": "Paris"}'},
    }
    api_backend = FakeBackend("openrouter", local=False, tool_calls=[tool_call])
    api_backend.supports_tools = True

    backends = {
        "llama3.1:8b": FakeBackend("llama3.1:8b", local=True),
        "openrouter": api_backend,
    }
    app = create_app(
        router=Router(centroids={"llama3.1:8b": np.array([1.0, 0.0]), "openrouter": np.array([0.0, 1.0])}, capability_order=["llama3.1:8b", "openrouter"]),
        embed=lambda text: np.array([0.0, 1.0]),  # routes to openrouter
        backends=backends,
        ledger=Ledger(tmp_path / "ledger.jsonl"),
        gate=Gate(generate=lambda p: "distilled", compost_dir=tmp_path / "compost"),
        escalations=EscalationStore(tmp_path / "escalations"),
        toll_enabled=False,
    )
    client = TestClient(app)

    # 1. Non-streaming tool call
    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "auto",
            "messages": [{"role": "user", "content": "weather in Paris"}],
            "tools": [{"type": "function", "function": {"name": "get_weather"}}],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["choices"][0]["finish_reason"] == "tool_calls"
    assert data["choices"][0]["message"]["tool_calls"][0]["function"]["name"] == "get_weather"
    assert data["kultivait"]["tier"] == "openrouter"
    assert data["kultivait"]["fallback_reason"] is None

    # 2. Streaming tool call
    resp_stream = client.post(
        "/v1/chat/completions",
        json={
            "model": "auto",
            "messages": [{"role": "user", "content": "weather in Paris"}],
            "tools": [{"type": "function", "function": {"name": "get_weather"}}],
            "stream": True,
        },
    )
    assert resp_stream.status_code == 200
    events = [line for line in resp_stream.text.split("\n\n") if line.startswith("data: ")]
    chunks = [json.loads(line[6:]) for line in events if line[6:] != "[DONE]"]
    tool_chunk = next(c for c in chunks if c["choices"][0]["delta"].get("tool_calls"))
    assert tool_chunk["choices"][0]["delta"]["tool_calls"][0]["function"]["name"] == "get_weather"

    # 3. Check ledger has recorded dual-track cost (cost_usd = 0.01, notional_usd = 0.01 for API)
    records = [json.loads(line) for line in (tmp_path / "ledger.jsonl").read_text().splitlines()]
    assert records[-1]["tier"] == "openrouter"
    assert records[-1]["cost_usd"] == 0.01
    assert records[-1]["notional_usd"] == 0.01
    assert records[-1]["fallback_reason"] is None


def test_api_backend_tool_bearing_anthropic_messages_no_fallback(tmp_path):
    tool_call = {
        "id": "call_weather_2",
        "type": "function",
        "function": {"name": "get_weather", "arguments": '{"city": "Berlin"}'},
    }
    api_backend = FakeBackend("openrouter", local=False, tool_calls=[tool_call])
    api_backend.supports_tools = True

    backends = {
        "llama3.1:8b": FakeBackend("llama3.1:8b", local=True),
        "openrouter": api_backend,
    }
    app = create_app(
        router=Router(centroids={"llama3.1:8b": np.array([1.0, 0.0]), "openrouter": np.array([0.0, 1.0])}, capability_order=["llama3.1:8b", "openrouter"]),
        embed=lambda text: np.array([0.0, 1.0]),  # routes to openrouter
        backends=backends,
        ledger=Ledger(tmp_path / "ledger.jsonl"),
        gate=Gate(generate=lambda p: "distilled", compost_dir=tmp_path / "compost"),
        escalations=EscalationStore(tmp_path / "escalations"),
        toll_enabled=False,
    )
    client = TestClient(app)

    # 1. Non-streaming tool call
    resp = client.post(
        "/v1/messages",
        json={
            "model": "auto",
            "messages": [{"role": "user", "content": "weather in Berlin"}],
            "tools": [{"name": "get_weather", "input_schema": {"type": "object"}}],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["stop_reason"] == "tool_use"
    assert data["content"][0]["type"] == "tool_use"
    assert data["content"][0]["name"] == "get_weather"
    assert data["content"][0]["input"] == {"city": "Berlin"}

    # 2. Streaming tool call
    resp_stream = client.post(
        "/v1/messages",
        json={
            "model": "auto",
            "messages": [{"role": "user", "content": "weather in Berlin"}],
            "tools": [{"name": "get_weather", "input_schema": {"type": "object"}}],
            "stream": True,
        },
    )
    assert resp_stream.status_code == 200
    lines = resp_stream.text.strip().split("\n\n")
    parsed_events = []
    for block in lines:
        if not block.strip():
            continue
        ev_type = None
        ev_data = None
        for line in block.split("\n"):
            if line.startswith("event: "):
                ev_type = line[7:]
            elif line.startswith("data: "):
                ev_data = json.loads(line[6:])
        if ev_type and ev_data:
            parsed_events.append((ev_type, ev_data))

    start_ev = next(d for t, d in parsed_events if t == "content_block_start" and d["content_block"].get("type") == "tool_use")
    assert start_ev["content_block"]["name"] == "get_weather"
    delta_ev = next(d for t, d in parsed_events if t == "content_block_delta" and d["delta"].get("type") == "input_json_delta")
    assert "Berlin" in delta_ev["delta"]["partial_json"]
    msg_delta = next(d for t, d in parsed_events if t == "message_delta")
    assert msg_delta["delta"]["stop_reason"] == "tool_use"





