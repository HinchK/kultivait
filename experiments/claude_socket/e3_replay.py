"""E3: replay a captured Claude Code /v1/messages request into kultivait's real
create_app (test-suite FakeBackends: local 'llama3.1:8b' tool-capable, cloud
'claude' CLI not tool-capable). No models, no network. Run from repo root:
  uv run python experiments/claude_socket/e3_replay.py <captured_body.json>
Capture a body first with stub_upstream.py (it writes <log>.last_body.json).
Note: FakeBackend accepts any tool shape, so this checks routing/framing,
NOT tool-format compatibility with a real local runtime (see the E8 finding
in docs/research/2026-09-11-claude-socket-loopback.md).
"""
import json
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, "tests")
sys.path.insert(0, "src")
from test_server import make_client, parse_sse  # noqa: E402

body = json.load(open(sys.argv[1]))
HEADERS = {
    "anthropic-version": "2023-06-01",
    "anthropic-beta": "claude-code-20250219,context-1m-2025-08-07,interleaved-thinking-2025-05-14",
    "x-api-key": "kultivait",
    "user-agent": "claude-cli/2.1.269 (external, sdk-cli)",
}

# embed vectors: [0.9,0.1] lands on the local centroid, [0.1,0.9] on 'claude'
for label, vec in (("classified-local", [0.9, 0.1]), ("classified-frontier", [0.1, 0.9])):
    tmp = Path(tempfile.mkdtemp())
    client, backends = make_client(tmp, embed=lambda _t, v=vec: np.array(v), toll_enabled=False)
    resp = client.post("/v1/messages?beta=true", json=body, headers=HEADERS)
    print(f"=== {label}: HTTP {resp.status_code} ct={resp.headers.get('content-type')}")
    served = {n: len(b.calls) for n, b in backends.items()}
    print("backend calls:", served)
    for n, b in backends.items():
        if b.calls:
            msgs = b.calls[-1]
            print(f"  {n}: got {len(msgs)} messages, roles={[m.get('role') for m in msgs]}, "
                  f"tools={len(b.tools_seen[-1] or [])}, "
                  f"system_chars={sum(len(json.dumps(m.get('content'))) for m in msgs if m.get('role') == 'system')}")
    if resp.headers.get("content-type", "").startswith("text/event-stream"):
        events = []
        for line in resp.text.splitlines():
            if line.startswith("event: "):
                events.append(line[7:])
        print("SSE event sequence:", events)
        data = [json.loads(l[6:]) for l in resp.text.splitlines() if l.startswith("data: ") and l[6:] != "[DONE]"]
        extra = [d.get("kultivait") for d in data if isinstance(d, dict) and d.get("kultivait")]
        print("kultivait metadata in stream:", extra[:1])
    else:
        print("body:", resp.text[:400])
    led = (tmp / "ledger.jsonl")
    if led.exists():
        rec = json.loads(led.read_text().splitlines()[-1])
        print("ledger:", {k: rec.get(k) for k in ("tier", "requested_tier", "fallback_reason", "escalation_id", "verdict", "preprocess_mark", "tokens_in")})
    esc = list((tmp / "escalations").glob("*.json")) if (tmp / "escalations").exists() else []
    print("escalations archived:", len(esc), [f"{p.stat().st_size} B" for p in esc])
