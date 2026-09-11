"""Recording stub that mimics kultivait's route surface (POST /v1/messages and
POST /v1/chat/completions only; everything else 404) and logs what a client
sends. Auth headers are redacted. Usage: python stub_upstream.py PORT LOGFILE
[--full-routes]  (--full-routes also answers count_tokens / models)."""
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT, LOG = int(sys.argv[1]), sys.argv[2]
FULL = "--full-routes" in sys.argv
REDACT = {"x-api-key", "authorization", "cookie"}


def log(rec):
    with open(LOG, "a") as f:
        f.write(json.dumps(rec) + "\n")


class H(BaseHTTPRequestHandler):
    def _body(self):
        n = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(n) if n else b""
        try:
            return json.loads(raw) if raw else None, len(raw)
        except Exception:
            return None, len(raw)

    def _record(self, body, nbytes, status):
        hdr = {k.lower(): ("<redacted:%d chars>" % len(v) if k.lower() in REDACT else v)
               for k, v in self.headers.items()}
        summary = None
        if isinstance(body, dict):
            sys_ = body.get("system")
            summary = {
                "model": body.get("model"), "stream": body.get("stream"),
                "max_tokens": body.get("max_tokens"),
                "n_messages": len(body.get("messages") or []),
                "n_tools": len(body.get("tools") or []),
                "tool_names": [t.get("name") for t in (body.get("tools") or [])][:40],
                "system_chars": len(json.dumps(sys_)) if sys_ is not None else 0,
                "has_thinking": "thinking" in body, "metadata": body.get("metadata"),
                "keys": sorted(body.keys()),
            }
        log({"method": self.command, "path": self.path, "status": status,
             "headers": hdr, "body_bytes": nbytes, "summary": summary})
        if isinstance(body, dict) and self.path.startswith("/v1/messages") and "count_tokens" not in self.path:
            with open(LOG + ".last_body.json", "w") as f:
                json.dump(body, f)

    def _json(self, code, obj):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if FULL and self.path.startswith("/v1/models"):
            self._record(None, 0, 200)
            return self._json(200, {"data": [], "has_more": False})
        self._record(None, 0, 404)
        self._json(404, {"detail": "Not Found"})

    def do_HEAD(self):
        self._record(None, 0, 404)
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        body, n = self._body()
        path = self.path.split("?")[0]
        if path == "/v1/messages/count_tokens" and FULL:
            self._record(body, n, 200)
            return self._json(200, {"input_tokens": 10})
        if path != "/v1/messages" and path != "/v1/chat/completions":
            self._record(body, n, 404)
            return self._json(404, {"detail": "Not Found"})
        self._record(body, n, 200)
        model = (body or {}).get("model", "stub")
        if (body or {}).get("stream"):
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.end_headers()
            ev = [
                ("message_start", {"type": "message_start", "message": {
                    "id": "msg_stub", "type": "message", "role": "assistant", "model": model,
                    "content": [], "stop_reason": None, "stop_sequence": None,
                    "usage": {"input_tokens": 10, "output_tokens": 1}}}),
                ("content_block_start", {"type": "content_block_start", "index": 0,
                                         "content_block": {"type": "text", "text": ""}}),
                ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                         "delta": {"type": "text_delta", "text": "STUB-OK"}}),
                ("content_block_stop", {"type": "content_block_stop", "index": 0}),
                ("message_delta", {"type": "message_delta",
                                   "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                                   "usage": {"output_tokens": 2}}),
                ("message_stop", {"type": "message_stop"}),
            ]
            for name, data in ev:
                self.wfile.write(f"event: {name}\ndata: {json.dumps(data)}\n\n".encode())
                self.wfile.flush()
            return
        return self._json(200, {
            "id": "msg_stub", "type": "message", "role": "assistant", "model": model,
            "content": [{"type": "text", "text": "STUB-OK"}], "stop_reason": "end_turn",
            "stop_sequence": None, "usage": {"input_tokens": 10, "output_tokens": 2}})

    def log_message(self, *a):
        pass


srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
if "--tls" in sys.argv:  # --tls CERT KEY
    import ssl
    i = sys.argv.index("--tls")
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(sys.argv[i + 1], sys.argv[i + 2])
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
srv.serve_forever()
