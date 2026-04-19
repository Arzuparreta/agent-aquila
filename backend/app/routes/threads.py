"""Chat threads + messages — the artist-first home of the new app.

Endpoints:
- ``GET    /threads`` — list threads (excludes archived by default).
- ``POST   /threads`` — create a manual thread (or upsert an entity-bound one).
- ``GET    /threads/{id}`` — read a single thread.
- ``PATCH  /threads/{id}`` — pin/archive/title.
- ``DELETE /threads/{id}`` — hard-delete the thread (cascades to chat_messages).
- ``GET    /threads/{id}/messages`` — paginated message history.
- ``POST   /threads/{id}/messages`` — append a user message and run the agent in this
  thread context. Persists both messages, returns the assistant reply with any inline
  cards (approval / setup) attached as ``attachments``.
- ``POST   /threads/{id}/messages/{message_id}/retry`` — delete a failed assistant/system
  reply (provider/decrypt error or plain system failure) and re-run the agent from the
  preceding user turn without duplicating the user bubble.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.chat import (
    MessageCreate,
    MessageRead,
    MessageSendResult,
    ThreadCreate,
    ThreadPatch,
    ThreadRead,
)
from app.services.agent_rate_limit_service import AgentRateLimitService
from app.services.agent_service import AgentService
from app.services.capability_policy import risk_tier_for_kind
from app.services.chat_service import (
    append_message,
    attachments_as_entity_refs,
    get_or_create_entity_thread,
    get_or_create_general_thread,
    get_thread,
    get_thread_message,
    history_for_agent,
    latest_prior_user_message,
    list_messages,
    list_threads,
    message_is_retriable_failed_turn,
    thread_latest_message_id,
    message_to_read,
    render_user_message,
    thread_to_read,
)
from app.services.pending_execution_service import preview_for_proposal_kind

router = APIRouter(prefix="/threads", tags=["threads"], dependencies=[Depends(get_current_user)])


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


def _agent_run_to_attachments(run) -> list[dict[str, Any]]:
    """Translate pending proposals and tool steps into inline chat cards.

    Each card shape (frontend-aware):
      - {"card_kind": "approval", "proposal_id": int, "kind": str, "summary": str,
         "risk_tier": str, "preview": {...}}
    Connector setup / oauth_authorize cards are emitted directly by the agent tools as
    tool results; we surface those to the FE by inspecting agent steps. (The chat view
    can also poll thread refs if the agent did not embed a card.)
    """
    out: list[dict[str, Any]] = []
    for prop in run.pending_proposals or []:
        out.append(
            {
                "card_kind": "approval",
                "proposal_id": prop.id,
                "kind": prop.kind,
                "summary": prop.summary,
                "risk_tier": prop.risk_tier or risk_tier_for_kind(prop.kind),
                "preview": preview_for_proposal_kind(prop.kind, dict(prop.payload)),
            }
        )
    # Surface any tool results that look like setup cards (connector_setup / oauth_authorize).
    for step in run.steps or []:
        if not step.payload:
            continue
        # Provider-error / key-decrypt steps emitted by the agent loop become
        # inline chat cards so the UI can render the "Probar conexión" /
        # "Abrir ajustes" affordances instead of dumping raw httpx text.
        if step.kind == "provider_error" and isinstance(step.payload, dict):
            payload = dict(step.payload)
            payload.setdefault("card_kind", "provider_error")
            out.append(payload)
            continue
        if step.kind == "key_decrypt_error" and isinstance(step.payload, dict):
            payload = dict(step.payload)
            payload.setdefault("card_kind", "key_decrypt_error")
            out.append(payload)
            continue
        if step.kind != "tool":
            continue
        result = step.payload.get("result") if isinstance(step.payload, dict) else None
        if isinstance(result, dict) and result.get("card_kind") in {
            "connector_setup",
            "oauth_authorize",
        }:
            out.append(result)
    return out


@router.get("", response_model=list[ThreadRead])
async def get_threads(
    include_archived: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ThreadRead]:
    # Ensure the artist always has a "General" thread to land on.
    await get_or_create_general_thread(db, current_user)
    await db.commit()
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
            title=(payload.title or "Nueva conversación")[:255],
        )
        db.add(row)
        await db.flush()
    await db.commit()
    await db.refresh(row)
    return thread_to_read(row)


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
    AgentRateLimitService.check(current_user.id)

    user_attachments = (
        [r.model_dump() for r in payload.references] if payload.references else None
    )
    user_msg = await append_message(
        db,
        thread,
        role="user",
        content=payload.content,
        attachments=user_attachments,
    )
    await db.commit()
    await db.refresh(user_msg)
    await db.refresh(thread)

    prior = await history_for_agent(db, thread)
    # Drop the most recent user message we just persisted (it's already last in `prior`),
    # since the agent expects it as the live `message` arg.
    if prior and prior[-1].get("role") == "user" and prior[-1].get("content") == payload.content:
        prior = prior[:-1]

    rendered = render_user_message(payload.content, payload.references)

    run = await AgentService.run_agent(
        db,
        current_user,
        rendered,
        prior_messages=prior,
        thread_id=thread.id,
        thread_context_hint=await _build_thread_context_hint(db, thread),
    )

    cards = _agent_run_to_attachments(run)
    # When the agent loop already produced a structured error card
    # (provider_error / key_decrypt_error), don't *also* dump `run.error` text
    # into the message bubble or the top-of-thread banner — the card already
    # shows message + actionable hint + a CTA, and duplicating it just clutters
    # the conversation. Any partial assistant_reply produced before the failure
    # is still rendered (preserving useful context).
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

    return MessageSendResult(
        thread=thread_to_read(thread),
        user_message=message_to_read(user_msg),
        assistant_message=message_to_read(asst_msg),
        error=run.error if (run.status != "completed" and not has_error_card) else None,
    )


@router.post("/{thread_id}/messages/{message_id}/retry", response_model=MessageSendResult)
async def retry_failed_message(
    thread_id: int,
    message_id: int,
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

    AgentRateLimitService.check(current_user.id)

    await db.delete(failed)
    await db.commit()

    refs = attachments_as_entity_refs(user_msg.attachments)
    rendered = render_user_message(user_msg.content, refs)
    prior = await history_for_agent(db, thread)
    if prior and prior[-1].get("role") == "user" and prior[-1].get("content") == user_msg.content:
        prior = prior[:-1]

    run = await AgentService.run_agent(
        db,
        current_user,
        rendered,
        prior_messages=prior,
        thread_id=thread.id,
        thread_context_hint=await _build_thread_context_hint(db, thread),
    )

    cards = _agent_run_to_attachments(run)
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

    return MessageSendResult(
        thread=thread_to_read(thread),
        user_message=message_to_read(user_msg),
        assistant_message=message_to_read(asst_msg),
        error=run.error if (run.status != "completed" and not has_error_card) else None,
    )
