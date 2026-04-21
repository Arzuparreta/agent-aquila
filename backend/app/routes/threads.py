"""Chat threads + messages — the artist-first home of the new app.

Endpoints:
- ``GET    /threads`` — list threads (excludes archived by default).
- ``POST   /threads`` — create a manual thread (or upsert an entity-bound one).
- ``GET    /threads/{id}`` — read a single thread.
- ``PATCH  /threads/{id}`` — pin/archive/title.
- ``DELETE /threads/{id}`` — hard-delete the thread (cascades to chat_messages).
- ``DELETE /threads/archived`` — hard-delete every archived thread for the user.
- ``GET    /threads/{id}/messages`` — paginated message history.
- ``POST   /threads/{id}/messages`` — append a user message and run the agent in this
  thread context. Persists both messages, returns the assistant reply with any inline
  cards (approval / setup) attached as ``attachments``.
- ``POST   /threads/{id}/messages/{message_id}/retry`` — delete a failed assistant/system
  reply (provider/decrypt error or plain system failure) and re-run the agent from the
  preceding user turn without duplicating the user bubble.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.agent import AgentRunRead
from app.schemas.chat import (
    ArchivedThreadsDeleteResult,
    MessageCreate,
    MessageRead,
    MessageSendResult,
    ThreadCreate,
    ThreadPatch,
    ThreadRead,
)
from app.services.agent_attachments import attachments_from_agent_run_read
from app.services.agent_memory_post_turn_service import maybe_ingest_post_turn_memory
from app.services.agent_runtime_config_service import resolve_for_user
from app.services.agent_rate_limit_service import AgentRateLimitService
from app.services.agent_service import AgentService
from app.services.chat_service import (
    append_message,
    delete_all_archived_threads,
    apply_agent_run_to_placeholder,
    attachments_as_entity_refs,
    first_assistant_message_after_id,
    get_message_by_client_token,
    get_message_by_agent_run,
    get_or_create_entity_thread,
    get_thread,
    get_thread_message,
    history_for_agent,
    preview_memory_flush_dropped,
    latest_prior_user_message,
    list_messages,
    list_threads,
    message_is_retriable_failed_turn,
    thread_latest_message_id,
    message_to_read,
    render_user_message,
    thread_to_read,
)
from app.services.job_queue import enqueue
from app.models.agent_run import AgentRun

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/threads", tags=["threads"], dependencies=[Depends(get_current_user)])

_AGENT_REPLY_PLACEHOLDER = "\u2026"


async def _post_turn_memory_if_completed(
    db: AsyncSession,
    user: User,
    *,
    rendered_user_message: str,
    assistant_text: str,
    run_status: str,
    agent_run_id: int | None = None,
) -> None:
    """Persist durable facts from the last exchange after a successful agent run."""
    if run_status != "completed":
        return
    await maybe_ingest_post_turn_memory(
        db,
        user,
        user_message=rendered_user_message,
        assistant_message=assistant_text or "",
        run_id=agent_run_id,
    )


async def _enqueue_chat_agent_turn(
    *,
    run_id: int,
    user_id: int,
    prior: list[dict[str, str]] | None,
    hint: str | None,
) -> dict[str, Any]:
    """Try twice with a short pause — transient Redis/ARQ hiccups should not force a sync HTTP agent run."""
    last: dict[str, Any] = {"queued": False}
    for attempt in range(2):
        try:
            last = await enqueue(
                "run_chat_agent_turn",
                run_id,
                user_id,
                prior,
                hint,
                _job_id=f"agent_run:{run_id}",
            )
            if last.get("queued"):
                return last
        except Exception:
            logger.exception(
                "failed to enqueue run_chat_agent_turn run_id=%s attempt=%s",
                run_id,
                attempt + 1,
            )
            last = {"queued": False}
        if attempt == 0:
            await asyncio.sleep(0.15)
    return last


def _normalize_idempotency_key(raw: str | None) -> str | None:
    key = (raw or "").strip()
    if not key:
        return None
    return key[:128]


async def _result_from_idempotent_send(
    db: AsyncSession,
    thread,
    user_msg,
) -> MessageSendResult | None:
    asst_msg = await first_assistant_message_after_id(db, thread, user_msg.id)
    if not asst_msg:
        return None
    pending = False
    if asst_msg.agent_run_id is not None:
        run = await db.get(AgentRun, asst_msg.agent_run_id)
        pending = bool(run and run.status in ("pending", "running"))
    return MessageSendResult(
        thread=thread_to_read(thread),
        user_message=message_to_read(user_msg),
        assistant_message=message_to_read(asst_msg),
        error=None,
        agent_run_pending=pending,
    )


async def _result_from_idempotent_retry(
    db: AsyncSession,
    thread,
    assistant_msg,
) -> MessageSendResult | None:
    user_msg = await latest_prior_user_message(db, thread, assistant_msg.id)
    if not user_msg:
        return None
    pending = False
    if assistant_msg.agent_run_id is not None:
        run = await db.get(AgentRun, assistant_msg.agent_run_id)
        pending = bool(run and run.status in ("pending", "running"))
    return MessageSendResult(
        thread=thread_to_read(thread),
        user_message=message_to_read(user_msg),
        assistant_message=message_to_read(assistant_msg),
        error=None,
        agent_run_pending=pending,
    )


def _message_send_result(
    thread,
    user_msg,
    asst_msg,
    run,
    *,
    agent_run_pending: bool = False,
) -> MessageSendResult:
    cards = attachments_from_agent_run_read(run)
    has_error_card = any(
        isinstance(c, dict) and c.get("card_kind") in ("provider_error", "key_decrypt_error")
        for c in cards
    )
    return MessageSendResult(
        thread=thread_to_read(thread),
        user_message=message_to_read(user_msg),
        assistant_message=message_to_read(asst_msg),
        error=run.error if (run.status != "completed" and not has_error_card) else None,
        agent_run_pending=agent_run_pending,
    )


async def _build_thread_context_hint(db: AsyncSession, thread) -> str | None:
    """Build the system-prompt suffix for entity-bound threads.

    After the OpenClaw refactor the only first-class entities are the
    free-form ``general`` threads opened from the inbox / chat composer.
    External resources (Gmail messages, Calendar events, Drive files) are
    referenced by their *provider* IDs via message attachments rather
    than mirrored into our DB, so there is no entity row to enrich.
    """
    del db  # entity hints removed alongside CRM/mirror tables
    if thread.kind != "entity" or not thread.entity_type:
        return None
    return (
        f"Conversación dedicada al {thread.entity_type} #{thread.entity_id} ({thread.title})."
    )


@router.get("", response_model=list[ThreadRead])
async def get_threads(
    include_archived: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ThreadRead]:
    rows = await list_threads(db, current_user, include_archived=include_archived)
    return [thread_to_read(r) for r in rows]


@router.post("", response_model=ThreadRead, status_code=status.HTTP_201_CREATED)
async def create_thread(
    payload: ThreadCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ThreadRead:
    if payload.entity_type and payload.entity_id:
        row = await get_or_create_entity_thread(
            db,
            current_user,
            entity_type=payload.entity_type,
            entity_id=payload.entity_id,
            title=payload.title,
        )
    else:
        # Free-form manual thread (kind=general) with custom title.
        from app.models.chat_thread import ChatThread

        row = ChatThread(
            user_id=current_user.id,
            kind="general",
            title=(payload.title or "New chat")[:255],
        )
        db.add(row)
        await db.flush()
    await db.commit()
    await db.refresh(row)
    return thread_to_read(row)


@router.delete("/archived", response_model=ArchivedThreadsDeleteResult)
async def delete_archived_threads(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ArchivedThreadsDeleteResult:
    """Hard-delete all archived threads for the current user (cascades to messages)."""
    n = await delete_all_archived_threads(db, current_user)
    await db.commit()
    return ArchivedThreadsDeleteResult(deleted=n)


@router.get("/{thread_id}", response_model=ThreadRead)
async def read_thread(
    thread_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ThreadRead:
    row = await get_thread(db, current_user, thread_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found")
    return thread_to_read(row)


@router.patch("/{thread_id}", response_model=ThreadRead)
async def patch_thread(
    thread_id: int,
    patch: ThreadPatch,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ThreadRead:
    row = await get_thread(db, current_user, thread_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found")
    if patch.title is not None:
        row.title = patch.title.strip()[:255] or row.title
    if patch.pinned is not None:
        row.pinned = bool(patch.pinned)
    if patch.archived is not None:
        row.archived = bool(patch.archived)
    await db.commit()
    await db.refresh(row)
    return thread_to_read(row)


@router.delete("/{thread_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_thread(
    thread_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Hard-delete a chat thread owned by the calling user.

    DB-level ``ON DELETE CASCADE`` on ``chat_messages.thread_id`` removes
    the message history automatically.
    """
    row = await get_thread(db, current_user, thread_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found")
    await db.delete(row)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{thread_id}/messages", response_model=list[MessageRead])
async def read_messages(
    thread_id: int,
    limit: int = Query(default=200, ge=1, le=500),
    before_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[MessageRead]:
    thread = await get_thread(db, current_user, thread_id)
    if not thread:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found")
    rows = await list_messages(db, thread, limit=limit, before_id=before_id)
    return [message_to_read(m) for m in rows]


@router.post("/{thread_id}/messages", response_model=MessageSendResult)
async def send_message(
    thread_id: int,
    payload: MessageCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MessageSendResult:
    thread = await get_thread(db, current_user, thread_id)
    if not thread:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found")
    agent_rt = await resolve_for_user(db, current_user)
    AgentRateLimitService.check(current_user.id, max_runs_per_hour=agent_rt.agent_max_runs_per_hour)
    idem_key = _normalize_idempotency_key(payload.idempotency_key)
    if idem_key:
        existing = await get_message_by_client_token(db, thread, idem_key)
        if existing and existing.role == "user":
            replay = await _result_from_idempotent_send(db, thread, existing)
            if replay is not None:
                return replay

    user_attachments = (
        [r.model_dump() for r in payload.references] if payload.references else None
    )
    user_msg = await append_message(
        db,
        thread,
        role="user",
        content=payload.content,
        attachments=user_attachments,
        client_token=idem_key,
    )
    await db.commit()
    await db.refresh(user_msg)
    await db.refresh(thread)

    dropped = await preview_memory_flush_dropped(db, thread, runtime=agent_rt)
    if dropped:
        await AgentService.run_memory_flush_turn(
            db, current_user, thread_id=thread.id, dropped_messages=dropped
        )
    prior = await history_for_agent(db, thread, runtime=agent_rt)
    # Drop the most recent user message we just persisted (it's already last in `prior`),
    # since the agent expects it as the live `message` arg.
    if prior and prior[-1].get("role") == "user" and prior[-1].get("content") == payload.content:
        prior = prior[:-1]

    rendered = render_user_message(payload.content, payload.references)
    hint = await _build_thread_context_hint(db, thread)

    early = await AgentService.run_agent_invalid_preflight(
        db, current_user, rendered, thread_id=thread.id
    )
    if early is not None:
        cards = attachments_from_agent_run_read(early)
        has_error_card = any(
            isinstance(c, dict) and c.get("card_kind") in ("provider_error", "key_decrypt_error")
            for c in cards
        )
        if early.assistant_reply:
            assistant_text = early.assistant_reply
        elif has_error_card:
            assistant_text = ""
        else:
            assistant_text = early.error or ""
        asst_msg = await append_message(
            db,
            thread,
            role="assistant" if early.status == "completed" else "system",
            content=assistant_text,
            attachments=cards or None,
            agent_run_id=early.id,
        )
        await db.commit()
        await db.refresh(asst_msg)
        await db.refresh(thread)
        await _post_turn_memory_if_completed(
            db,
            current_user,
            rendered_user_message=rendered,
            assistant_text=assistant_text,
            run_status=early.status,
            agent_run_id=early.id,
        )
        return _message_send_result(thread, user_msg, asst_msg, early)

    use_async = agent_rt.agent_async_runs and bool(settings.redis_url)
    if use_async:
        run_row = await AgentService.create_pending_agent_run(
            db, current_user, rendered, thread_id=thread.id
        )
        run_id_snap = int(run_row.id)
        root_trace_snap = run_row.root_trace_id
        asst_msg = await append_message(
            db,
            thread,
            role="assistant",
            content=_AGENT_REPLY_PLACEHOLDER,
            agent_run_id=run_id_snap,
        )
        await db.commit()
        await db.refresh(asst_msg)
        await db.refresh(thread)
        enq = await _enqueue_chat_agent_turn(
            run_id=run_id_snap,
            user_id=current_user.id,
            prior=prior,
            hint=hint,
        )
        if not enq.get("queued"):
            logger.warning(
                "ARQ enqueue did not queue run_id=%s; running agent inline (may exceed Next.js proxy time). "
                "Check Redis, worker, and AGENT_ASYNC_RUNS.",
                run_id_snap,
            )
        if enq.get("queued"):
            pending_read = AgentRunRead(
                id=run_id_snap,
                status="pending",
                user_message=rendered,
                assistant_reply=None,
                error=None,
                root_trace_id=root_trace_snap,
                chat_thread_id=thread.id,
                steps=[],
                pending_proposals=[],
            )
            return _message_send_result(
                thread, user_msg, asst_msg, pending_read, agent_run_pending=True
            )
        await db.refresh(run_row)
        run_row.status = "running"
        await db.commit()
        read = await AgentService._execute_agent_loop(
            db,
            current_user,
            run_row,
            prior_messages=prior,
            thread_context_hint=hint,
            replay=None,
        )
        await apply_agent_run_to_placeholder(
            db, thread, agent_run_id=run_id_snap, run_read=read
        )
        await db.commit()
        await _post_turn_memory_if_completed(
            db,
            current_user,
            rendered_user_message=rendered,
            assistant_text=read.assistant_reply or "",
            run_status=read.status,
            agent_run_id=run_id_snap,
        )
        asst_final = await get_message_by_agent_run(db, thread, run_id_snap)
        assert asst_final is not None
        await db.refresh(thread)
        return _message_send_result(thread, user_msg, asst_final, read)

    run = await AgentService.run_agent(
        db,
        current_user,
        rendered,
        prior_messages=prior,
        thread_id=thread.id,
        thread_context_hint=hint,
    )
    cards = attachments_from_agent_run_read(run)
    has_error_card = any(
        isinstance(c, dict) and c.get("card_kind") in ("provider_error", "key_decrypt_error")
        for c in cards
    )
    if run.assistant_reply:
        assistant_text = run.assistant_reply
    elif has_error_card:
        assistant_text = ""
    else:
        assistant_text = run.error or ""
    asst_msg = await append_message(
        db,
        thread,
        role="assistant" if run.status == "completed" else "system",
        content=assistant_text,
        attachments=cards or None,
        agent_run_id=run.id,
    )
    await db.commit()
    await db.refresh(asst_msg)
    await db.refresh(thread)
    await _post_turn_memory_if_completed(
        db,
        current_user,
        rendered_user_message=rendered,
        assistant_text=assistant_text,
        run_status=run.status,
        agent_run_id=run.id,
    )
    return _message_send_result(thread, user_msg, asst_msg, run)


@router.post("/{thread_id}/messages/{message_id}/retry", response_model=MessageSendResult)
async def retry_failed_message(
    thread_id: int,
    message_id: int,
    x_idempotency_key: str | None = Header(default=None, alias="X-Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MessageSendResult:
    """Re-run the agent for the user turn that produced this failed reply.

    Deletes the failed assistant/system row (provider error, decrypt error, or plain
    system failure), then appends a fresh assistant message — no duplicate user bubble.
    """
    thread = await get_thread(db, current_user, thread_id)
    if not thread:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found")
    idem_key = _normalize_idempotency_key(x_idempotency_key)
    if idem_key:
        existing = await get_message_by_client_token(db, thread, idem_key)
        if existing and existing.role in ("assistant", "system"):
            replay = await _result_from_idempotent_retry(db, thread, existing)
            if replay is not None:
                return replay

    failed = await get_thread_message(db, thread, message_id)
    if not failed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")
    if not message_is_retriable_failed_turn(failed):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This message cannot be retried",
        )

    latest_id = await thread_latest_message_id(db, thread)
    if latest_id is not None and latest_id != failed.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only the latest message in the thread can be retried",
        )

    user_msg = await latest_prior_user_message(db, thread, failed.id)
    if not user_msg:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No user message found to retry from",
        )

    await db.delete(failed)
    await db.commit()

    refs = attachments_as_entity_refs(user_msg.attachments)
    rendered = render_user_message(user_msg.content, refs)
    agent_rt = await resolve_for_user(db, current_user)
    AgentRateLimitService.check(current_user.id, max_runs_per_hour=agent_rt.agent_max_runs_per_hour)
    dropped = await preview_memory_flush_dropped(db, thread, runtime=agent_rt)
    if dropped:
        await AgentService.run_memory_flush_turn(
            db, current_user, thread_id=thread.id, dropped_messages=dropped
        )
    prior = await history_for_agent(db, thread, runtime=agent_rt)
    if prior and prior[-1].get("role") == "user" and prior[-1].get("content") == user_msg.content:
        prior = prior[:-1]

    hint = await _build_thread_context_hint(db, thread)

    early = await AgentService.run_agent_invalid_preflight(
        db, current_user, rendered, thread_id=thread.id
    )
    if early is not None:
        cards = attachments_from_agent_run_read(early)
        has_error_card = any(
            isinstance(c, dict) and c.get("card_kind") in ("provider_error", "key_decrypt_error")
            for c in cards
        )
        if early.assistant_reply:
            assistant_text = early.assistant_reply
        elif has_error_card:
            assistant_text = ""
        else:
            assistant_text = early.error or ""
        asst_msg = await append_message(
            db,
            thread,
            role="assistant" if early.status == "completed" else "system",
            content=assistant_text,
            attachments=cards or None,
            agent_run_id=early.id,
            client_token=idem_key,
        )
        await db.commit()
        await db.refresh(asst_msg)
        await db.refresh(thread)
        await _post_turn_memory_if_completed(
            db,
            current_user,
            rendered_user_message=rendered,
            assistant_text=assistant_text,
            run_status=early.status,
            agent_run_id=early.id,
        )
        return _message_send_result(thread, user_msg, asst_msg, early)

    use_async = agent_rt.agent_async_runs and bool(settings.redis_url)
    if use_async:
        run_row = await AgentService.create_pending_agent_run(
            db, current_user, rendered, thread_id=thread.id
        )
        run_id_snap = int(run_row.id)
        root_trace_snap = run_row.root_trace_id
        asst_msg = await append_message(
            db,
            thread,
            role="assistant",
            content=_AGENT_REPLY_PLACEHOLDER,
            agent_run_id=run_id_snap,
            client_token=idem_key,
        )
        await db.commit()
        await db.refresh(asst_msg)
        await db.refresh(thread)
        enq = await _enqueue_chat_agent_turn(
            run_id=run_id_snap,
            user_id=current_user.id,
            prior=prior,
            hint=hint,
        )
        if not enq.get("queued"):
            logger.warning(
                "ARQ enqueue did not queue run_id=%s; running agent inline (may exceed Next.js proxy time). "
                "Check Redis, worker, and AGENT_ASYNC_RUNS.",
                run_id_snap,
            )
        if enq.get("queued"):
            pending_read = AgentRunRead(
                id=run_id_snap,
                status="pending",
                user_message=rendered,
                assistant_reply=None,
                error=None,
                root_trace_id=root_trace_snap,
                chat_thread_id=thread.id,
                steps=[],
                pending_proposals=[],
            )
            return _message_send_result(
                thread, user_msg, asst_msg, pending_read, agent_run_pending=True
            )
        await db.refresh(run_row)
        run_row.status = "running"
        await db.commit()
        read = await AgentService._execute_agent_loop(
            db,
            current_user,
            run_row,
            prior_messages=prior,
            thread_context_hint=hint,
            replay=None,
        )
        await apply_agent_run_to_placeholder(
            db, thread, agent_run_id=run_id_snap, run_read=read
        )
        await db.commit()
        await _post_turn_memory_if_completed(
            db,
            current_user,
            rendered_user_message=rendered,
            assistant_text=read.assistant_reply or "",
            run_status=read.status,
            agent_run_id=run_id_snap,
        )
        asst_final = await get_message_by_agent_run(db, thread, run_id_snap)
        assert asst_final is not None
        await db.refresh(thread)
        return _message_send_result(thread, user_msg, asst_final, read)

    run = await AgentService.run_agent(
        db,
        current_user,
        rendered,
        prior_messages=prior,
        thread_id=thread.id,
        thread_context_hint=hint,
    )
    cards = attachments_from_agent_run_read(run)
    has_error_card = any(
        isinstance(c, dict) and c.get("card_kind") in ("provider_error", "key_decrypt_error")
        for c in cards
    )
    if run.assistant_reply:
        assistant_text = run.assistant_reply
    elif has_error_card:
        assistant_text = ""
    else:
        assistant_text = run.error or ""
    asst_msg = await append_message(
        db,
        thread,
        role="assistant" if run.status == "completed" else "system",
        content=assistant_text,
        attachments=cards or None,
        agent_run_id=run.id,
        client_token=idem_key,
    )
    await db.commit()
    await db.refresh(asst_msg)
    await db.refresh(thread)
    await _post_turn_memory_if_completed(
        db,
        current_user,
        rendered_user_message=rendered,
        assistant_text=assistant_text,
        run_status=run.status,
        agent_run_id=run.id,
    )
    return _message_send_result(thread, user_msg, asst_msg, run)
