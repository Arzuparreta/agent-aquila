"""Chat thread + message persistence layer.

This module owns:
- Resolving / creating ``ChatThread`` rows (general or per-entity, deduped via the unique
  constraint ``(user_id, entity_type, entity_id)``).
- Persisting ``ChatMessage`` rows for both sides of a conversation.
- Building the prior-message context that the agent loop consumes when running with a
  ``thread_id`` (so multi-turn topical conversations actually feel continuous).

The agent loop itself lives in ``AgentService.run_agent``. This service stays thin and
side-effect-only over Postgres; LLM and tool execution belong to the agent.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Iterable

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat_message import ChatMessage
from app.models.chat_thread import ChatThread
from app.models.user import User
from app.schemas.agent import AgentRunRead
from app.schemas.chat import EntityRef, MessageRead, ThreadRead
from app.services.agent_attachments import attachments_from_agent_run_read

# Maximum prior chat turns we hand to the LLM as conversation context. Older messages
# are still persisted and visible to the artist, just not re-sent each turn.
HISTORY_TURNS_FOR_AGENT = 8


def _entity_label_default(entity_type: str | None, entity_id: int | None) -> str:
    if entity_type and entity_id:
        return f"{entity_type.capitalize()} #{entity_id}"
    return "General"


async def get_or_create_entity_thread(
    db: AsyncSession,
    user: User,
    *,
    entity_type: str,
    entity_id: int,
    title: str | None = None,
) -> ChatThread:
    """Idempotent: returns the existing thread for ``(user, entity_type, entity_id)`` or creates one."""
    stmt = select(ChatThread).where(
        ChatThread.user_id == user.id,
        ChatThread.entity_type == entity_type,
        ChatThread.entity_id == entity_id,
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row:
        return row
    row = ChatThread(
        user_id=user.id,
        kind="entity",
        entity_type=entity_type,
        entity_id=entity_id,
        title=title or _entity_label_default(entity_type, entity_id),
    )
    db.add(row)
    await db.flush()
    return row


async def start_entity_chat(
    db: AsyncSession,
    user: User,
    *,
    entity_type: str,
    entity_id: int,
    title: str,
    announcement: str,
    event_attachments: list[dict] | None = None,
) -> ChatThread:
    """Upsert an entity-bound thread and (idempotently) seed one ``event`` announcement.

    Returns the thread. Also unarchives the thread if it was archived, so reopening from
    the library / inbox brings it back into the conversation list. The caller is
    responsible for committing the session (mirrors the pattern used by
    ``start_chat_from_email`` — keeps the endpoint in control of its own transaction).
    """
    thread = await get_or_create_entity_thread(
        db, user, entity_type=entity_type, entity_id=entity_id, title=title
    )

    res = await db.execute(
        select(ChatMessage.id)
        .where(
            ChatMessage.thread_id == thread.id,
            ChatMessage.role == "event",
        )
        .limit(1)
    )
    already_seeded = res.scalar_one_or_none() is not None

    if not already_seeded:
        await append_message(
            db,
            thread,
            role="event",
            content=announcement,
            attachments=event_attachments,
        )

    if thread.archived:
        thread.archived = False
        thread.updated_at = datetime.now(UTC)

    return thread


async def list_threads(
    db: AsyncSession, user: User, *, include_archived: bool = False
) -> list[ChatThread]:
    stmt = select(ChatThread).where(ChatThread.user_id == user.id)
    if not include_archived:
        stmt = stmt.where(ChatThread.archived.is_(False))
    stmt = stmt.order_by(
        desc(ChatThread.pinned),
        desc(ChatThread.last_message_at),
        desc(ChatThread.created_at),
    )
    return list((await db.execute(stmt)).scalars().all())


async def get_thread(db: AsyncSession, user: User, thread_id: int) -> ChatThread | None:
    row = await db.get(ChatThread, thread_id)
    if not row or row.user_id != user.id:
        return None
    return row


async def list_messages(
    db: AsyncSession, thread: ChatThread, *, limit: int = 200, before_id: int | None = None
) -> list[ChatMessage]:
    stmt = select(ChatMessage).where(ChatMessage.thread_id == thread.id)
    if before_id is not None:
        stmt = stmt.where(ChatMessage.id < before_id)
    stmt = stmt.order_by(ChatMessage.id.desc()).limit(limit)
    rows = list((await db.execute(stmt)).scalars().all())
    return list(reversed(rows))


async def append_message(
    db: AsyncSession,
    thread: ChatThread,
    *,
    role: str,
    content: str,
    attachments: list[dict] | None = None,
    agent_run_id: int | None = None,
    flush: bool = True,
) -> ChatMessage:
    msg = ChatMessage(
        thread_id=thread.id,
        role=role,
        content=content,
        attachments=attachments,
        agent_run_id=agent_run_id,
    )
    db.add(msg)
    thread.last_message_at = datetime.now(UTC)
    if flush:
        await db.flush()
    return msg


async def history_for_agent(
    db: AsyncSession, thread: ChatThread, *, limit: int = HISTORY_TURNS_FOR_AGENT
) -> list[dict[str, str]]:
    """Returns prior turns as the OpenAI-compatible ``[{role, content}, ...]`` list.

    Keeps the most recent ``limit`` user/assistant pairs and also surfaces ``event``
    rows as ``system`` messages so the seeded entity announcement (written by the
    various ``/start-chat`` endpoints via ``start_entity_chat``) actually reaches the
    model. ``system`` rows stored on the thread are still stripped — those are author-
    authored UI annotations, not model-facing context.
    """
    stmt = (
        select(ChatMessage)
        .where(
            ChatMessage.thread_id == thread.id,
            ChatMessage.role.in_(("user", "assistant", "event")),
        )
        .order_by(ChatMessage.id.desc())
        .limit(limit * 2)
    )
    rows = list((await db.execute(stmt)).scalars().all())
    rows.reverse()
    return [
        {"role": "system" if r.role == "event" else r.role, "content": r.content}
        for r in rows
    ]


def thread_to_read(thread: ChatThread, *, unread: int = 0) -> ThreadRead:
    return ThreadRead(
        id=thread.id,
        kind=thread.kind,  # type: ignore[arg-type]
        entity_type=thread.entity_type,  # type: ignore[arg-type]
        entity_id=thread.entity_id,
        title=thread.title,
        pinned=thread.pinned,
        archived=thread.archived,
        last_message_at=thread.last_message_at,
        created_at=thread.created_at,
        updated_at=thread.updated_at,
        unread=unread,
    )


def message_to_read(msg: ChatMessage) -> MessageRead:
    return MessageRead(
        id=msg.id,
        thread_id=msg.thread_id,
        role=msg.role,  # type: ignore[arg-type]
        content=msg.content,
        attachments=msg.attachments,
        agent_run_id=msg.agent_run_id,
        created_at=msg.created_at,
    )


def attachments_as_entity_refs(raw: list[dict[str, Any]] | None) -> list[EntityRef]:
    """Parse user @reference chips from ``attachments`` (assistant rows use ``card_kind`` cards)."""
    if not raw:
        return []
    out: list[EntityRef] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        if item.get("card_kind") is not None:
            continue
        t = item.get("type")
        eid = item.get("id")
        if t is None or eid is None:
            continue
        eid_norm: int | str
        if isinstance(eid, (int, str)):
            eid_norm = eid
        else:
            eid_norm = str(eid)
        lbl = item.get("label")
        label = None if lbl is None else str(lbl)
        out.append(EntityRef(type=str(t), id=eid_norm, label=label))
    return out


async def get_thread_message(
    db: AsyncSession, thread: ChatThread, message_id: int
) -> ChatMessage | None:
    stmt = select(ChatMessage).where(
        ChatMessage.id == message_id,
        ChatMessage.thread_id == thread.id,
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def latest_prior_user_message(
    db: AsyncSession, thread: ChatThread, before_message_id: int
) -> ChatMessage | None:
    stmt = (
        select(ChatMessage)
        .where(
            ChatMessage.thread_id == thread.id,
            ChatMessage.id < before_message_id,
            ChatMessage.role == "user",
        )
        .order_by(ChatMessage.id.desc())
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def thread_latest_message_id(db: AsyncSession, thread: ChatThread) -> int | None:
    stmt = (
        select(ChatMessage.id)
        .where(ChatMessage.thread_id == thread.id)
        .order_by(ChatMessage.id.desc())
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


def message_is_retriable_failed_turn(msg: ChatMessage) -> bool:
    """Whether the row is a failed agent reply the artist can re-run from the prior user turn."""
    if msg.role not in ("assistant", "system"):
        return False
    if msg.attachments:
        for c in msg.attachments:
            if isinstance(c, dict) and c.get("card_kind") in ("provider_error", "key_decrypt_error"):
                return True
        return False
    return msg.role == "system"


async def get_message_by_agent_run(
    db: AsyncSession, thread: ChatThread, agent_run_id: int
) -> ChatMessage | None:
    stmt = select(ChatMessage).where(
        ChatMessage.thread_id == thread.id,
        ChatMessage.agent_run_id == agent_run_id,
    ).limit(1)
    return (await db.execute(stmt)).scalar_one_or_none()


async def apply_agent_run_to_placeholder(
    db: AsyncSession,
    thread: ChatThread,
    *,
    agent_run_id: int,
    run_read: AgentRunRead,
) -> ChatMessage | None:
    """Fill the assistant row created for an async agent run (placeholder ``\u2026``)."""
    msg = await get_message_by_agent_run(db, thread, agent_run_id)
    if not msg:
        return None
    cards = attachments_from_agent_run_read(run_read)
    has_error_card = any(
        isinstance(c, dict) and c.get("card_kind") in ("provider_error", "key_decrypt_error")
        for c in cards
    )
    if run_read.assistant_reply:
        msg.content = run_read.assistant_reply
    elif has_error_card:
        msg.content = ""
    else:
        msg.content = run_read.error or ""
    msg.role = "assistant" if run_read.status == "completed" else "system"
    msg.attachments = cards or None
    thread.last_message_at = datetime.now(UTC)
    await db.flush()
    return msg


def render_user_message(content: str, references: Iterable[EntityRef]) -> str:
    """Inline @reference chips into the text we send to the LLM.

    Example: text="What's up with @Maria?", references=[contact:42 label="Maria"]
    becomes: "What's up with @Maria? (referenced: contact:42)" for the agent's context.
    """
    refs = list(references)
    if not refs:
        return content
    suffix = "\n\n[Referencias adjuntas: " + ", ".join(
        f"{r.type}:{r.id}" + (f" ({r.label})" if r.label else "") for r in refs
    ) + "]"
    return content + suffix
