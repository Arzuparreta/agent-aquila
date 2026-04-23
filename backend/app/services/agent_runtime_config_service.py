"""Merge per-user ``agent_runtime_config`` JSON with env defaults (``config.settings``)."""

from __future__ import annotations

from typing import Any

from app.core.config import Settings, settings
from app.models.user import User
from app.models.user_ai_settings import UserAISettings
from app.schemas.agent_runtime_config import (
    AgentRuntimeConfigPartial,
    AgentRuntimeConfigResolved,
)
from sqlalchemy.ext.asyncio import AsyncSession


def _get(defaults: Settings, key: str, raw: dict[str, Any]) -> Any:
    if key in raw:
        return raw[key]
    return getattr(defaults, key)


def _opt_int(v: Any) -> int | None:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    s = str(v).strip()
    if not s:
        return None
    try:
        return int(s)
    except (TypeError, ValueError):
        return None


def merge_stored_with_env(raw: dict[str, Any] | None) -> AgentRuntimeConfigResolved:
    """Build effective runtime config. ``raw`` is the JSON column (partial overrides)."""
    s = settings
    r = raw if isinstance(raw, dict) else {}
    payload = {
        "agent_max_runs_per_hour": int(_get(s, "agent_max_runs_per_hour", r)),
        "agent_max_tool_steps": int(_get(s, "agent_max_tool_steps", r)),
        "agent_async_runs": bool(_get(s, "agent_async_runs", r)),
        "agent_heartbeat_burst_per_hour": int(_get(s, "agent_heartbeat_burst_per_hour", r)),
        "agent_heartbeat_enabled": bool(_get(s, "agent_heartbeat_enabled", r)),
        "agent_heartbeat_minutes": int(_get(s, "agent_heartbeat_minutes", r)),
        "agent_heartbeat_check_gmail": bool(_get(s, "agent_heartbeat_check_gmail", r)),
        "agent_tool_palette": str(_get(s, "agent_tool_palette", r)).strip().lower() or "full",
        "agent_prompt_tier": str(_get(s, "agent_prompt_tier", r)).strip().lower() or "full",
        "agent_include_harness_facts": bool(_get(s, "agent_include_harness_facts", r)),
        "context_budget_v2": bool(_get(s, "context_budget_v2", r)),
        "token_aware_history": bool(_get(s, "token_aware_history", r)),
        "dynamic_model_limits": bool(_get(s, "dynamic_model_limits", r)),
        "agent_connector_gated_tools": bool(_get(s, "agent_connector_gated_tools", r)),
        "agent_prompted_compact_json": bool(_get(s, "agent_prompted_compact_json", r)),
        "agent_history_turns": int(_get(s, "agent_history_turns", r)),
        "agent_thread_compact_after_pairs": int(_get(s, "agent_thread_compact_after_pairs", r)),
        "agent_memory_flush_enabled": bool(_get(s, "agent_memory_flush_enabled", r)),
        "agent_memory_flush_max_steps": int(_get(s, "agent_memory_flush_max_steps", r)),
        "agent_memory_flush_max_transcript_chars": int(_get(s, "agent_memory_flush_max_transcript_chars", r)),
        "agent_memory_post_turn_enabled": bool(_get(s, "agent_memory_post_turn_enabled", r)),
        "agent_memory_post_turn_mode": str(_get(s, "agent_memory_post_turn_mode", r)).strip().lower()
        or "committee",
        "agent_channel_gateway_enabled": bool(_get(s, "agent_channel_gateway_enabled", r)),
        "agent_email_domain_allowlist": str(_get(s, "agent_email_domain_allowlist", r) or ""),
        "agent_non_chat_uses_compact_palette": bool(_get(s, "agent_non_chat_uses_compact_palette", r)),
        "agent_heartbeat_max_tool_steps": _opt_int(_get(s, "agent_heartbeat_max_tool_steps", r)),
        "agent_channel_inbound_max_tool_steps": _opt_int(_get(s, "agent_channel_inbound_max_tool_steps", r)),
        "agent_automation_max_tool_steps": _opt_int(_get(s, "agent_automation_max_tool_steps", r)),
        "agent_inject_user_context_in_chat": bool(_get(s, "agent_inject_user_context_in_chat", r)),
    }
    return AgentRuntimeConfigResolved.model_validate(payload)


async def resolve_for_user(db: AsyncSession, user: User) -> AgentRuntimeConfigResolved:
    from app.services.user_ai_settings_service import UserAISettingsService

    prefs = await UserAISettingsService.get_or_create(db, user)
    raw = getattr(prefs, "agent_runtime_config", None)
    return merge_stored_with_env(raw if isinstance(raw, dict) else None)


def merge_patch_into_stored(
    existing: dict[str, Any] | None,
    patch: AgentRuntimeConfigPartial,
) -> dict[str, Any]:
    """Deep-merge validated patch; ``None`` values in patch remove override keys (revert to env)."""
    data = patch.model_dump(exclude_unset=True)
    base: dict[str, Any] = dict(existing) if isinstance(existing, dict) else {}
    for key, val in data.items():
        if val is None:
            base.pop(key, None)
        else:
            base[key] = val
    return base


def runtime_from_row(row: UserAISettings) -> AgentRuntimeConfigResolved:
    raw = getattr(row, "agent_runtime_config", None)
    return merge_stored_with_env(raw if isinstance(raw, dict) else None)
