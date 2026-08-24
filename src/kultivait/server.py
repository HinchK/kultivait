"""OpenAI-compatible proxy: weigh locally, route deliberately, tally everything."""

import atexit
import hashlib
import json
import os
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, Callable

import httpx
import numpy as np
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from posthog import Posthog

load_dotenv()

from kultivait.backends import Backend, Completion
from kultivait.effort import resolve_effort
from kultivait.escalations import EscalationStore
from kultivait.gates import Gate
from kultivait.ledger import Ledger
from kultivait.preprocessor import (
    MARK_FAIL,
    MARK_OK,
    MARK_SKIPPED,
    MARK_TIMEOUT,
    run as run_preprocessor,
)
from kultivait.router import Decision, Router
from kultivait.tollbooth import (
    RouteOption,
    TollTicket,
    TollboothQueue,
    build_route_menu,
    resolve_auto_policy,
)


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


def _conversation_fingerprint(messages: list[dict]) -> str:
    """Hash of system prompt + first user message to group requests in a conversation."""
    system_text = ""
    first_user_text = ""
    for m in messages:
        role = m.get("role")
        if role == "system" and not system_text:
            system_text = _text_of(m.get("content", ""))
        elif role == "user" and not first_user_text:
            first_user_text = _text_of(m.get("content", ""))
    raw = f"{system_text}\n---\n{first_user_text}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def _apply_rewrite(messages: list[dict], rewrite: str) -> list[dict]:
    """Replace the last user message content with the rewritten prompt."""
    last_user_idx = None
    for i, m in enumerate(messages):
        if m.get("role") == "user":
            last_user_idx = i
    out = []
    for i, m in enumerate(messages):
        if i == last_user_idx:
            out.append({**m, "content": rewrite})
        else:
            out.append(dict(m))
    return out


def _default_preprocess_generate_for(
    chat_base_url: str = "http://localhost:11434",
    runtime: str = "ollama",
    model: str | None = None,
    num_ctx: int = 32768,
):
    import re

    def generate(target_model: str, prompt: str) -> tuple[str, float]:
        actual_model = target_model or model or "qwen3.5:4b"
        messages = [{"role": "user", "content": prompt}]
        t0 = time.monotonic()
        if runtime == "llamacpp":
            payload = {"model": actual_model, "messages": messages, "stream": False}
            r = httpx.post(f"{chat_base_url}/v1/chat/completions", json=payload, timeout=600)
            r.raise_for_status()
            text = r.json()["choices"][0]["message"]["content"] or ""
        else:
            payload = {
                "model": actual_model,
                "messages": messages,
                "stream": False,
                "options": {"num_ctx": num_ctx, "temperature": 0.2, "num_predict": 700},
            }
            if actual_model.startswith("qwen3"):
                payload["think"] = False
            r = httpx.post(f"{chat_base_url}/api/chat", json=payload, timeout=600)
            r.raise_for_status()
            text = r.json()["message"]["content"]
        clean_text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
        return clean_text, time.monotonic() - t0

    return generate


