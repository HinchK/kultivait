"""OpenAI-compatible proxy: weigh locally, route deliberately, tally everything."""

import json
import time
import uuid
from typing import Callable

import numpy as np
from fastapi import FastAPI
from fastapi.responses import StreamingResponse

from kultivait.backends import Backend, Completion
from kultivait.gates import Gate
from kultivait.ledger import Ledger
from kultivait.router import Decision, Router


def _text_of(content) -> str:
    """Message content may be a string or a list of content blocks."""
    if isinstance(content, str):
        return content
    return " ".join(
        block.get("text", "") for block in content if isinstance(block, dict)
    )


def create_app(
    router: Router,
    embed: Callable[[str], np.ndarray],
    backends: dict[str, Backend],
    ledger: Ledger,
    gate: Gate,
) -> FastAPI:
    app = FastAPI(title="kultivait")

    def _record(tier: str, completion: Completion) -> None:
        ledger.record(
            tier=tier,
            local=completion.local,
            tokens_in=completion.tokens_in,
            tokens_out=completion.tokens_out,
            cost_usd=completion.cost_usd,
        )

    def _classify(messages: list[dict]) -> "Decision":
        user_text = next(
            (_text_of(m["content"]) for m in reversed(messages) if m.get("role") == "user"),
            "",
        )
        return router.classify(embed(user_text))

    @app.post("/v1/chat/completions")
    def chat_completions(body: dict):
        messages = body.get("messages", [])
        decision = _classify(messages)

        if body.get("stream"):
            chunk_id = f"kult-{uuid.uuid4().hex[:12]}"
            created = int(time.time())

            def chunk(delta: dict, finish: str | None = None) -> str:
                payload = {
                    "id": chunk_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": decision.tier,
                    "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
                }
                return f"data: {json.dumps(payload)}\n\n"

            def sse():
                yield chunk({"role": "assistant"})
                for item in backends[decision.tier].stream(messages):
                    if isinstance(item, Completion):
                        _record(decision.tier, item)
                        yield chunk({}, finish="stop")
                    else:
                        yield chunk({"content": item})
                yield "data: [DONE]\n\n"

            return StreamingResponse(sse(), media_type="text/event-stream")

        completion = backends[decision.tier].complete(messages)
        _record(decision.tier, completion)
        return {
            "id": f"kult-{uuid.uuid4().hex[:12]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": decision.tier,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": completion.text},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": completion.tokens_in,
                "completion_tokens": completion.tokens_out,
                "total_tokens": completion.tokens_in + completion.tokens_out,
            },
            "kultivait": {
                "tier": decision.tier,
                "margin": decision.margin,
                "escalated": decision.escalated,
                "local": completion.local,
            },
        }

    @app.post("/v1/messages")
    def anthropic_messages(body: dict):
        # Normalize to plain-string messages: backends (ollama, CLIs) don't
        # understand Anthropic content blocks or the separate system param.
        messages = [
            {"role": m.get("role", "user"), "content": _text_of(m.get("content", ""))}
            for m in body.get("messages", [])
        ]
        system = body.get("system")
        if system:
            messages = [{"role": "system", "content": _text_of(system)}, *messages]
        decision = _classify(messages)
        msg_id = f"kult-{uuid.uuid4().hex[:12]}"

        if body.get("stream"):

            def event(etype: str, payload: dict) -> str:
                return f"event: {etype}\ndata: {json.dumps({'type': etype, **payload})}\n\n"

            def sse():
                # input token count isn't known until the backend finishes;
                # real usage arrives in message_delta, per-field zeros here.
                yield event(
                    "message_start",
                    {
                        "message": {
                            "id": msg_id,
                            "type": "message",
                            "role": "assistant",
                            "model": decision.tier,
                            "content": [],
                            "usage": {"input_tokens": 0, "output_tokens": 0},
                        }
                    },
                )
                yield event(
                    "content_block_start",
                    {"index": 0, "content_block": {"type": "text", "text": ""}},
                )
                for item in backends[decision.tier].stream(messages):
                    if isinstance(item, Completion):
                        _record(decision.tier, item)
                        yield event("content_block_stop", {"index": 0})
                        yield event(
                            "message_delta",
                            {
                                "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                                "usage": {
                                    "input_tokens": item.tokens_in,
                                    "output_tokens": item.tokens_out,
                                },
                            },
                        )
                    else:
                        yield event(
                            "content_block_delta",
                            {"index": 0, "delta": {"type": "text_delta", "text": item}},
                        )
                yield event("message_stop", {})

            return StreamingResponse(sse(), media_type="text/event-stream")

        completion = backends[decision.tier].complete(messages)
        _record(decision.tier, completion)
        return {
            "id": msg_id,
            "type": "message",
            "role": "assistant",
            "model": decision.tier,
            "content": [{"type": "text", "text": completion.text}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {
                "input_tokens": completion.tokens_in,
                "output_tokens": completion.tokens_out,
            },
        }

    @app.post("/gate")
    def gate_handoff(body: dict):
        result = gate.distill(
            body["transcript"],
            from_phase=body.get("from_phase", "previous"),
            to_phase=body.get("to_phase", "next"),
        )
        return {
            "brief": result.brief,
            "tokens_before": result.tokens_before,
            "tokens_after": result.tokens_after,
            "compost_id": result.compost_id,
        }

    @app.get("/harvest")
    def harvest():
        return ledger.harvest()

    return app
