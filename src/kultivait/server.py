"""OpenAI-compatible proxy: weigh locally, route deliberately, tally everything."""

import atexit
import json
import os
import time
import uuid
from contextlib import asynccontextmanager
from typing import Callable

import numpy as np
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from posthog import Posthog

load_dotenv()

from kultivait.backends import Backend, Completion
from kultivait.escalations import EscalationStore
from kultivait.gates import Gate
from kultivait.ledger import Ledger
from kultivait.router import Decision, Router


def _text_of(content) -> str:
    """Message content may be a string or a list of content blocks/parts."""
    if isinstance(content, str):
        return content
    return " ".join(
        block.get("text", "") for block in content if isinstance(block, dict)
    )


def _normalize(messages: list[dict]) -> list[dict]:
    """Flatten content blocks/parts to plain strings: backends (ollama, CLIs)
    understand neither Anthropic blocks nor OpenAI content parts.
    Tool plumbing (assistant tool_calls, tool results) is preserved."""
    out = []
    for m in messages:
        norm = {"role": m.get("role", "user"), "content": _text_of(m.get("content") or "")}
        if m.get("tool_calls"):
            norm["tool_calls"] = m["tool_calls"]
        if m.get("tool_call_id"):
            norm["tool_call_id"] = m["tool_call_id"]
        out.append(norm)
    return out