def create_app(
    router: Router,
    embed: Callable[[str], np.ndarray],
    backends: dict[str, Backend],
    ledger: Ledger,
    gate: Gate,
    escalations: EscalationStore,
    preprocess_generate: Callable[[str, str], Any] | None = None,
    preprocess_timeout_s: float = 15.0,
    effort_overrides: dict | None = None,
    tollbooth: TollboothQueue | None = None,
    toll_timeout_s: float = 60.0,
    toll_enabled: bool = True,
) -> FastAPI:
    if preprocess_generate is None:
        preprocess_generate = _default_preprocess_generate_for()

    if tollbooth is None:
        tollbooth = TollboothQueue(
            default_timeout_s=toll_timeout_s,
            enabled=toll_enabled,
            escalations=escalations,
            ledger=ledger,
        )

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
        fingerprint = _conversation_fingerprint(messages)
        target_fits_dict = None
        route_choice = None
        toll_mark = "skipped"

        is_contested = decision.escalated or decision.margin < router._margin

        if not is_contested:
            preprocess_mark = MARK_SKIPPED
            target_tier = decision.tier
            tier, fallback_reason = _resolve_tier(target_tier, tools)
            verdict = "frontier" if (backends.get(tier) and not backends[tier].local) else "local"
            max_fit = 0.0
            subtask_candidates_count = 0
            canonical_effort = "balanced"
            cli_effort_flags = []
            effort_flags = None
            model_override = None
            dispatch_messages = messages
        else:
            prep_result = run_preprocessor(
                messages,
                generate=preprocess_generate,
                timeout_s=preprocess_timeout_s,
            )
            preprocess_mark = prep_result.mark
            max_fit = prep_result.max_fit
            subtask_candidates_count = len(prep_result.analysis.subtask_candidates)
            target_fits_dict = {tf.target: tf.fit for tf in prep_result.target_fits}

            if prep_result.mark == MARK_OK and prep_result.derived_verdict is not None:
                derived_verdict = prep_result.derived_verdict
                if derived_verdict == "local":
                    verdict = "local"
                    target_tier = router.capability_order[0]
                    tier, fallback_reason = _resolve_tier(target_tier, tools)
                    dispatch_messages = messages
                    effort_plan = resolve_effort(
                        complexity=prep_result.analysis.complexity,
                        task_type=prep_result.analysis.task_type,
                        target_cli=tier,
                        overrides=effort_overrides,
                    )
                    canonical_effort = effort_plan.canonical
                    cli_effort_flags = effort_plan.cli_flags
                    effort_flags = None
                    model_override = None
                elif derived_verdict == "frontier":
                    verdict = "frontier"
                    target_tier = router.capability_order[-1]
                    tier, fallback_reason = _resolve_tier(target_tier, tools)
                    backend = backends.get(tier)
                    if backend and not backend.local:
                        dispatch_messages = _apply_rewrite(messages, prep_result.rewrite)
                    else:
                        dispatch_messages = messages
                    effort_plan = resolve_effort(
                        complexity=prep_result.analysis.complexity,
                        task_type=prep_result.analysis.task_type,
                        target_cli=tier,
                        overrides=effort_overrides,
                    )
                    canonical_effort = effort_plan.canonical
                    cli_effort_flags = effort_plan.cli_flags
                    effort_flags = effort_plan.cli_flags
                    model_override = effort_plan.model_override
                else:  # contested
                    user_text = next(
                        (_text_of(m["content"]) for m in reversed(messages) if m.get("role") == "user"),
                        "",
                    )
                    local_tier = router.capability_order[0]
                    local_backend = backends.get(local_tier)
                    local_serving_capable = bool(local_backend and (not tools or local_backend.supports_tools))
                    installed_clis = [name for name, b in backends.items() if not b.local]

                    options = build_route_menu(
                        target_fits=prep_result.target_fits,
                        installed_clis=installed_clis,
                        analysis=prep_result.analysis,
                        rewrite=prep_result.rewrite,
                        original_prompt=user_text,
                        local_tier_name=local_tier,
                        pricing=None,
                        effort_overrides=effort_overrides,
                    )
                    default_auto = resolve_auto_policy(options, local_serving_capable=local_serving_capable)
                    ticket = TollTicket(
                        ticket_id=f"toll-{uuid.uuid4().hex[:8]}",
                        fingerprint=fingerprint,
                        created_at=time.time(),
                        timeout_s=tollbooth.default_timeout_s,
                        options=options,
                        default_auto_choice=default_auto,
                        original_prompt=user_text,
                        task_type=prep_result.analysis.task_type,
                        complexity=prep_result.analysis.complexity,
                    )
                    route_choice, toll_mark, effort_override = tollbooth.hold_ticket(ticket)

                    if "local" in route_choice:
                        verdict = "local"
                        target_tier = local_tier
                        tier, fallback_reason = _resolve_tier(target_tier, tools)
                        dispatch_messages = messages
                        canonical_effort = "balanced"
                        cli_effort_flags = []
                        effort_flags = None
                        model_override = None
                        if route_choice.startswith("human:local") or route_choice == "human:local":
                            escalations.save(messages, requested_tier="local")
                    else:
                        target_cli = route_choice.split(":")[-1]
                        target_tier = target_cli
                        tier, fallback_reason = _resolve_tier(target_tier, tools)
                        verdict = "frontier"
                        backend = backends.get(tier)
                        if backend and not backend.local:
                            dispatch_messages = _apply_rewrite(messages, prep_result.rewrite)
                        else:
                            dispatch_messages = messages

                        if effort_override:
                            eff_overrides = {**(effort_overrides or {}), target_cli: effort_override}
                            effort_plan = resolve_effort(
                                complexity=prep_result.analysis.complexity,
                                task_type=prep_result.analysis.task_type,
                                target_cli=tier,
                                overrides=eff_overrides,
                            )
                        else:
                            selected_opt = next((o for o in options if o.target == target_cli), None)
                            if selected_opt:
                                effort_plan = selected_opt.effort
                            else:
                                effort_plan = resolve_effort(
                                    complexity=prep_result.analysis.complexity,
                                    task_type=prep_result.analysis.task_type,
                                    target_cli=tier,
                                    overrides=effort_overrides,
                                )
                        canonical_effort = effort_plan.canonical
                        cli_effort_flags = effort_plan.cli_flags
                        effort_flags = effort_plan.cli_flags
                        model_override = effort_plan.model_override
            else:
                tier, fallback_reason = _resolve_tier(decision.tier, tools)
                verdict = "frontier" if (backends.get(tier) and not backends[tier].local) else "local"
                dispatch_messages = messages
                canonical_effort = "balanced"
                cli_effort_flags = []
                effort_flags = None
                model_override = None

        # A silent downgrade must leave a recoverable trail: archive the full
        # conversation so a paste-ready brief can be distilled on demand.
        escalation_id = (
            escalations.save(messages, requested_tier=decision.tier)
            if fallback_reason
            else None
        )
        meta = _decision_meta(decision, fallback_reason, messages)
        meta.update(
            {
                "escalation_id": escalation_id,
                "fingerprint": fingerprint,
                "preprocess_mark": preprocess_mark,
                "verdict": verdict,
                "max_fit": max_fit,
                "canonical_effort": canonical_effort,
                "cli_effort_flags": cli_effort_flags,
                "toll": toll_mark,
                "route_choice": route_choice,
                "subtask_candidates": subtask_candidates_count,
                "target_fits": target_fits_dict,
            }
        )

        def kultivait_meta(local: bool) -> dict:
            return {
                "tier": tier,
                "margin": decision.margin,
                "escalated": decision.escalated,
                "fallback_reason": fallback_reason,
                "escalation_id": escalation_id,
                "local": local,
                "verdict": verdict,
                "max_fit": max_fit,
                "preprocess_mark": preprocess_mark,
                "subtask_candidates": subtask_candidates_count,
                "canonical_effort": canonical_effort,
                "cli_effort_flags": cli_effort_flags,
                "fingerprint": fingerprint,
                "toll": toll_mark,
                "route_choice": route_choice,
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
                for item in backends[tier].stream(
                    dispatch_messages,
                    tools=tools,
                    effort_flags=effort_flags,
                    model_override=model_override,
                ):
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

        completion = backends[tier].complete(
            dispatch_messages,
            tools=tools,
            effort_flags=effort_flags,
            model_override=model_override,
        )
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
        fingerprint = _conversation_fingerprint(messages)
        target_fits_dict = None
        route_choice = None
        toll_mark = "skipped"
        escalation_id = None

        is_contested = decision.escalated or decision.margin < router._margin

        if not is_contested:
            preprocess_mark = MARK_SKIPPED
            target_tier = decision.tier
            tier, fallback_reason = _resolve_tier(target_tier, None)
            verdict = "frontier" if (backends.get(tier) and not backends[tier].local) else "local"
            max_fit = 0.0
            subtask_candidates_count = 0
            canonical_effort = "balanced"
            cli_effort_flags = []
            effort_flags = None
            model_override = None
            dispatch_messages = messages
        else:
            prep_result = run_preprocessor(
                messages,
                generate=preprocess_generate,
                timeout_s=preprocess_timeout_s,
            )
            preprocess_mark = prep_result.mark
            max_fit = prep_result.max_fit
            subtask_candidates_count = len(prep_result.analysis.subtask_candidates)
            target_fits_dict = {tf.target: tf.fit for tf in prep_result.target_fits}

            if prep_result.mark == MARK_OK and prep_result.derived_verdict is not None:
                derived_verdict = prep_result.derived_verdict
                if derived_verdict == "local":
                    verdict = "local"
                    target_tier = router.capability_order[0]
                    tier, fallback_reason = _resolve_tier(target_tier, None)
                    dispatch_messages = messages
                    effort_plan = resolve_effort(
                        complexity=prep_result.analysis.complexity,
                        task_type=prep_result.analysis.task_type,
                        target_cli=tier,
                        overrides=effort_overrides,
                    )
                    canonical_effort = effort_plan.canonical
                    cli_effort_flags = effort_plan.cli_flags
                    effort_flags = None
                    model_override = None
                elif derived_verdict == "frontier":
                    verdict = "frontier"
                    target_tier = router.capability_order[-1]
                    tier, fallback_reason = _resolve_tier(target_tier, None)
                    backend = backends.get(tier)
                    if backend and not backend.local:
                        dispatch_messages = _apply_rewrite(messages, prep_result.rewrite)
                    else:
                        dispatch_messages = messages
                    effort_plan = resolve_effort(
                        complexity=prep_result.analysis.complexity,
                        task_type=prep_result.analysis.task_type,
                        target_cli=tier,
                        overrides=effort_overrides,
                    )
                    canonical_effort = effort_plan.canonical
                    cli_effort_flags = effort_plan.cli_flags
                    effort_flags = effort_plan.cli_flags
                    model_override = effort_plan.model_override
                else:  # contested
                    user_text = next(
                        (_text_of(m["content"]) for m in reversed(messages) if m.get("role") == "user"),
                        "",
                    )
                    local_tier = router.capability_order[0]
                    local_backend = backends.get(local_tier)
                    local_serving_capable = bool(local_backend and local_backend.supports_tools)
                    installed_clis = [name for name, b in backends.items() if not b.local]

                    options = build_route_menu(
                        target_fits=prep_result.target_fits,
                        installed_clis=installed_clis,
                        analysis=prep_result.analysis,
                        rewrite=prep_result.rewrite,
                        original_prompt=user_text,
                        local_tier_name=local_tier,
                        pricing=None,
                        effort_overrides=effort_overrides,
                    )
                    default_auto = resolve_auto_policy(options, local_serving_capable=local_serving_capable)
                    ticket = TollTicket(
                        ticket_id=f"toll-{uuid.uuid4().hex[:8]}",
                        fingerprint=fingerprint,
                        created_at=time.time(),
                        timeout_s=tollbooth.default_timeout_s,
                        options=options,
                        default_auto_choice=default_auto,
                        original_prompt=user_text,
                        task_type=prep_result.analysis.task_type,
                        complexity=prep_result.analysis.complexity,
                    )
                    route_choice, toll_mark, effort_override = tollbooth.hold_ticket(ticket)

                    if "local" in route_choice:
                        verdict = "local"
                        target_tier = local_tier
                        tier, fallback_reason = _resolve_tier(target_tier, None)
                        dispatch_messages = messages
                        canonical_effort = "balanced"
                        cli_effort_flags = []
                        effort_flags = None
                        model_override = None
                        if route_choice.startswith("human:local") or route_choice == "human:local":
                            escalation_id = escalations.save(messages, requested_tier="local")
                    else:
                        target_cli = route_choice.split(":")[-1]
                        target_tier = target_cli
                        tier, fallback_reason = _resolve_tier(target_tier, None)
                        verdict = "frontier"
                        backend = backends.get(tier)
                        if backend and not backend.local:
                            dispatch_messages = _apply_rewrite(messages, prep_result.rewrite)
                        else:
                            dispatch_messages = messages

                        if effort_override:
                            eff_overrides = {**(effort_overrides or {}), target_cli: effort_override}
                            effort_plan = resolve_effort(
                                complexity=prep_result.analysis.complexity,
                                task_type=prep_result.analysis.task_type,
                                target_cli=tier,
                                overrides=eff_overrides,
                            )
                        else:
                            selected_opt = next((o for o in options if o.target == target_cli), None)
                            if selected_opt:
                                effort_plan = selected_opt.effort
                            else:
                                effort_plan = resolve_effort(
                                    complexity=prep_result.analysis.complexity,
                                    task_type=prep_result.analysis.task_type,
                                    target_cli=tier,
                                    overrides=effort_overrides,
                                )
                        canonical_effort = effort_plan.canonical
                        cli_effort_flags = effort_plan.cli_flags
                        effort_flags = effort_plan.cli_flags
                        model_override = effort_plan.model_override
            else:
                tier, fallback_reason = _resolve_tier(decision.tier, None)
                verdict = "frontier" if (backends.get(tier) and not backends[tier].local) else "local"
                dispatch_messages = messages
                canonical_effort = "balanced"
                cli_effort_flags = []
                effort_flags = None
                model_override = None

        if fallback_reason and not escalation_id:
            escalation_id = escalations.save(messages, requested_tier=decision.tier)

        meta = _decision_meta(decision, fallback_reason, messages)
        meta.update(
            {
                "escalation_id": escalation_id,
                "fingerprint": fingerprint,
                "preprocess_mark": preprocess_mark,
                "verdict": verdict,
                "max_fit": max_fit,
                "canonical_effort": canonical_effort,
                "cli_effort_flags": cli_effort_flags,
                "toll": toll_mark,
                "route_choice": route_choice,
                "subtask_candidates": subtask_candidates_count,
                "target_fits": target_fits_dict,
            }
        )
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
                            "model": tier,
                            "content": [],
                            "usage": {"input_tokens": 0, "output_tokens": 0},
                        }
                    },
                )
                yield event(
                    "content_block_start",
                    {"index": 0, "content_block": {"type": "text", "text": ""}},
                )
                for item in backends[tier].stream(
                    dispatch_messages,
                    effort_flags=effort_flags,
                    model_override=model_override,
                ):
                    if isinstance(item, Completion):
                        _record(tier, item, **meta)
                        _capture(
                            "message_completion_completed",
                            request,
                            {
                                "tier": tier,
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
                                    "total_cost_usd": item.cost_usd,
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

        completion = backends[tier].complete(
            dispatch_messages,
            effort_flags=effort_flags,
            model_override=model_override,
        )
        _record(tier, completion, **meta)
        _capture(
            "message_completion_completed",
            request,
            {
                "tier": tier,
                "local": completion.local,
                "streaming": False,
            },
        )
        return {
            "id": msg_id,
            "type": "message",
            "role": "assistant",
            "model": tier,
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
