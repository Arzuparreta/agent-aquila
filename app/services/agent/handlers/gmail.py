from __future__ import annotations
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.connector_connection import ConnectorConnection
from app.models.user import User
from app.services.agent.runtime_clients import GmailClient

# From agent_service.py (Phase 5 refactor)

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
from app.services.agent_harness.native import chat_turn_native
from app.services.agent_dispatch_table import AGENT_TOOL_DISPATCH
from app.schemas.agent_runtime_config import AgentRuntimeConfigResolved
from app.services.agent_harness_effective import (
effective_tool_palette_mode_for_turn,

resolve_max_tool_steps_for_turn,
)
from app.services.agent_memory_post_turn_service import heuristic_wants_post_turn_extraction
from app.services.agent_memory_service import AgentMemoryService
from app.services.agent_runtime_config_service import merge_stored_with_env, resolve_for_user
from app.schemas.agent_turn_profile import TURN_PROFILE_USER_CHAT, normalize_turn_profile
from app.services.agent_run_attention import build_attention_snapshot
from app.services.agent_replay import AgentReplayContext
from app.services.agent_tools import (
AGENT_TOOL_NAMES,
AGENT_TOOLS,
FINAL_ANSWER_TOOL_NAME,
filter_tools_for_user_connectors,
tools_for_palette_mode,
)
from app.services.agent_trace import (
EV_LLM_REQUEST,

EV_LLM_RESPONSE,
EV_RUN_COMPLETED,
EV_RUN_FAILED,
EV_RUN_STARTED,
EV_TOOL_FINISHED,
EV_TOOL_STARTED,
content_sha256_preview,
emit_trace_event,

new_span_id,
new_trace_id,
)
from app.services.agent_user_context import injectable_user_context_section
from app.services.agent_workspace import (
build_system_prompt,
linked_connector_providers,
list_allowed_workspace_files,

TEAMS_TOOL_PROVIDERS,
TELEGRAM_TOOL_PROVIDERS,
YOUTUBE_TOOL_PROVIDERS,
)
from app.services.connectors.calendar_adapters import (
create_calendar_event,
delete_calendar_event,
update_calendar_event,
)
from app.services.connectors.file_adapters import share_file, upload_file
from app.services.connectors.gcal_client import CalendarAPIError, GoogleCalendarClient
from app.services.connectors.gmail_client import GmailAPIError, GmailClient
from app.services.connectors.drive_client import DriveAPIError, GoogleDriveClient
from app.services.connectors.google_people_client import GooglePeopleAPIError, GooglePeopleClient
from app.services.connectors.google_docs_client import GoogleDocsAPIError, GoogleDocsClient
from app.services.connectors.google_sheets_client import GoogleSheetsAPIError, GoogleSheetsClient
from app.services.connectors.google_tasks_client import GoogleTasksAPIError, GoogleTasksClient

from app.services.connectors.graph_client import GraphAPIError, GraphClient
from app.services.connectors.icloud_caldav_client import ICloudCalDAVError, ICloudCalDAVClient
from app.services.connectors.icloud_contacts_client import (
ICloudContactsError,
list_contacts as icloud_carddav_list_contacts,
search_contacts as icloud_carddav_search_contacts,
)
from app.services.connectors.icloud_pyicloud_extras import (
list_notes as icloud_pyicloud_list_notes,
list_photos as icloud_pyicloud_list_photos,
list_reminders as icloud_pyicloud_list_reminders,
)
from app.services.connectors.icloud_drive_client import (
DEFAULT_DOWNLOAD_MAX_BYTES,
ICloudDriveError,
download_file_sync,

list_folder_sync,
)
from app.services.connectors.whatsapp_client import WhatsAppAPIError, WhatsAppClient
from app.services.connectors.youtube_client import YoutubeAPIError, YoutubeClient
from app.services.connectors.github_client import GitHubAPIError, GitHubClient
from app.services.connectors.linear_client import LinearAPIError, LinearClient
from app.services.connectors.notion_client import NotionAPIError, NotionClient
from app.services.connectors.discord_bot_client import DiscordAPIError, DiscordBotClient
from app.services.connectors.slack_client import SlackAPIError, SlackClient
from app.services.connectors.telegram_bot_client import TelegramAPIError, TelegramBotClient
from app.services.connectors.web_search_client import WebSearchAPIError, WebSearchClient

from app.services.gmail_metadata_cache import (
get_message_metadata,
get_thread as gmail_cache_get_thread,
invalidate_connection as gmail_cache_invalidate_connection,
invalidate_message as gmail_cache_invalidate_message,
put_message_metadata,
put_thread as gmail_cache_put_thread,
)
from app.services.llm_client import ChatResponse, ChatToolCall, LLMClient
from app.services.llm_errors import LLMProviderError, NoActiveProviderError
from app.services.model_limits_service import resolve_model_limits

from app.services.connector_setup_service import (
submit_discord_bot_credentials as submit_discord_bot_credentials_service,
submit_github_credentials as submit_github_credentials_service,
submit_icloud_caldav_credentials as submit_icloud_caldav_credentials_service,
submit_linear_credentials as submit_linear_credentials_service,
submit_notion_credentials as submit_notion_credentials_service,
submit_slack_credentials as submit_slack_credentials_service,
submit_telegram_bot_credentials as submit_telegram_bot_credentials_service,
submit_whatsapp_credentials as submit_whatsapp_credentials_service,
)

