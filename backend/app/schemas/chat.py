from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

ThreadKind = Literal["general", "entity"]
EntityType = Literal["contact", "deal", "event", "email", "drive_file", "attachment"]
MessageRole = Literal["user", "assistant", "system", "event"]


class EntityRef(BaseModel):
    """Lightweight @mention chip the artist drops into the composer by tapping a library item."""

    type: EntityType
    id: int
    label: str | None = None


class ThreadRead(BaseModel):
    id: int
    kind: ThreadKind
    entity_type: EntityType | None = None
    entity_id: int | None = None
    title: str
    pinned: bool
    archived: bool
    last_message_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    unread: int = 0


class ThreadCreate(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    entity_type: EntityType | None = None
    entity_id: int | None = None


class ThreadPatch(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    pinned: bool | None = None
    archived: bool | None = None


class MessageRead(BaseModel):
    id: int
    thread_id: int
    role: MessageRole
    content: str
    attachments: list[dict[str, Any]] | None = None
    agent_run_id: int | None = None
    created_at: datetime


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=16000)
    references: list[EntityRef] = Field(default_factory=list)
    attachment_ids: list[int] = Field(default_factory=list)


class MessageSendResult(BaseModel):
    """Returned by POST /threads/{id}/messages — both sides + any inline cards.

    The frontend appends ``user_message`` then ``assistant_message`` to the rendered
    thread; the assistant message's ``attachments`` may contain inline cards (approval,
    undo, connector setup) the chat view renders specially.
    """

    thread: ThreadRead
    user_message: MessageRead
    assistant_message: MessageRead
    error: str | None = None


class StartChatResponse(BaseModel):
    """Returned by every ``POST /{entity}/{id}/start-chat`` endpoint.

    The frontend uses ``thread_id`` to navigate to ``/?thread=<id>`` so the user lands
    in the entity-bound thread with the seeded announcement already visible.
    """

    thread_id: int