def create_app(
    router: Router,
    embed: Callable[[str], np.ndarray],
    backends: dict[str, Backend],
    ledger: Ledger,
    gate: Gate,
    escalations: EscalationStore,
) -> FastAPI:
    project_token = os.getenv("POSTHOG_PROJECT_TOKEN")
    posthog_client = (
        Posthog(
            project_token,
            host=os.getenv("POSTHOG_HOST"),
            enable_exception_autocapture=True,
        )
        if project_token
        else None
    )
    if posthog_client:
        atexit.register(posthog_client.shutdown)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        if posthog_client:
            posthog_client.shutdown()

    app = FastAPI(title="kultivait", lifespan=lifespan)

    def _capture(event: str, request: Request, properties: dict) -> None:
        if posthog_client:
            posthog_client.capture(
                event,
                distinct_id="kultivait-proxy",
                properties={"$process_person_profile": False, **properties},
            )

    def _record(tier: str, completion: Completion, **decision_meta) -> None:
        ledger.record(
            tier=tier,
            local=completion.local,
            tokens_in=completion.tokens_in,
            tokens_out=completion.tokens_out,
            cost_usd=completion.cost_usd,
            truncated=completion.truncated,
            **decision_meta,
        )

    def _decision_meta(
        decision: Decision, fallback_reason: "str | None", messages: list[dict]
    ) -> dict:
        user_text = next(
            (m["content"] for m in reversed(messages) if m.get("role") == "user"), ""
        )
        return {
            "requested_tier": decision.tier,
            "margin": round(decision.margin, 4),
            "escalated": decision.escalated,
            "fallback_reason": fallback_reason,
            "snippet": user_text[:80],
        }

    def _classify(messages: list[dict]) -> "Decision":
        user_text = next(
            (_text_of(m["content"]) for m in reversed(messages) if m.get("role") == "user"),
            "",
        )
        return router.classify(embed(user_text))

    def _resolve_tier(tier: str, tools: "list | None") -> "tuple[str, str | None]":
        """Returns (served_tier, fallback_reason). Falls back when the
        classified tier has no backend (virtual frontier tiers in local-only
        setups) or can't do client-side tool calls (cloud CLIs run their own
        agent loops). Fallback picks the most capable serving-capable tier."""
        def serves(name: str) -> bool:
            backend = backends.get(name)
            return backend is not None and (not tools or backend.supports_tools)

        if serves(tier):
            return tier, None
        reason = "no_backend" if tier not in backends else "tools_unsupported"
        for name in reversed(router.capability_order):
            if serves(name):
                return name, reason
        raise RuntimeError("no serving-capable backend configured")

    @app.post("/v1/chat/completions")
    def chat_completions(body: dict, request: Request):
        messages = _normalize(body.get("messages", []))
        tools = body.get("tools")
        decision = _classify(messages)
        tier, fallback_reason = _resolve_tier(decision.tier, tools)
        # A silent downgrade must leave a recoverable trail: archive the full
        # conversation so a paste-ready brief can be distilled on demand.
        escalation_id = (
            escalations.save(messages, requested_tier=decision.tier)
            if fallback_reason
            else None
        )
        meta = _decision_meta(decision, fallback_reason, messages)
        meta["escalation_id"] = escalation_id

        def kultivait_meta(local: bool) -> dict:
            return {
                "tier": tier,
                "margin": decision.margin,
                "escalated": decision.escalated,
                "fallback_reason": fallback_reason,
                "escalation_id": escalation_id,
                "local": local,
            }

        if body.get("stream"):
            chunk_id = f"kult-{uuid.uuid4().hex[:12]}"
            created = int(time.time())

            def chunk(delta: dict, finish: str | None = None) -> str:
                payload = {
                    "id": chunk_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": tier,
                    "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
                }
                return f"data: {json.dumps(payload)}\n\n"

            def sse():
                yield chunk({"role": "assistant"})
                for item in backends[tier].stream(messages, tools=tools):
                    if isinstance(item, Completion):
                        _record(tier, item, **meta)
                        _capture(
                            "chat_completion_completed",
                            request,
                            {
                                "tier": tier,
                                "local": item.local,
                                "streaming": True,
                                "fallback_reason": fallback_reason,
                                "has_tool_calls": bool(item.tool_calls),
                            },
                        )
                        if item.tool_calls:
                            yield chunk(
                                {
                                    "tool_calls": [
                                        {**tc, "index": i}
                                        for i, tc in enumerate(item.tool_calls)
                                    ]
                                }
                            )
                            yield chunk({}, finish="tool_calls")
                        else:
                            yield chunk({}, finish="stop")
                    else:
                        yield chunk({"content": item})
                yield "data: [DONE]\n\n"

            return StreamingResponse(sse(), media_type="text/event-stream")

        completion = backends[tier].complete(messages, tools=tools)
        _record(tier, completion, **meta)
        _capture(
            "chat_completion_completed",
            request,
            {
                "tier": tier,
                "local": completion.local,
                "streaming": False,
                "fallback_reason": fallback_reason,
                "has_tool_calls": bool(completion.tool_calls),
            },
        )
        message: dict = {"role": "assistant", "content": completion.text or None}
        if completion.tool_calls:
            message["tool_calls"] = completion.tool_calls
        return {
            "id": f"kult-{uuid.uuid4().hex[:12]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": tier,
            "choices": [
                {
                    "index": 0,
                    "message": message,
                    "finish_reason": "tool_calls" if completion.tool_calls else "stop",
                }
            ],
            "usage": {
                "prompt_tokens": completion.tokens_in,
                "completion_tokens": completion.tokens_out,
                "total_tokens": completion.tokens_in + completion.tokens_out,
            },
            "kultivait": kultivait_meta(completion.local),
        }

    @app.post("/v1/messages")
    def anthropic_messages(body: dict, request: Request):
        messages = _normalize(body.get("messages", []))
        system = body.get("system")
        if system:
            messages = [{"role": "system", "content": _text_of(system)}, *messages]
        decision = _classify(messages)
        meta = _decision_meta(decision, None, messages)
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
                        _record(decision.tier, item, **meta)
                        _capture(
                            "message_completion_completed",
                            request,
                            {
                                "tier": decision.tier,
                                "local": item.local,
                                "streaming": True,
                            },
                        )
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
        _record(decision.tier, completion, **meta)
        _capture(
            "message_completion_completed",
            request,
            {
                "tier": decision.tier,
                "local": completion.local,
                "streaming": False,
            },
        )
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
    def gate_handoff(body: dict, request: Request):
        result = gate.distill(
            body["transcript"],
            from_phase=body.get("from_phase", "previous"),
            to_phase=body.get("to_phase", "next"),
        )
        _capture(
            "handoff_brief_created",
            request,
            {
                "from_phase": body.get("from_phase", "previous"),
                "to_phase": body.get("to_phase", "next"),
                "tokens_before": result.tokens_before,
                "tokens_after": result.tokens_after,
            },
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
