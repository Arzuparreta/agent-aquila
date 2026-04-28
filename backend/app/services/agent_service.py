"""ReAct loop + tool dispatch: live provider tools, memory, and skills.

Refactored in Phase 5: Split into agent/ package modules.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.envelope_crypto import KeyDecryptError
from app.models.agent_run import AgentRun, AgentRunStep, AgentTraceEvent
from app.models.chat_message import ChatMessage
from app.models.connector_connection import ConnectorConnection
from app.models.pending_proposal import PendingProposal
from app.models.scheduled_task import ScheduledTask
from app.models.user import User
from app.schemas.agent import (
    AgentRunAttentionRead,
    AgentRunRead,
    AgentRunSummaryRead,
    AgentStepRead,
    AgentTraceEventRead,
    PendingProposalRead,
)

# Agent package - refactored modules
from app.services.agent import (
    AGENT_TOOL_DISPATCH,
    AGENT_TOOLS,
    AGENT_TOOL_NAMES,
    FINAL_ANSWER_TOOL_NAME,
    AgentService,
    _resolve_connection,
    _gmail_client,
    _calendar_client,
    _drive_client,
    _youtube_client,
    _tasks_client,
    _people_client,
    _sheets_client,
    _docs_client,
    _icloud_app_password_creds,
    _icloud_caldav_client,
    _parse_rfc3339_to_utc_datetime,
    _default_icloud_calendar_url,
    _graph_client,
    _github_client,
    _slack_api_client,
    _linear_client,
    _notion_client,
    _telegram_client,
    _discord_client,
    CALENDAR_TOOL_PROVIDERS,
    DISCORD_TOOL_PROVIDERS,
    DOCS_TOOL_PROVIDERS,
    DRIVE_TOOL_PROVIDERS,
    GITHUB_TOOL_PROVIDERS,
    GMAIL_TOOL_PROVIDERS,
    GRAPH_CALENDAR_TOOL_PROVIDERS,
    ICLOUD_TOOL_PROVIDERS,
    LINEAR_TOOL_PROVIDERS,
    NOTION_TOOL_PROVIDERS,
    OUTLOOK_MAIL_TOOL_PROVIDERS,
    PEOPLE_TOOL_PROVIDERS,
    SHEETS_TOOL_PROVIDERS,
    SLACK_TOOL_PROVIDERS,
    TASKS_TOOL_PROVIDERS,
    TEAMS_TOOL_PROVIDERS,
    TELEGRAM_TOOL_PROVIDERS,
    YOUTUBE_TOOL_PROVIDERS,
    filter_tools_for_user_connectors,
    tools_for_palette_mode,
    _execute_agent_loop,
    _dispatch_tool,
    _insert_proposal,
    _idem,
    _scheduled_task_to_dict,
    _parse_label_ids,
    run_agent_invalid_preflight,
    abort_pending_run_queue_unavailable,
    create_pending_agent_run,
    run_agent,
    _load_steps,
    _to_read,
    list_recent_runs,
    list_trace_events,
    get_run,
)

from app.services.agent.runtime import (
    merge_stored_with_env,
    resolve_for_user,
    UserAISettingsService,
    estimate_message_tokens,
    plan_budget,
    NoActiveProviderError,
    LLMProviderError,
    clamp_tool_content_by_tokens,
    content_sha256_preview,
)
from app.services.ai_providers import provider_kind_requires_api_key
from app.services.agent.harness.effective import (
    effective_tool_palette_mode_for_turn,
    resolve_max_tool_steps_for_turn,
)
from app.services.agent.memory.post_turn import heuristic_wants_post_turn_extraction
from app.services.agent.turn_profile import (
    TURN_PROFILE_USER_CHAT,
    normalize_turn_profile,
)
from app.services.agent.workspace import build_system_prompt, linked_connector_providers
from app.services.agent.user_context import injectable_user_context_section
from app.services.agent.trace import (
    EV_LLM_REQUEST,
    EV_LLM_RESPONSE,
    EV_RUN_STARTED,
    EV_RUN_COMPLETED,
    EV_RUN_FAILED,
    EV_TOOL_STARTED,
    EV_TOOL_FINISHED,
    emit_trace_event,
    new_trace_id,
    new_span_id,
    _conversation_trace_snapshot,
    _trim_step_payload_for_client,
    _approx_prompt_tokens,
    _assistant_message_from,
    _is_context_overflow,
    _reduce_conversation_for_budget,
)
from app.services.agent.replay import AgentReplayContext
from app.services.agent.proposal import proposal_to_read
from app.services.agent.attention import build_attention_snapshot

_logger = logging.getLogger(__name__)


def get_tool_palette(
    tool_ids: list[str], *, compact: bool = False
) -> list[dict[str, Any]]:
    """Return a subset of AGENT_TOOLS."""
    return tools_for_palette_mode(
        tool_ids or AGENT_TOOL_NAMES,
        mode="compact" if compact else "full",
    )


def resolve_turn_tool_palette(
    db: AsyncSession,
    user: User,
    *,
    turn_profile: str,
) -> list[dict[str, Any]]:
    """Resolve which tools the user can use this turn."""
    from app.services.user_ai_settings_service import UserAISettingsService

    settings_row = await UserAISettingsService.get_or_create(db, user)
    linked = await linked_connector_providers(db, user.id)

    tool_ids = [
        name
        for name in AGENT_TOOL_NAMES
        if filter_tools_for_user_connectors(
            db, name, user, linked, settings_row.agent_connector_gated_tools
        )
    ]

    mode = settings_row.agent_tool_palette
    if settings_row.agent_non_chat_uses_compact_palette and turn_profile != TURN_PROFILE_USER_CHAT:
        mode = "compact"

    return tools_for_palette_mode(tool_ids, mode=mode)


# The rest of the file would now just re-export from the agent package
# The original agent_service.py monolith is now split into:
# - app/services/agent/connection.py
# - app/services/agent/handlers/*.py
# - app/services/agent/dispatch.py
# - app/services/agent/__init__.py (AgentService wrapper)