from app.services.device_ingest_service import DeviceIngestService
from app.services.connector_service import ConnectorService
from app.services.oauth import TokenManager
from app.services.oauth.errors import ConnectorNeedsReauth, OAuthError
from app.services.proposal_service import proposal_to_read
from app.services.skills_service import _skills_dir
from app.services.skills_service import list_skills as _list_skills
from app.services.skills_service import load_skill as _load_skill
from app.services.scheduled_task_service import ScheduledTaskService
from app.services.user_ai_settings_service import (

UserAISettingsService,
coerce_harness_mode,
merge_calendar_timezone_from_user_prefs,
)
from app.services.user_time_context import normalize_time_format, session_time_result
from app.services.token_budget_service import (
clamp_tool_content_by_tokens,
estimate_message_tokens,
plan_budget,
select_history_by_budget,
)

_replay_ctx: ContextVar[AgentReplayContext | None] = ContextVar("agent_replay", default=None)

_agent_ctx: ContextVar[dict[str, Any]] = ContextVar("agent_ctx", default={})

_logger_memory_tools = logging.getLogger(__name__)

_logger = logging.getLogger(__name__)

def get_tool_palette(
user: User,
*,
tenant_hint: str | None = None,
palette_mode: str | None = None,
runtime: AgentRuntimeConfigResolved | None = None,
) -> list[dict[str, Any]]:
"""Synchronous palette (no connector gating). Prefer :func:`resolve_turn_tool_palette` in the loop."""
del tenant_hint
del user
rt = runtime if runtime is not None else merge_stored_with_env(None)
mode = palette_mode if palette_mode is not None else rt.agent_tool_palette

return tools_for_palette_mode(mode)


async def resolve_turn_tool_palette(
db: AsyncSession,
user: User,
*,
turn_profile: str | None = None,
) -> list[dict[str, Any]]:
"""Tool schemas for this run, optionally omitting tools for disconnected providers."""
rt = await resolve_for_user(db, user)
mode = effective_tool_palette_mode_for_turn(rt, turn_profile)
base = tools_for_palette_mode(mode)

if not rt.agent_connector_gated_tools:
    return base
filtered = await filter_tools_for_user_connectors(db, user.id, base)
names = {t["function"]["name"] for t in filtered}
if FINAL_ANSWER_TOOL_NAME not in names:

    return base
if len(filtered) < 6:
    return base
return filtered


def _conversation_trace_snapshot(
conversation: list[dict[str, Any]], *, max_items: int = 8, max_content: int = 4000
) -> str:
"""Compact JSON of recent messages for AgentRunStep diagnostics."""
tail = conversation[-max_items:]
slim: list[dict[str, Any]] = []
for m in tail:
    role = m.get("role")
    content = m.get("content")
    if isinstance(content, str) and len(content) > max_content:
        content = content[:max_content] + "…"
    item: dict[str, Any] = {"role": role, "content": content}
    tcalls = m.get("tool_calls")

    if tcalls:
        item["tool_calls_preview"] = []
        for tc in tcalls[:16]:
            if isinstance(tc, dict):
                fn = tc.get("function") or {}
                item["tool_calls_preview"].append({"name": fn.get("name")})
    slim.append(item)
try:
    return json.dumps(slim, ensure_ascii=False)[:12000]
except (TypeError, ValueError):
    return "[]"


# ``GET /agent/runs/{id}`` must stay small enough for browsers and Next.js dev rewrites;
# Gmail/Calendar tool results can be megabytes of JSON.
_MAX_STEP_PAYLOAD_JSON_CHARS = 20_000


def _trim_step_payload_for_client(payload: dict[str, Any] | None) -> dict[str, Any] | None:
"""Shrink persisted step payloads before returning them over HTTP."""
if payload is None:
    return None
try:
    serialized = json.dumps(payload, ensure_ascii=False, default=str)
except (TypeError, ValueError):
    return {"_serialization_error": True}
if len(serialized) <= _MAX_STEP_PAYLOAD_JSON_CHARS:
    return payload
if isinstance(payload, dict) and "result" in payload:
    slim = dict(payload)
    res = slim.get("result")
    if isinstance(res, (dict, list)):
        try:
            res_raw = json.dumps(res, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            slim["result"] = {"_truncated": True}
            return slim
        if len(res_raw) > 8000:
            slim["result"] = {
                "_truncated": True,
                "_approx_chars": len(res_raw),
                "_preview": res_raw[:8000] + "…",
            }
        try:
            slim_raw = json.dumps(slim, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            pass
        else:
            if len(slim_raw) <= _MAX_STEP_PAYLOAD_JSON_CHARS:
                return slim
return {
    "_truncated": True,
    "_approx_chars": len(serialized),
    "_preview": serialized[:8000] + "…",
}


def _approx_prompt_tokens(messages: list[dict[str, Any]]) -> int:
"""Rough token estimate for trace metrics (not billing-accurate)."""
try:
    raw = json.dumps(messages, ensure_ascii=False)
except (TypeError, ValueError):
    raw = ""
return max(1, len(raw) // 4)



def _is_context_overflow(exc: LLMProviderError) -> bool:
detail = str(exc.detail or "").lower()
return any(
    marker in detail
    for marker in (
        "maximum context length",
        "context length",
        "requested",
        "input_tokens",
        "prompt is too long",
    )

)


def _reduce_conversation_for_budget(
conversation: list[dict[str, Any]],
*,
input_budget_tokens: int,
) -> tuple[list[dict[str, Any]], bool]:
if not conversation:
    return conversation, False
if estimate_message_tokens(conversation) <= input_budget_tokens:

