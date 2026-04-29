"""Effective harness limits from turn profile + merged runtime config."""

from __future__ import annotations

from app.schemas.agent_runtime_config import AgentRuntimeConfigResolved
from app.schemas.agent_turn_profile import normalize_turn_profile, TURN_PROFILE_USER_CHAT


def effective_tool_palette_mode_for_turn(rt: AgentRuntimeConfigResolved, turn_profile: str | None) -> str:
    """``compact`` for most non-chat profiles when the flag is on (token savings)."""
    tp = normalize_turn_profile(turn_profile)
    if tp == TURN_PROFILE_USER_CHAT:
        return rt.agent_tool_palette
    if getattr(rt, "agent_non_chat_uses_compact_palette", True):
        return "compact"
    return rt.agent_tool_palette


def resolve_max_tool_steps_for_turn(rt: AgentRuntimeConfigResolved, turn_profile: str | None) -> int:
    tp = normalize_turn_profile(turn_profile)
    if tp == "heartbeat":
        v = getattr(rt, "agent_heartbeat_max_tool_steps", None)
        return int(v) if v is not None else rt.agent_max_tool_steps
    if tp == "channel_inbound":
        v = getattr(rt, "agent_channel_inbound_max_tool_steps", None)
        return int(v) if v is not None else rt.agent_max_tool_steps
    if tp == "automation":
        v = getattr(rt, "agent_automation_max_tool_steps", None)
        return int(v) if v is not None else rt.agent_max_tool_steps
    return rt.agent_max_tool_steps
