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
from typing import Iterable

from sqlalchemy import desc, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat_message import ChatMessage
from app.models.chat_thread import ChatThread
from app.models.user import User
from app.schemas.chat import EntityRef, MessageRead, ThreadRead

# Maximum prior chat turns we hand to the LLM as conversation context. Older messages
# are still persisted and visible to the artist, just not re-sent each turn.
HISTORY_TURNS_FOR_AGENT = 8


def _entity_label_default(entity_type: str | None, entity_id: int | None) -> str:
    if entity_type and entity_id:
        return f"{entity_type.capitalize()} #{entity_id}"
    return "General"


async def get_or_create_general_thread(db: AsyncSession, user: User) -> ChatThread:
    """Return the user's *default* general thread, creating it on first call.

    Identified by ``is_default = TRUE`` (not by the broader
    ``kind='general' AND entity IS NULL`` predicate, which also matches
    free-form "Nueva conversación" threads). Uses Postgres
    ``INSERT ... ON CONFLICT DO NOTHING`` against the partial unique index
    ``uq_chat_threads_user_default`` so two concurrent requests can race
    safely — the loser falls through to the SELECT and returns the winner's
    row.
    """
    select_default = select(ChatThread).where(
        ChatThread.user_id == user.id,
        ChatThread.is_default.is_(True),
    )
    row = (await db.execute(select_default)).scalar_one_or_none()
    if row:
        return row

    insert_stmt = (
        pg_insert(ChatThread)
        .values(
            user_id=user.id,
            kind="general",
            entity_type=None,
            entity_id=None,
            title="General",
            is_default=True,
        )
        .on_conflict_do_nothing(index_elements=["user_id"], index_where=ChatThread.is_default.is_(True))
    )
    await db.execute(insert_stmt)
    await db.flush()
    row = (await db.execute(select_default)).scalar_one()
    return row


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

    Filters out ``system`` and ``event`` roles (those are UI-side annotations, not part of
    the LLM exchange). Keeps the most recent ``limit`` user/assistant pairs.
    """
    stmt = (
        select(ChatMessage)
        .where(
            ChatMessage.thread_id == thread.id,
            ChatMessage.role.in_(("user", "assistant")),
        )
        .order_by(ChatMessage.id.desc())
        .limit(limit * 2)
    )
    rows = list((await db.execute(stmt)).scalars().all())
    rows.reverse()
    return [{"role": r.role, "content": r.content} for r in rows]


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
