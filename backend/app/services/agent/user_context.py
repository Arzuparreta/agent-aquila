"""Async-maintained user context snapshot (TL;DR) for harness injection."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.user import User
from app.models.user_ai_settings import UserAISettings
from app.services.agent_memory_service import AgentMemoryService
from app.services.ai_providers import provider_kind_requires_api_key
from app.services.llm_client import LLMClient
from app.services.user_ai_settings_service import UserAISettingsService

logger = logging.getLogger(__name__)

_SNIPPET_MAX = 9000
_FALLBACK_MAX = 2500
_OVERVIEW_MAX_STORE = 8000


def _section_for_prompt(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return ""
    return "## User context snapshot (cached)\n\n" + t + "\n\n"


async def injectable_user_context_section(
    db: AsyncSession,
    user: User,
    *,
    settings_row: UserAISettings,
    turn_profile: str,
    inject_in_chat: bool,
) -> str:
    """Return markdown to prepend in the system prompt, or empty string."""
    tp = (turn_profile or "user_chat").strip().lower()
    if tp == "user_chat" and not inject_in_chat:
        return ""
    raw = getattr(settings_row, "agent_context_overview", None)
    if not raw or not str(raw).strip():
        return ""
    return _section_for_prompt(str(raw))


async def refresh_user_context_overview(
    db: AsyncSession,
    user: User,
    *,
    force_llm: bool = True,
) -> None:
    """Recompute ``agent_context_overview`` from canonical memory (best-effort LLM compress)."""
    row = await UserAISettingsService.get_or_create(db, user)
    if row.ai_disabled or getattr(row, "agent_processing_paused", False):
        return
    blob = await AgentMemoryService.recent_for_prompt(db, user)
    if not blob or len(blob.strip()) < 12:
        row.agent_context_overview = None
        row.agent_context_overview_updated_at = datetime.now(UTC)
        await db.commit()
        return

    snippet = blob[:_SNIPPET_MAX] + ("…" if len(blob) > _SNIPPET_MAX else "")
    api_key = await UserAISettingsService.get_api_key(db, user)
    use_llm = bool(getattr(settings, "agent_user_context_overview_llm_enabled", True))
    use_llm = use_llm and force_llm
    if use_llm and provider_kind_requires_api_key(row.provider_kind) and not (api_key or "").strip():
        use_llm = False

    if use_llm:
        try:
            prompt = (
                "Compress the following into at most 8 short bullet points for another assistant "
                "that will help this user. Focus: identity, preferences, active projects, and "
                "anything that affects how to triage mail or calendar. Be factual; do not invent.\n\n"
                + snippet
            )
            out = await LLMClient.chat_completion(
                api_key or "",
                row,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.15,
                max_tokens=450,
            )
            text = (out or "").strip()
            if text:
                row.agent_context_overview = text[:_OVERVIEW_MAX_STORE]
                row.agent_context_overview_updated_at = datetime.now(UTC)
                await db.commit()
                return
        except Exception:  # noqa: BLE001
            logger.warning("user_context_overview LLM refresh failed user_id=%s", user.id, exc_info=True)

    # Fallback: lossy truncation of the same blob the model would see.
    row.agent_context_overview = snippet[:_FALLBACK_MAX] + ("…" if len(snippet) > _FALLBACK_MAX else "")
    row.agent_context_overview_updated_at = datetime.now(UTC)
    await db.commit()


async def maybe_refresh_after_post_turn(
    db: AsyncSession,
    user: User,
    *,
    min_interval_minutes: int | None = None,
) -> None:
    """Throttle snapshot refresh so post-turn does not hammer the provider."""
    row = await UserAISettingsService.get_or_create(db, user)
    interval = min_interval_minutes
    if interval is None:
        interval = int(getattr(settings, "agent_user_context_refresh_min_minutes", 180) or 180)
    last = getattr(row, "agent_context_overview_updated_at", None)
    if last is not None:
        try:
            delta = datetime.now(UTC) - last
            if delta < timedelta(minutes=max(5, interval)):
                return
        except (TypeError, ValueError):
            pass
    await refresh_user_context_overview(db, user, force_llm=True)
