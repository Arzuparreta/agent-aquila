"""Backward-compatible shim — all agent logic lives in app.services.agent.

Refactored in Phase 5: Split into agent/ package modules.
Phase 6: Cleaned up stale imports, added missing resolve_turn_tool_palette.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User

from app.services.agent import AgentService
from app.services.agent import AGENT_TOOLS, AGENT_TOOL_NAMES, FINAL_ANSWER_TOOL_NAME
from app.services.agent import TOOL_DISPATCH as AGENT_TOOL_DISPATCH
from app.services.agent import filter_tools_for_user_connectors, tools_for_palette_mode


async def resolve_turn_tool_palette(
    db: AsyncSession,
    user: User,
    *,
    turn_profile: str,
) -> list[dict[str, Any]]:
    """Resolve which tools the user can use this turn."""
    from app.schemas.agent_turn_profile import TURN_PROFILE_USER_CHAT
    from app.services.agent_runtime_config_service import resolve_for_user

    rt = await resolve_for_user(db, user)

    mode = rt.agent_tool_palette
    if rt.agent_non_chat_uses_compact_palette and turn_profile != TURN_PROFILE_USER_CHAT:
        mode = "compact"

    base = tools_for_palette_mode(mode=mode)

    if rt.agent_connector_gated_tools:
        base = await filter_tools_for_user_connectors(db, user.id, base)

    if len(base) < 10:
        base = tools_for_palette_mode(mode=mode)
        base = await filter_tools_for_user_connectors(db, user.id, base)
        if len(base) < 10:
            base = tools_for_palette_mode(mode=mode)

    return base


def get_tool_palette(
    tool_ids: list[str], *, compact: bool = False
) -> list[dict[str, Any]]:
    """Return a subset of AGENT_TOOLS."""
    return tools_for_palette_mode(
        tool_ids or AGENT_TOOL_NAMES,
        mode="compact" if compact else "full",
    )
