"""Generate a short thread title after the first successful assistant reply.

Titles mirror the conversation language (no UI translation). See plan: auto chat titles.
"""

from __future__ import annotations

import logging
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat_thread import ChatThread
from app.models.user import User
from app.services.ai_providers import provider_kind_requires_api_key
from app.services.llm_client import LLMClient
from app.services.user_ai_settings_service import UserAISettingsService

logger = logging.getLogger(__name__)

# Matches frontend i18n defaults and legacy DB default.
_THREAD_TITLE_PLACEHOLDERS_FOLDED: frozenset[str] = frozenset(
    s.casefold() for s in ("New chat", "Nuevo chat", "General")
)

_AGENT_REPLY_PLACEHOLDER = "\u2026"

_TITLE_SYSTEM = """You name chat conversations for a sidebar list.
Return exactly one short title: about 3–8 words, plain text, no quotes, one line.
Language rules (critical):
- Write the title in the same language as the conversation below.
- If the user mixes two or more languages, use the language of the first substantive user message—do not translate to English or any other language.
- Do not output labels like "Title:"."""

_TITLE_USER_TEMPLATE = """USER:
{user}

ASSISTANT:
{assistant}

Reply with only the title."""


def is_thread_title_placeholder(title: str | None) -> bool:
    t = (title or "").strip()
    if not t:
        return True
    return t.casefold() in _THREAD_TITLE_PLACEHOLDERS_FOLDED


async def _thread_owned_by_user(
    db: AsyncSession, user: User, thread_id: int
) -> ChatThread | None:
    stmt = select(ChatThread).where(ChatThread.id == thread_id, ChatThread.user_id == user.id)
    return (await db.execute(stmt)).scalar_one_or_none()


def sanitize_generated_title(raw: str) -> str:
    s = (raw or "").strip()
    s = re.sub(r"[\r\n]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = s.strip(" \"'«»")
    return s[:255]


async def maybe_generate_thread_title(
    db: AsyncSession,
    user: User,
    thread_id: int,
    *,
    user_message: str,
    assistant_message: str,
    run_status: str,
) -> None:
    """If the thread still has a default title, replace it using a short LLM completion.

    Never raises; logs failures. Idempotent once the title is non-placeholder.
    """
    if run_status != "completed":
        return
    a = (assistant_message or "").strip()
    if not a or a == _AGENT_REPLY_PLACEHOLDER:
        return

    thread = await _thread_owned_by_user(db, user, thread_id)
    if not thread or thread.kind != "general":
        return
    if not is_thread_title_placeholder(thread.title):
        return

    settings_row = await UserAISettingsService.get_or_create(db, user)
    if getattr(settings_row, "agent_processing_paused", False) or settings_row.ai_disabled:
        return

    api_key = await UserAISettingsService.get_api_key(db, user)
    if provider_kind_requires_api_key(settings_row.provider_kind) and not api_key:
        return

    u_block = (user_message or "").strip() or "(empty)"
    a_block = a
    user_prompt = _TITLE_USER_TEMPLATE.format(user=u_block, assistant=a_block)

    try:
        raw = await LLMClient.chat_completion(
            api_key,
            settings_row,
            messages=[
                {"role": "system", "content": _TITLE_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.25,
            max_tokens=64,
        )
    except Exception:
        logger.exception("chat_thread_title: LLM failed user_id=%s thread_id=%s", user.id, thread_id)
        return

    title = sanitize_generated_title(raw)
    if not title or is_thread_title_placeholder(title):
        return

    thread.title = title
    try:
        await db.commit()
        await db.refresh(thread)
    except Exception:
        logger.exception("chat_thread_title: commit failed user_id=%s thread_id=%s", user.id, thread_id)
        await db.rollback()
