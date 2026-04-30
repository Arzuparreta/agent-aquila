"""Core agent loop, dispatch, and run management."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.envelope_crypto import KeyDecryptError
from app.models.agent_run import AgentRun, AgentRunStep, AgentTraceEvent
from app.models.chat_message import ChatMessage
from app.models.connector_connection import ConnectorConnection
from app.models.pending_proposal import PendingProposal
from app.models.user import User
from app.schemas.agent import (
    AgentRunAttentionRead, AgentRunRead, AgentRunSummaryRead,
    AgentStepRead, AgentTraceEventRead, PendingProposalRead,
)
from app.services.ai_providers import provider_kind_requires_api_key
from app.services.agent.runtime import (
    NoActiveProviderError, LLMProviderError,
    estimate_message_tokens, plan_budget, clamp_tool_content_by_tokens,
    content_sha256_preview,
)
from app.services.user_ai_settings_service import UserAISettingsService
from app.services.agent.harness.native import chat_turn_native
from app.services.agent.dispatch import TOOL_DISPATCH, TOOL_NAMES
from app.services.agent_tools import FINAL_ANSWER_TOOL_NAME
from app.services.agent.harness.effective import (
    effective_tool_palette_mode_for_turn,
    resolve_max_tool_steps_for_turn,
)
from app.services.agent.memory.post_turn import heuristic_wants_post_turn_extraction
from app.schemas.agent_turn_profile import TURN_PROFILE_USER_CHAT, normalize_turn_profile
from app.services.agent_workspace import build_system_prompt, linked_connector_providers
from app.services.agent.user_context import injectable_user_context_section
from app.services.agent.trace import (
    EV_LLM_REQUEST, EV_LLM_RESPONSE, EV_RUN_STARTED,
    EV_RUN_COMPLETED, EV_RUN_FAILED, EV_TOOL_STARTED,
    EV_TOOL_FINISHED, emit_trace_event,
    new_trace_id, new_span_id,
)
from app.services.agent.replay import AgentReplayContext
from app.services.agent.proposal import proposal_to_read
from app.services.agent.runtime_clients import TokenManager
from app.services.agent_runtime_config_service import resolve_for_user
from app.services.agent.trace import (
    _conversation_trace_snapshot, _trim_step_payload_for_client,
    _approx_prompt_tokens, _assistant_message_from,
    _is_context_overflow, _reduce_conversation_for_budget,
)
from app.services.agent.run_attention import build_attention_snapshot
from app.services.agent_tools import filter_tools_for_user_connectors, tools_for_palette_mode
from app.services.llm_client import ChatResponse
from app.services.model_limits_service import resolve_model_limits
from app.services.user_time_context import normalize_time_format

_logger = logging.getLogger(__name__)

_replay_ctx: ContextVar[AgentReplayContext | None] = ContextVar("agent_replay", default=None)
_agent_ctx: ContextVar[dict[str, Any]] = ContextVar("agent_ctx", default={})


# ---------------------------------------------------------------------------
# Tool dispatch
# ---------------------------------------------------------------------------

async def _dispatch_tool(
    db: AsyncSession, user: User, run_id: int,
    thread_id: int | None, call: Any,
) -> tuple[dict[str, Any], PendingProposal | None]:
    """Execute one model-issued tool call."""
    del thread_id
    tool_name = call.name or ""
    args = call.arguments if isinstance(call.arguments, dict) else {}

    if tool_name not in TOOL_NAMES:
        return ({"error": f"unknown tool {tool_name!r}"}, None)

    replay = _replay_ctx.get()
    if replay is not None:
        result = replay.next_tool_result()
        prop_id = result.get("proposal_id") if isinstance(result, dict) else None
        if prop_id:
            prop = await db.get(PendingProposal, int(prop_id))
            return (result, prop)
        return (result, None)

    entry = TOOL_DISPATCH.get(tool_name)
    if entry is None:
        return ({"error": f"unhandled tool: {tool_name}"}, None)
    handler, takes_run_id = entry

    try:
        if takes_run_id:
            result = await handler(db, user, run_id, args)
        else:
            result = await handler(db, user, args)
    except Exception as exc:  # noqa: BLE001
        return ({"error": str(exc)[:500]}, None)

    prop_id = result.get("proposal_id") if isinstance(result, dict) else None
    if prop_id:
        prop = await db.get(PendingProposal, int(prop_id))
        return (result, prop)
    return (result, None)


# ---------------------------------------------------------------------------
# Run lifecycle
# ---------------------------------------------------------------------------

async def run_agent_invalid_preflight(
    db: AsyncSession, user: User, message: str,
    *, thread_id: int | None = None,
) -> AgentRunRead | None:
    settings_row = await UserAISettingsService.get_or_create(db, user)
    if getattr(settings_row, "agent_processing_paused", False):
        run = AgentRun(
            user_id=user.id, status="failed", user_message=message,
            error="The agent is paused. Resume it from the dashboard (Settings).",
            chat_thread_id=thread_id,
        )
        db.add(run)
        await db.commit()
        await db.refresh(run)
        return _to_read(run, [], [])
    if settings_row.ai_disabled:
        run = AgentRun(
            user_id=user.id, status="failed", user_message=message,
            error="AI is disabled for this user", chat_thread_id=thread_id,
        )
        db.add(run)
        await db.commit()
        await db.refresh(run)
        return _to_read(run, [], [])
    api_key = await UserAISettingsService.get_api_key(db, user)
    if provider_kind_requires_api_key(settings_row.provider_kind) and not api_key:
        run = AgentRun(
            user_id=user.id, status="failed", user_message=message,
            error="API key not configured", chat_thread_id=thread_id,
        )
        db.add(run)
        await db.commit()
        await db.refresh(run)
        return _to_read(run, [], [])
    return None


async def abort_pending_run_queue_unavailable(
    db: AsyncSession, *, run: AgentRun, placeholder_message: ChatMessage,
) -> AgentRunRead:
    err = (
        "Could not start the assistant: the job queue is unavailable. "
        "Ensure Redis and the ARQ worker are running and REDIS_URL is set."
    )
    run.status = "failed"
    run.error = err
    placeholder_message.role = "system"
    placeholder_message.content = err
    await db.commit()
    await db.refresh(run)
    await db.refresh(placeholder_message)
    return _to_read(run, [], [])


async def create_pending_agent_run(
    db: AsyncSession, user: User, message: str,
    *, thread_id: int | None = None,
    turn_profile: str = TURN_PROFILE_USER_CHAT,
) -> AgentRun:
    root_trace = new_trace_id()
    run = AgentRun(
        user_id=user.id, status="pending", user_message=message,
        root_trace_id=root_trace, chat_thread_id=thread_id,
        turn_profile=normalize_turn_profile(turn_profile),
    )
    db.add(run)
    await db.flush()
    return run


async def run_agent(
    db: AsyncSession, user: User, message: str,
    *, prior_messages: list[dict[str, str]] | None = None,
    thread_id: int | None = None,
    thread_context_hint: str | None = None,
    replay: AgentReplayContext | None = None,
    turn_profile: str | None = None,
    agent_ctx: dict[str, Any] | None = None,
) -> AgentRunRead:
    early = await run_agent_invalid_preflight(db, user, message, thread_id=thread_id)
    if early is not None:
        return early

    root_trace = new_trace_id()
    tpf = normalize_turn_profile(turn_profile)
    run = AgentRun(
        user_id=user.id, status="running", user_message=message,
        root_trace_id=root_trace, chat_thread_id=thread_id, turn_profile=tpf,
    )
    db.add(run)
    await db.flush()

    ctx_token = None
    if agent_ctx:
        ctx_token = _agent_ctx.set(agent_ctx)

    try:
        return await _execute_agent_loop(
            db, user, run,
            prior_messages=prior_messages,
            thread_context_hint=thread_context_hint,
            replay=replay,
        )
    finally:
        if ctx_token is not None:
            _agent_ctx.reset(ctx_token)


# ---------------------------------------------------------------------------
# Main ReAct loop (native harness only)
# ---------------------------------------------------------------------------

async def _execute_agent_loop(
    db: AsyncSession, user: User, run: AgentRun,
    *, prior_messages: list[dict[str, str]] | None = None,
    thread_context_hint: str | None = None,
    replay: AgentReplayContext | None = None,
    tool_palette_override: list[dict[str, Any]] | None = None,
    system_prompt_override: str | None = None,
    max_tool_steps_override: int | None = None,
) -> AgentRunRead:
    message = run.user_message
    thread_id = run.chat_thread_id
    settings_row = await UserAISettingsService.get_or_create(db, user)
    rt = await resolve_for_user(db, user)
    api_key = await UserAISettingsService.get_api_key(db, user)
    tp = normalize_turn_profile(getattr(run, "turn_profile", None) or TURN_PROFILE_USER_CHAT)
    eff_max = resolve_max_tool_steps_for_turn(rt, tp)
    if max_tool_steps_override is not None:
        eff_max = int(max_tool_steps_override)

    if tool_palette_override is not None:
        turn_tools = tool_palette_override
    else:
        from app.services.agent_service import resolve_turn_tool_palette
        turn_tools = await resolve_turn_tool_palette(db, user, turn_profile=tp)

    user_ctx_block = await injectable_user_context_section(
        db, user, settings_row=settings_row, turn_profile=tp,
        inject_in_chat=rt.agent_inject_user_context_in_chat,
    )

    root_trace = run.root_trace_id or new_trace_id()
    if run.root_trace_id is None:
        run.root_trace_id = root_trace
    root_span = new_span_id()

    await emit_trace_event(db, run_id=run.id, event_type=EV_RUN_STARTED,
        trace_id=root_trace, span_id=root_span, payload={
            "schema": "agent_trace.v1",
            "user_message_sha256": content_sha256_preview(message),
            "thread_id": thread_id,
            "tool_palette_size": len(turn_tools),
            "harness_mode_effective": "native",
            "replay": replay is not None,
            "memory_flush": tool_palette_override is not None,
            "turn_profile": tp,
            "max_tool_steps_effective": eff_max,
        })

    system_prompt = (
        system_prompt_override
        if system_prompt_override is not None
        else await build_system_prompt(
            db, user, tool_palette=turn_tools,
            thread_context_hint=thread_context_hint,
            user_timezone=getattr(settings_row, "user_timezone", None),
            time_format=normalize_time_format(getattr(settings_row, "time_format", None)),
            prompt_tier=rt.agent_prompt_tier,
            agent_processing_paused=bool(getattr(settings_row, "agent_processing_paused", False)),
            runtime=rt, turn_profile=tp,
            injected_user_context=user_ctx_block,
            max_tool_steps_effective=eff_max,
        )
    )

    conversation: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    if prior_messages:
        conversation.extend(
            {"role": str(m.get("role") or "user"), "content": str(m.get("content") or "")}
            for m in prior_messages if m.get("content")
        )
    conversation.append({"role": "user", "content": message})

    model_limits = await resolve_model_limits(
        api_key=api_key or "", settings_row=settings_row, model=settings_row.chat_model,
    )
    budget = plan_budget(messages=conversation, limits=model_limits)
    if rt.context_budget_v2 and budget.compacted:
        conversation, _ = _reduce_conversation_for_budget(
            conversation, input_budget_tokens=budget.input_budget)
        budget = plan_budget(messages=conversation, limits=model_limits)

    step_idx = 0
    proposals_created: list[PendingProposal] = []

    if thread_id is not None:
        db.add(AgentRunStep(
            run_id=run.id, step_index=0, kind="meta", name="thread",
            payload={"thread_id": int(thread_id)},
        ))

    _replay_token = None
    if replay is not None:
        _replay_token = _replay_ctx.set(replay)

    try:
        final_answer_text: str | None = None
        max_steps = eff_max
        overflow_retried = False
        empty_response_retried = False
        empty_gmail_search_streak = 0
        empty_gmail_queries: list[str] = []

        for _ in range(max_steps):
            await db.refresh(run)
            if run.cancel_requested:
                run.cancel_requested = False
                run.status = "cancelled"
                run.assistant_reply = (run.assistant_reply or "").strip() or "Generation stopped."
                break

            llm_span = new_span_id()
            await emit_trace_event(db, run_id=run.id, event_type=EV_LLM_REQUEST,
                trace_id=root_trace, span_id=llm_span, parent_span_id=root_span, payload={
                    "approx_prompt_tokens": _approx_prompt_tokens(conversation),
                    "estimated_prompt_tokens": estimate_message_tokens(conversation),
                    "input_budget_tokens": budget.input_budget,
                    "reserved_output_tokens": budget.reserved_output_tokens,
                    "tool_defs_count": len(turn_tools),
                    "turn_profile": tp,
                })

            _llm_t0 = time.monotonic()
            try:
                response = await chat_turn_native(
                    api_key or "", settings_row, messages=conversation,
                    tools=turn_tools,
                    require_tool_choice=rt.agent_tool_choice_required,
                    temperature=0.15,
                    max_tokens=budget.reserved_output_tokens if rt.context_budget_v2 else None,
                )
            except LLMProviderError as exc:
                if rt.context_budget_v2 and _is_context_overflow(exc) and not overflow_retried:
                    overflow_retried = True
                    tighter_output = max(256, budget.reserved_output_tokens // 2)
                    budget = plan_budget(messages=conversation, limits=model_limits,
                                         requested_output_tokens=tighter_output)
                    conversation, _ = _reduce_conversation_for_budget(
                        conversation, input_budget_tokens=budget.input_budget)
                    continue
                raise

            _llm_duration_ms = int((time.monotonic() - _llm_t0) * 1000)

            step_idx += 1
            await emit_trace_event(db, run_id=run.id, event_type=EV_LLM_RESPONSE,
                trace_id=root_trace, span_id=llm_span, parent_span_id=root_span,
                step_index=step_idx, payload={
                    "finish_reason": response.finish_reason,
                    "usage": response.usage,
                    "tool_call_names": [tc.name for tc in response.tool_calls],
                    "has_tool_calls": response.has_tool_calls,
                    "duration_ms": _llm_duration_ms,
                })

            db.add(AgentRunStep(
                run_id=run.id, step_index=step_idx, kind="llm", name="turn", payload={
                    "content": (response.content or "")[:4000],
                    "tool_calls": [{"name": tc.name, "arguments": tc.arguments}
                                   for tc in response.tool_calls],
                    "finish_reason": response.finish_reason,
                    "raw_response_text": (response.content or "")[:20000],
                    "raw_request_messages": _conversation_trace_snapshot(conversation),
                    "usage": response.usage,
                    "approx_prompt_tokens": _approx_prompt_tokens(conversation),
                }))

            if not response.has_tool_calls:
                plain_reply = (response.content or "").strip()
                if plain_reply:
                    run.assistant_reply = plain_reply
                    run.status = "completed"
                else:
                    if not empty_response_retried:
                        empty_response_retried = True
                        conversation.append({"role": "user", "content": (
                            "Your previous reply was empty. Return either a short final answer "
                            "or continue with needed tools, but do not return empty content."
                        )})
                        if rt.context_budget_v2:
                            budget = plan_budget(messages=conversation, limits=model_limits)
                            if budget.compacted:
                                conversation, _ = _reduce_conversation_for_budget(
                                    conversation, input_budget_tokens=budget.input_budget)
                                budget = plan_budget(messages=conversation, limits=model_limits)
                        continue
                    run.status = "failed"
                    run.error = "Model returned an empty response without tool calls. Try again."
                break

            conversation.append(_assistant_message_from(response))

            tool_result_dicts: list[dict[str, Any]] = []
            stop_due_to_repeated_empty_gmail_search = False

            for call in response.tool_calls:
                tool_name = call.name or ""
                args = call.arguments if isinstance(call.arguments, dict) else {}
                tool_span = new_span_id()

                await emit_trace_event(db, run_id=run.id, event_type=EV_TOOL_STARTED,
                    trace_id=root_trace, span_id=tool_span, parent_span_id=llm_span,
                    step_index=step_idx + 1, payload={"tool_name": tool_name})

                if tool_name == FINAL_ANSWER_TOOL_NAME:
                    text = str(args.get("text") or "").strip()
                    citations = args.get("citations") or []
                    if not text:
                        result = {"error": "final_answer requires a non-empty 'text' field"}
                        prop = None
                    else:
                        if isinstance(citations, list) and citations:
                            cite_txt = ", ".join(str(c) for c in citations)
                            final_answer_text = f"{text}\n\n— {cite_txt}"
                        else:
                            final_answer_text = text
                        result = {"ok": True}
                        prop = None
                else:
                    result, prop = await _dispatch_tool(db, user, run.id, thread_id, call)
                    if prop is not None:
                        proposals_created.append(prop)

                step_idx += 1
                db.add(AgentRunStep(
                    run_id=run.id, step_index=step_idx, kind="tool", name=tool_name,
                    payload={"args": args, "result": result},
                ))
                tool_result_dicts.append(result if isinstance(result, dict) else {"result": result})

                # Empty Gmail search detection
                if tool_name == "gmail_list_messages" and isinstance(result, dict):
                    result_size = result.get("resultSizeEstimate")
                    msgs = result.get("messages")
                    empty_result = False
                    if isinstance(result_size, int):
                        empty_result = result_size == 0
                    elif isinstance(msgs, list):
                        empty_result = len(msgs) == 0
                    if empty_result:
                        empty_gmail_search_streak += 1
                        q = str(args.get("q") or "").strip()
                        if q and q not in empty_gmail_queries:
                            empty_gmail_queries.append(q)
                    else:
                        empty_gmail_search_streak = 0
                        empty_gmail_queries.clear()
                    if empty_gmail_search_streak >= 4 and final_answer_text is None:
                        tried = ", ".join(f"'{q}'" for q in empty_gmail_queries[:4]) or "several queries"
                        run.assistant_reply = (
                            "No encuentro correos coincidentes en Gmail tras varias busquedas "
                            f"({tried}). Para continuar sin fallar: dime 1-2 remitentes, un rango "
                            "de fechas, o un fragmento exacto del asunto/cuerpo y lo intento de nuevo."
                        )
                        run.status = "completed"
                        stop_due_to_repeated_empty_gmail_search = True
                elif tool_name != FINAL_ANSWER_TOOL_NAME:
                    empty_gmail_search_streak = 0
                    empty_gmail_queries.clear()

                # Native harness: append tool result
                tool_payload = json.dumps(result, ensure_ascii=False, default=str)
                conversation.append({
                    "role": "tool", "tool_call_id": call.id, "name": tool_name,
                    "content": clamp_tool_content_by_tokens(tool_payload, 3000),
                })

                await emit_trace_event(db, run_id=run.id, event_type=EV_TOOL_FINISHED,
                    trace_id=root_trace, span_id=tool_span, parent_span_id=llm_span,
                    step_index=step_idx, payload={
                        "tool_name": tool_name,
                        "result_sha256": content_sha256_preview(
                            json.dumps(result, ensure_ascii=False, default=str)[:8000]),
                        "proposal": bool(prop),
                    })

                if stop_due_to_repeated_empty_gmail_search:
                    break

            if stop_due_to_repeated_empty_gmail_search:
                break

            if rt.context_budget_v2:
                budget = plan_budget(messages=conversation, limits=model_limits)
                if budget.compacted:
                    conversation, _ = _reduce_conversation_for_budget(
                        conversation, input_budget_tokens=budget.input_budget)
                    budget = plan_budget(messages=conversation, limits=model_limits)

            if final_answer_text is not None:
                run.assistant_reply = final_answer_text
                run.status = "completed"
                break
        else:
            # Budget exhausted without explicit final_answer — produce best-effort reply
            # from the last LLM content or accumulated tool results.
            last_content = ""
            for step in reversed(conversation):
                if step.get("role") == "assistant" and step.get("content"):
                    last_content = step["content"].strip()
                    break
            if last_content:
                run.assistant_reply = last_content
                run.status = "completed"
            else:
                run.assistant_reply = (
                    "I've reached the end of my current turn budget without reaching a "
                    "definitive answer. Here's what I gathered so far — let me know if "
                    "you'd like me to continue exploring a specific angle."
                )
                run.status = "completed"

    except LLMProviderError as exc:
        step_idx += 1
        db.add(AgentRunStep(run_id=run.id, step_index=step_idx, kind="provider_error",
                            name=exc.provider, payload=exc.to_dict()))
        run.status = "failed"
        run.error = f"{exc.message} {exc.hint}".strip()[:2000]
    except KeyDecryptError as exc:
        step_idx += 1
        db.add(AgentRunStep(run_id=run.id, step_index=step_idx, kind="key_decrypt_error",
                            name=exc.scope, payload={
                                "kind": "key_decrypt_error", "scope": exc.scope,
                                "reason": exc.reason, "settings_url": "/settings#ai",
                            }))
        run.status = "failed"
        run.error = ("An API key for the active provider exists but cannot be decrypted. "
                     "Re-enter it in Settings → AI to recover.")
    except NoActiveProviderError as exc:
        run.status = "failed"
        run.error = str(exc) or "No AI provider is selected as active."
        run.assistant_reply = run.error
    except Exception as exc:
        run.status = "failed"
        run.error = str(exc)[:2000]

    finally:
        if _replay_token is not None:
            _replay_ctx.reset(_replay_token)

        if run.root_trace_id:
            if run.status == "completed":
                await emit_trace_event(db, run_id=run.id, event_type=EV_RUN_COMPLETED,
                    trace_id=run.root_trace_id, span_id=root_span,
                    payload={"assistant_reply_sha256": content_sha256_preview(run.assistant_reply or "")})
            elif run.status == "failed":
                await emit_trace_event(db, run_id=run.id, event_type=EV_RUN_FAILED,
                    trace_id=run.root_trace_id, span_id=root_span,
                    payload={"error": (run.error or "")[:500]})

        run.updated_at = datetime.now(UTC)
        await db.commit()
        await db.refresh(run)
        for p in proposals_created:
            await db.refresh(p)
        prop_reads = [proposal_to_read(p) for p in proposals_created]
        steps = await _load_steps(db, run.id)
        return _to_read(run, steps, prop_reads)


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------

async def _load_steps(db: AsyncSession, run_id: int) -> list[AgentStepRead]:
    result = await db.execute(
        select(AgentRunStep).where(AgentRunStep.run_id == run_id)
        .order_by(AgentRunStep.step_index)
    )
    rows = result.scalars().all()
    return [
        AgentStepRead(step_index=s.step_index, kind=s.kind, name=s.name, payload=s.payload)
        for s in rows
    ]


def _to_read(
    run: AgentRun, steps: list[AgentStepRead], proposals: list[PendingProposalRead],
    *, attention: AgentRunAttentionRead | None = None,
) -> AgentRunRead:
    return AgentRunRead(
        id=run.id, status=run.status, user_message=run.user_message,
        assistant_reply=run.assistant_reply, error=run.error,
        root_trace_id=run.root_trace_id, chat_thread_id=run.chat_thread_id,
        turn_profile=getattr(run, "turn_profile", None) or TURN_PROFILE_USER_CHAT,
        attention=attention, steps=steps, pending_proposals=proposals,
    )


async def list_recent_runs(db: AsyncSession, user: User, *, limit: int = 30) -> list[AgentRunSummaryRead]:
    lim = max(1, min(100, int(limit)))
    result = await db.execute(
        select(AgentRun).where(AgentRun.user_id == user.id)
        .order_by(AgentRun.id.desc()).limit(lim)
    )
    rows = result.scalars().all()
    out: list[AgentRunSummaryRead] = []
    for r in rows:
        um = r.user_message or ""
        preview = um[:240] + ("…" if len(um) > 240 else "")
        out.append(AgentRunSummaryRead(
            id=r.id, status=r.status, user_message_preview=preview,
            created_at=r.created_at, root_trace_id=r.root_trace_id,
            chat_thread_id=r.chat_thread_id,
        ))
    return out


async def list_trace_events(
    db: AsyncSession, user: User, run_id: int,
) -> list[AgentTraceEventRead] | None:
    run = await db.get(AgentRun, run_id)
    if not run or run.user_id != user.id:
        return None
    result = await db.execute(
        select(AgentTraceEvent).where(AgentTraceEvent.run_id == run_id)
        .order_by(AgentTraceEvent.id)
    )
    rows = result.scalars().all()
    return [
        AgentTraceEventRead(
            id=r.id, schema_version=r.schema_version, event_type=r.event_type,
            trace_id=r.trace_id, span_id=r.span_id, parent_span_id=r.parent_span_id,
            step_index=r.step_index,
            payload=_trim_step_payload_for_client(r.payload) if isinstance(r.payload, dict) else r.payload,
            created_at=r.created_at,
        )
        for r in rows
    ]


async def get_run(db: AsyncSession, user: User, run_id: int) -> AgentRunRead | None:
    run = await db.get(AgentRun, run_id)
    if not run or run.user_id != user.id:
        return None
    steps_raw = await _load_steps(db, run.id)
    steps = [
        AgentStepRead(
            step_index=s.step_index, kind=s.kind, name=s.name,
            payload=_trim_step_payload_for_client(s.payload),
        )
        for s in steps_raw
    ]
    pr = await db.execute(
        select(PendingProposal).where(
            PendingProposal.run_id == run_id, PendingProposal.user_id == user.id)
    )
    props = [proposal_to_read(p) for p in pr.scalars().all()]
    attention = None
    if run.status in {"pending", "running", "needs_attention"}:
        snap = await build_attention_snapshot(db, run)
        attention = AgentRunAttentionRead(
            stage=snap.stage, last_event_at=snap.last_event_at, hint=snap.hint,
        )
    return _to_read(run, steps, props, attention=attention)
