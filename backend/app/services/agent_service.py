"""ReAct loop + tool dispatch: live provider tools, memory, and skills.

There are no local mailbox mirrors: every read tool calls the upstream API (Gmail, Calendar,
Drive, Outlook, Teams, and other linked connectors). Most writes run immediately; outbound email
and select high-risk sends use ``PendingProposal`` for human approval. Memory and skills are
agent-local state. ``turn_profile`` on each :class:`AgentRun` controls palette width and step
limits for context-first **non-chat** entry points.

Harness contract:

1. Send the FULL tool palette + the conversation to the LLM (native
   ``tools=`` parameter when the **native** harness is active; embedded JSON +
   ``<tool_call>`` tags when **prompted** — see ``agent_harness``).
2. Native path uses ``tool_choice="required"`` (honoured by cloud providers;
   Ollama may ignore it — we auto-fallback to prompted once per run).
3. Execute every tool call, feed results back (``role:"tool"`` for native;
   ``role:"user"`` + ``<tool_response>`` for prompted).
4. Stop when the model calls ``final_answer`` OR when ``settings.agent_max_tool_steps``.

Mis-invoked tools return structured errors; the model is expected to retry.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.envelope_crypto import KeyDecryptError
from app.models.agent_run import AgentRun, AgentRunStep, AgentTraceEvent
from app.models.chat_message import ChatMessage
from app.models.connector_connection import ConnectorConnection
from app.models.pending_proposal import PendingProposal
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
from app.services.agent_harness.prompted import (
    format_tool_results_for_prompt,
    parse_tool_calls_from_content,
)
from app.services.agent_harness.selector import resolve_effective_mode
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
    memory_flush_tools,
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
    build_memory_flush_system_prompt,
    build_system_prompt,
    linked_connector_providers,
    list_allowed_workspace_files,
    read_allowed_workspace_file,
)
from app.services.ai_providers import provider_kind_requires_api_key
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

# Provider id sets used by ``_resolve_connection``.
_GMAIL_PROVIDERS = ("google_gmail", "gmail")
_CAL_PROVIDERS = ("google_calendar", "gcal")
_DRIVE_PROVIDERS = ("google_drive", "gdrive")
_OUTLOOK_PROVIDERS = ("graph_mail",)
_TEAMS_PROVIDERS = ("graph_teams", "ms_teams")
_YOUTUBE_PROVIDERS = ("google_youtube",)
_TASKS_PROVIDERS = ("google_tasks",)
_PEOPLE_PROVIDERS = ("google_people",)
_SHEETS_PROVIDERS = ("google_sheets",)
_DOCS_PROVIDERS = ("google_docs",)
_WHATSAPP_PROVIDERS = ("whatsapp_business",)
_ICLOUD_CAL_PROVIDERS = ("icloud_caldav",)
_GITHUB_PROVIDERS = ("github",)
_SLACK_PROVIDERS = ("slack_bot",)
_LINEAR_PROVIDERS = ("linear",)
_NOTION_PROVIDERS = ("notion",)
_TELEGRAM_PROVIDERS = ("telegram_bot",)
_DISCORD_PROVIDERS = ("discord_bot",)

_replay_ctx: ContextVar[AgentReplayContext | None] = ContextVar("agent_replay", default=None)

_logger_memory_tools = logging.getLogger(__name__)

# When the user turn looks like naming / “remember this” / durable prefs, bias the model toward
# `upsert_memory` before `final_answer` (native `tool_choice="required"` allows final_answer alone).
_IDENTITY_AND_MEMORY_TOOL_NUDGE = """
## Host reminder (this user message)
This turn likely assigns or confirms your display name, or asks you to remember something durable. Before calling `final_answer`, call `upsert_memory` with appropriate keys (for names: `agent.identity.display_name_es` / `agent.identity.display_name_en`). If you tell the user you will remember or save it, you need a successful `upsert_memory` in this same turn — natural language alone does not persist.
"""


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
        return conversation, False
    reduced = list(conversation)
    changed = False
    # Keep system prompt + latest user turn, compact middle history first.
    if len(reduced) > 2:
        head = reduced[:1]
        middle = reduced[1:-1]
        tail = reduced[-1:]
        dropped_count = max(0, len(middle) - 8)
        compact_middle = select_history_by_budget(
            history=[
                {"role": str(m.get("role") or "user"), "content": str(m.get("content") or "")}
                for m in middle
                if isinstance(m.get("content"), str)
            ],
            budget_tokens=max(256, input_budget_tokens - estimate_message_tokens(head + tail)),
            keep_tail_messages=4,
        )
        if dropped_count > 0:
            summary = {
                "role": "system",
                "content": (
                    "Context compression summary:\n"
                    f"- Active Task: Continue the current user request.\n"
                    f"- Completed Actions: Earlier tool/assistant exchanges were compacted ({dropped_count} msgs).\n"
                    "- Pending Requests: Prior unresolved asks remain in compacted history.\n"
                    "- Constraints/Preferences: Preserve user constraints and provider/tool limitations.\n"
                    "- Open Questions: None explicitly tracked."
                ),
            }
            reduced = head + [summary] + compact_middle + tail
        else:
            reduced = head + compact_middle + tail
        changed = True
    # If still over budget, trim very large message contents.
    while estimate_message_tokens(reduced) > input_budget_tokens and len(reduced) > 1:
        idx = 1
        candidate = reduced[idx]
        content = candidate.get("content")
        if not isinstance(content, str) or len(content) < 600:
            if len(reduced) > 3:
                reduced.pop(idx)
                changed = True
                continue
            break
        candidate = dict(candidate)
        candidate["content"] = clamp_tool_content_by_tokens(content, max(100, len(content) // 10))
        reduced[idx] = candidate
        changed = True
    return reduced, changed


def _assistant_message_from(response: ChatResponse) -> dict[str, Any]:
    """Re-encode an assistant ``ChatResponse`` into a chat-completions message.

    We deliberately rebuild the dict (rather than reusing ``raw_message``) so
    the conversation history we feed back to the next call is exactly the
    OpenAI tool-calling shape, regardless of provider-specific extras.
    """
    msg: dict[str, Any] = {"role": "assistant", "content": response.content or None}
    if response.tool_calls:
        msg["tool_calls"] = [tc.to_message_dict() for tc in response.tool_calls]
    return msg


# ---------------------------------------------------------------------------
# Connection resolution
# ---------------------------------------------------------------------------


async def _resolve_connection(
    db: AsyncSession,
    user: User,
    args: dict[str, Any],
    providers: tuple[str, ...],
    *,
    label: str,
) -> ConnectorConnection:
    """Pick the connector connection a tool call should use.

    Honour ``args["connection_id"]`` when present; otherwise auto-detect
    the user's single matching connection. Returns a friendly-error
    ``RuntimeError`` (caught by the dispatcher) when the user has zero
    or many connections of the requested type.
    """
    cid = args.get("connection_id")
    if cid is not None:
        row = await db.get(ConnectorConnection, int(cid))
        if not row or row.user_id != user.id:
            raise RuntimeError(f"connection {cid} not found")
        if row.provider not in providers:
            raise RuntimeError(f"connection {cid} is not a {label} connection")
        return row
    stmt = (
        select(ConnectorConnection)
        .where(
            ConnectorConnection.user_id == user.id,
            ConnectorConnection.provider.in_(providers),
        )
        .order_by(ConnectorConnection.created_at.desc())
    )
    rows = list((await db.execute(stmt)).scalars().all())
    if not rows:
        raise RuntimeError(f"no {label} connection — connect one in Settings → Connectors")
    if len(rows) > 1:
        ids = ", ".join(str(r.id) for r in rows)
        raise RuntimeError(
            f"multiple {label} connections — pass `connection_id` (available: {ids})"
        )
    return rows[0]


async def _gmail_client(db: AsyncSession, row: ConnectorConnection) -> GmailClient:
    token = await TokenManager.get_valid_access_token(db, row)
    return GmailClient(token)


async def _calendar_client(db: AsyncSession, row: ConnectorConnection) -> GoogleCalendarClient:
    token = await TokenManager.get_valid_access_token(db, row)
    return GoogleCalendarClient(token)


async def _drive_client(db: AsyncSession, row: ConnectorConnection) -> GoogleDriveClient:
    token = await TokenManager.get_valid_access_token(db, row)
    return GoogleDriveClient(token)


async def _youtube_client(db: AsyncSession, row: ConnectorConnection) -> YoutubeClient:
    token = await TokenManager.get_valid_access_token(db, row)
    return YoutubeClient(token)


async def _tasks_client(db: AsyncSession, row: ConnectorConnection) -> GoogleTasksClient:
    token = await TokenManager.get_valid_access_token(db, row)
    return GoogleTasksClient(token)


async def _people_client(db: AsyncSession, row: ConnectorConnection) -> GooglePeopleClient:
    token = await TokenManager.get_valid_access_token(db, row)
    return GooglePeopleClient(token)


async def _sheets_client(db: AsyncSession, row: ConnectorConnection) -> GoogleSheetsClient:
    token = await TokenManager.get_valid_access_token(db, row)
    return GoogleSheetsClient(token)


async def _docs_client(db: AsyncSession, row: ConnectorConnection) -> GoogleDocsClient:
    token = await TokenManager.get_valid_access_token(db, row)
    return GoogleDocsClient(token)


def _icloud_app_password_creds(row: ConnectorConnection) -> tuple[str, str, bool]:
    creds = ConnectorService.decrypt_credentials(row)
    user = str(creds.get("username") or creds.get("apple_id") or "").strip()
    pw = str(creds.get("password") or creds.get("app_password") or "")
    china = bool(creds.get("china_mainland"))
    return user, pw, china


def _icloud_caldav_client(row: ConnectorConnection) -> ICloudCalDAVClient:
    user, pw, _china = _icloud_app_password_creds(row)
    return ICloudCalDAVClient(user, pw)


async def _graph_client(db: AsyncSession, row: ConnectorConnection) -> GraphClient:
    token = await TokenManager.get_valid_access_token(db, row)
    return GraphClient(token)


async def _github_client(db: AsyncSession, row: ConnectorConnection) -> GitHubClient:
    token = await TokenManager.get_valid_access_token(db, row)
    return GitHubClient(token)


async def _slack_api_client(db: AsyncSession, row: ConnectorConnection) -> SlackClient:
    token, creds, _p = await TokenManager.get_valid_creds(db, row)
    bot = str(creds.get("bot_token") or token or "").strip()
    return SlackClient(bot)


async def _linear_client(db: AsyncSession, row: ConnectorConnection) -> LinearClient:
    key = await TokenManager.get_valid_access_token(db, row)
    return LinearClient(key)


async def _notion_client(db: AsyncSession, row: ConnectorConnection) -> NotionClient:
    key = await TokenManager.get_valid_access_token(db, row)
    return NotionClient(key)


async def _telegram_client(db: AsyncSession, row: ConnectorConnection) -> TelegramBotClient:
    token, creds, _p = await TokenManager.get_valid_creds(db, row)
    bot = str(creds.get("bot_token") or token or "").strip()
    return TelegramBotClient(bot)


async def _discord_client(db: AsyncSession, row: ConnectorConnection) -> DiscordBotClient:
    token, creds, _p = await TokenManager.get_valid_creds(db, row)
    bot = str(creds.get("bot_token") or token or "").strip()
    return DiscordBotClient(bot)


class AgentService:
    # ------------------------------------------------------------------
    # Gmail tools
    # ------------------------------------------------------------------
    @staticmethod
    async def _tool_gmail_list_messages(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _GMAIL_PROVIDERS, label="Gmail")
        client = await _gmail_client(db, row)
        return await client.list_messages(
            page_token=args.get("page_token"),
            q=args.get("q"),
            label_ids=args.get("label_ids"),
            max_results=int(args.get("max_results") or 25),
        )

    @staticmethod
    async def _tool_gmail_get_message(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _GMAIL_PROVIDERS, label="Gmail")
        mid = str(args["message_id"])
        fmt = str(args.get("format") or "full")
        if fmt == "metadata":
            cached = get_message_metadata(row.id, mid)
            if cached is not None:
                return cached
        client = await _gmail_client(db, row)
        payload = await client.get_message(mid, format=fmt)
        if fmt == "metadata":
            put_message_metadata(row.id, mid, payload)
        return payload

    @staticmethod
    async def _tool_gmail_get_thread(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _GMAIL_PROVIDERS, label="Gmail")
        tid = str(args["thread_id"])
        fmt = str(args.get("format") or "metadata")
        if fmt == "metadata":
            cached = gmail_cache_get_thread(row.id, tid, fmt)
            if cached is not None:
                return cached
        client = await _gmail_client(db, row)
        payload = await client.get_thread(tid, format=fmt)
        if fmt == "metadata":
            gmail_cache_put_thread(row.id, tid, fmt, payload)
        return payload

    @staticmethod
    async def _tool_gmail_list_labels(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _GMAIL_PROVIDERS, label="Gmail")
        client = await _gmail_client(db, row)
        return await client.list_labels()

    @staticmethod
    async def _tool_gmail_list_filters(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _GMAIL_PROVIDERS, label="Gmail")
        client = await _gmail_client(db, row)
        return await client.list_filters()

    @staticmethod
    async def _tool_gmail_modify_message(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _GMAIL_PROVIDERS, label="Gmail")
        client = await _gmail_client(db, row)
        mid = str(args["message_id"])
        result = await client.modify_message(
            mid,
            add_label_ids=args.get("add_label_ids"),
            remove_label_ids=args.get("remove_label_ids"),
        )
        gmail_cache_invalidate_message(row.id, mid)
        return result

    @staticmethod
    async def _tool_gmail_modify_thread(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _GMAIL_PROVIDERS, label="Gmail")
        client = await _gmail_client(db, row)
        result = await client.modify_thread(
            str(args["thread_id"]),
            add_label_ids=args.get("add_label_ids"),
            remove_label_ids=args.get("remove_label_ids"),
        )
        gmail_cache_invalidate_connection(row.id)
        return result

    @staticmethod
    async def _tool_gmail_trash_message(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _GMAIL_PROVIDERS, label="Gmail")
        client = await _gmail_client(db, row)
        mid = str(args["message_id"])
        result = await client.trash_message(mid)
        gmail_cache_invalidate_message(row.id, mid)
        return result

    @staticmethod
    async def _tool_gmail_untrash_message(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _GMAIL_PROVIDERS, label="Gmail")
        client = await _gmail_client(db, row)
        mid = str(args["message_id"])
        result = await client.untrash_message(mid)
        gmail_cache_invalidate_message(row.id, mid)
        return result

    @staticmethod
    async def _tool_gmail_trash_thread(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _GMAIL_PROVIDERS, label="Gmail")
        client = await _gmail_client(db, row)
        result = await client.trash_thread(str(args["thread_id"]))
        gmail_cache_invalidate_connection(row.id)
        return result

    @staticmethod
    async def _tool_gmail_untrash_thread(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _GMAIL_PROVIDERS, label="Gmail")
        client = await _gmail_client(db, row)
        result = await client.untrash_thread(str(args["thread_id"]))
        gmail_cache_invalidate_connection(row.id)
        return result

    @staticmethod
    async def _tool_gmail_trash_bulk_query(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _GMAIL_PROVIDERS, label="Gmail")
        q = str(args.get("q") or "in:inbox")
        cap = min(max(int(args.get("max_messages") or 50_000), 1), 250_000)
        client = await _gmail_client(db, row)
        total = 0
        page_token: str | None = None
        capped = False
        while total < cap:
            page = await client.list_messages(page_token=page_token, q=q, max_results=500)
            messages = page.get("messages") or []
            ids = [str(m["id"]) for m in messages if isinstance(m, dict) and m.get("id")]
            if not ids:
                break
            for i in range(0, len(ids), 1000):
                chunk = ids[i : i + 1000]
                await client.batch_modify_messages(ids=chunk, add_label_ids=["TRASH"])
                total += len(chunk)
                if total >= cap:
                    capped = True
                    break
            if capped:
                break
            page_token = page.get("nextPageToken")
            if not page_token:
                break
        gmail_cache_invalidate_connection(row.id)
        return {"ok": True, "trashed_count": total, "q": q, "capped": capped}

    @staticmethod
    async def _tool_gmail_mark_read(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _GMAIL_PROVIDERS, label="Gmail")
        client = await _gmail_client(db, row)
        if args.get("thread_id"):
            out = await client.modify_thread(
                str(args["thread_id"]), remove_label_ids=["UNREAD"]
            )
            gmail_cache_invalidate_connection(row.id)
            return out
        if args.get("message_id"):
            mid = str(args["message_id"])
            out = await client.modify_message(mid, remove_label_ids=["UNREAD"])
            gmail_cache_invalidate_message(row.id, mid)
            return out
        return {"error": "either message_id or thread_id is required"}

    @staticmethod
    async def _tool_gmail_mark_unread(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _GMAIL_PROVIDERS, label="Gmail")
        client = await _gmail_client(db, row)
        if args.get("thread_id"):
            out = await client.modify_thread(
                str(args["thread_id"]), add_label_ids=["UNREAD"]
            )
            gmail_cache_invalidate_connection(row.id)
            return out
        if args.get("message_id"):
            mid = str(args["message_id"])
            out = await client.modify_message(mid, add_label_ids=["UNREAD"])
            gmail_cache_invalidate_message(row.id, mid)
            return out
        return {"error": "either message_id or thread_id is required"}

    @staticmethod
    async def _tool_gmail_silence_sender(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        """Create a skip-inbox filter; optionally move one thread/msg to Spam.

        Gmail **filters** cannot list **SPAM** in ``addLabelIds`` (API 400).
        For ``mode='spam'``, pass ``thread_id`` or ``message_id`` to move that
        mail to Spam via modify; future mail only gets the inbox-skipping filter.
        """
        email = str(args.get("email") or "").strip()
        if not email:
            return {"error": "email (sender address) is required"}
        mode = str(args.get("mode") or "mute").lower()
        if mode not in ("mute", "spam"):
            return {"error": "mode must be 'mute' or 'spam'"}
        row = await _resolve_connection(db, user, args, _GMAIL_PROVIDERS, label="Gmail")
        client = await _gmail_client(db, row)
        criteria = {"from": email}
        action: dict[str, Any] = {"removeLabelIds": ["INBOX", "UNREAD"]}
        moved_to_spam = False
        if mode == "spam":
            tid = args.get("thread_id")
            mid = args.get("message_id")
            if tid:
                await client.modify_thread(
                    str(tid),
                    add_label_ids=["SPAM"],
                    remove_label_ids=["INBOX"],
                )
                gmail_cache_invalidate_connection(row.id)
                moved_to_spam = True
            elif mid:
                m = str(mid)
                await client.modify_message(
                    m,
                    add_label_ids=["SPAM"],
                    remove_label_ids=["INBOX"],
                )
                gmail_cache_invalidate_message(row.id, m)
                moved_to_spam = True
        result = await client.create_filter(criteria=criteria, action=action)
        if mode == "spam":
            if moved_to_spam:
                summary = (
                    f"Moved the selected mail to Spam. Future mail from {email} will skip "
                    "the inbox (Gmail filters cannot assign the Spam label to new mail)."
                )
            else:
                summary = (
                    f"Filter created: future mail from {email} will skip the inbox. "
                    "To move existing mail to Spam, call again with thread_id or message_id "
                    "(filters cannot use the SPAM label)."
                )
        else:
            summary = f"Future mail from {email} will skip the inbox and be marked read."
        return {
            "ok": True,
            "mode": mode,
            "sender": email,
            "filter_id": result.get("id"),
            "moved_to_spam": moved_to_spam if mode == "spam" else None,
            "summary": summary,
        }

    @staticmethod
    async def _tool_gmail_create_filter(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _GMAIL_PROVIDERS, label="Gmail")
        client = await _gmail_client(db, row)
        criteria = args.get("criteria") or {}
        action = args.get("action") or {}
        if not criteria or not action:
            return {"error": "both criteria and action are required"}
        return await client.create_filter(criteria=criteria, action=action)

    @staticmethod
    async def _tool_gmail_delete_filter(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _GMAIL_PROVIDERS, label="Gmail")
        client = await _gmail_client(db, row)
        return await client.delete_filter(str(args["filter_id"]))

    # ------------------------------------------------------------------
    # Calendar tools
    # ------------------------------------------------------------------
    @staticmethod
    async def _tool_calendar_list_events(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _CAL_PROVIDERS, label="Google Calendar")
        client = await _calendar_client(db, row)
        # Without timeMin + orderBy=startTime, events.list returns an arbitrary first page
        # (often old events); upcoming items can be missing entirely when maxResults is capped.
        time_min = args.get("time_min")
        if time_min is None:
            time_min = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        time_max = args.get("time_max")
        return await client.list_events(
            str(args.get("calendar_id") or "primary"),
            page_token=args.get("page_token"),
            max_results=int(args.get("max_results") or 50),
            time_min=str(time_min),
            time_max=str(time_max) if time_max else None,
            order_by="startTime",
        )

    @staticmethod
    async def _tool_calendar_create_event(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _CAL_PROVIDERS, label="Google Calendar")
        _token, creds, provider = await TokenManager.get_valid_creds(db, row)
        payload = await merge_calendar_timezone_from_user_prefs(db, user, args)
        return await create_calendar_event(provider, creds, payload)

    @staticmethod
    async def _tool_calendar_update_event(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _CAL_PROVIDERS, label="Google Calendar")
        _token, creds, provider = await TokenManager.get_valid_creds(db, row)
        payload = await merge_calendar_timezone_from_user_prefs(db, user, args)
        return await update_calendar_event(provider, creds, payload)

    @staticmethod
    async def _tool_calendar_delete_event(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _CAL_PROVIDERS, label="Google Calendar")
        _token, creds, provider = await TokenManager.get_valid_creds(db, row)
        return await delete_calendar_event(provider, creds, str(args["event_id"]))

    # ------------------------------------------------------------------
    # Drive tools
    # ------------------------------------------------------------------
    @staticmethod
    async def _tool_drive_list_files(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _DRIVE_PROVIDERS, label="Google Drive")
        client = await _drive_client(db, row)
        return await client.list_files(
            page_token=args.get("page_token"),
            q=args.get("q"),
            page_size=int(args.get("page_size") or 50),
        )

    @staticmethod
    async def _tool_drive_upload_file(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _DRIVE_PROVIDERS, label="Google Drive")
        _token, creds, provider = await TokenManager.get_valid_creds(db, row)
        path = str(args.get("path") or "").strip()
        mime = str(args.get("mime_type") or "application/octet-stream")
        if args.get("content_base64"):
            try:
                body = base64.b64decode(str(args["content_base64"]))
            except Exception as exc:  # noqa: BLE001
                return {"error": f"invalid base64: {exc}"}
        elif args.get("content_text") is not None:
            body = str(args["content_text"]).encode("utf-8")
        else:
            return {"error": "either content_text or content_base64 is required"}
        return await upload_file(provider, creds, path, body, mime)

    @staticmethod
    async def _tool_drive_share_file(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _DRIVE_PROVIDERS, label="Google Drive")
        _token, creds, provider = await TokenManager.get_valid_creds(db, row)
        return await share_file(
            provider,
            creds,
            str(args["file_id"]),
            str(args["email"]),
            str(args.get("role") or "reader"),
        )

    @staticmethod
    async def _tool_sheets_read_range(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _SHEETS_PROVIDERS, label="Google Sheets")
        client = await _sheets_client(db, row)
        return await client.get_values(str(args["spreadsheet_id"]), str(args["range"]))

    @staticmethod
    async def _tool_sheets_append_row(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _SHEETS_PROVIDERS, label="Google Sheets")
        client = await _sheets_client(db, row)
        raw_vals = args.get("values")
        if not isinstance(raw_vals, list):
            return {"error": "values must be an array"}
        row_vals: list[Any] = list(raw_vals)
        return await client.append_row(
            str(args["spreadsheet_id"]),
            str(args["range"]),
            row_vals,
        )

    @staticmethod
    async def _tool_docs_get_document(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _DOCS_PROVIDERS, label="Google Docs")
        client = await _docs_client(db, row)
        return await client.get_document(str(args["document_id"]))

    # ------------------------------------------------------------------
    # YouTube, Tasks, People, iCloud CalDAV
    # ------------------------------------------------------------------
    @staticmethod
    async def _tool_youtube_list_my_channels(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _YOUTUBE_PROVIDERS, label="YouTube")
        client = await _youtube_client(db, row)
        return await client.list_my_channels(page_token=args.get("page_token"))

    @staticmethod
    async def _tool_youtube_search_videos(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _YOUTUBE_PROVIDERS, label="YouTube")
        cid = args.get("channel_id")
        q = args.get("q")
        if not cid and not q:
            return {"error": "pass channel_id and/or q"}
        client = await _youtube_client(db, row)
        return await client.search_videos(
            channel_id=str(cid) if cid else None,
            q=str(q) if q else None,
            page_token=args.get("page_token"),
            max_results=int(args.get("max_results") or 25),
        )

    @staticmethod
    async def _tool_youtube_get_video(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _YOUTUBE_PROVIDERS, label="YouTube")
        raw = args.get("video_id")
        if isinstance(raw, list):
            ids = [str(x).strip() for x in raw if str(x).strip()]
        else:
            ids = [s.strip() for s in str(raw or "").split(",") if s.strip()]
        if not ids:
            return {"error": "video_id required"}
        client = await _youtube_client(db, row)
        return await client.list_videos(ids)

    @staticmethod
    async def _tool_youtube_list_playlists(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _YOUTUBE_PROVIDERS, label="YouTube")
        cid = str(args.get("channel_id") or "").strip()
        if not cid:
            return {
                "error": "channel_id is required. Call youtube_list_my_channels first, then pass id.",
            }
        client = await _youtube_client(db, row)
        return await client.list_playlists(
            cid,
            page_token=args.get("page_token"),
            max_results=int(args.get("max_results") or 50),
        )

    @staticmethod
    async def _tool_youtube_list_playlist_items(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _YOUTUBE_PROVIDERS, label="YouTube")
        pid = str(args.get("playlist_id") or "").strip()
        if not pid:
            return {"error": "playlist_id is required (from youtube_list_playlists or channel contentDetails)."}
        client = await _youtube_client(db, row)
        return await client.list_playlist_items(
            pid,
            page_token=args.get("page_token"),
            max_results=int(args.get("max_results") or 50),
        )

    @staticmethod
    async def _tool_youtube_update_video(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _YOUTUBE_PROVIDERS, label="YouTube")
        client = await _youtube_client(db, row)
        tags = args.get("tags")
        tlist = [str(x) for x in tags] if isinstance(tags, list) else None
        return await client.update_video_snippet(
            str(args["video_id"]),
            title=str(args["title"]) if args.get("title") is not None else None,
            description=str(args["description"]) if args.get("description") is not None else None,
            tags=tlist,
            category_id=str(args["category_id"]) if args.get("category_id") is not None else None,
        )

    @staticmethod
    async def _tool_tasks_list_tasklists(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _TASKS_PROVIDERS, label="Google Tasks")
        client = await _tasks_client(db, row)
        return await client.list_tasklists(page_token=args.get("page_token"))

    @staticmethod
    async def _tool_tasks_list_tasks(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _TASKS_PROVIDERS, label="Google Tasks")
        client = await _tasks_client(db, row)
        sc = args.get("show_completed")
        return await client.list_tasks(
            str(args["tasklist_id"]),
            page_token=args.get("page_token"),
            show_completed=bool(sc) if sc is not None else None,
            due_min=args.get("due_min"),
            due_max=args.get("due_max"),
            max_results=int(args.get("max_results") or 100),
        )

    @staticmethod
    async def _tool_tasks_create_task(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _TASKS_PROVIDERS, label="Google Tasks")
        client = await _tasks_client(db, row)
        body: dict[str, Any] = {"title": str(args["title"])}
        if args.get("notes") is not None:
            body["notes"] = str(args["notes"])
        if args.get("due"):
            body["due"] = str(args["due"])
        return await client.insert_task(str(args["tasklist_id"]), body)

    @staticmethod
    async def _tool_tasks_update_task(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _TASKS_PROVIDERS, label="Google Tasks")
        client = await _tasks_client(db, row)
        body: dict[str, Any] = {}
        if args.get("title") is not None:
            body["title"] = str(args["title"])
        if args.get("notes") is not None:
            body["notes"] = str(args["notes"])
        if args.get("status"):
            body["status"] = str(args["status"])
        if args.get("due"):
            body["due"] = str(args["due"])
        return await client.patch_task(str(args["tasklist_id"]), str(args["task_id"]), body)

    @staticmethod
    async def _tool_tasks_delete_task(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _TASKS_PROVIDERS, label="Google Tasks")
        client = await _tasks_client(db, row)
        return await client.delete_task(str(args["tasklist_id"]), str(args["task_id"]))

    @staticmethod
    async def _tool_people_search_contacts(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _PEOPLE_PROVIDERS, label="Google Contacts")
        client = await _people_client(db, row)
        return await client.search_contacts(
            str(args["query"]),
            page_token=args.get("page_token"),
            page_size=int(args.get("page_size") or 20),
        )

    @staticmethod
    async def _tool_github_list_my_repos(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _GITHUB_PROVIDERS, label="GitHub")
        client = await _github_client(db, row)
        items = await client.list_user_repos(
            page=int(args.get("page") or 1),
            per_page=int(args.get("per_page") or 30),
        )
        return {"repos": items}

    @staticmethod
    async def _tool_github_list_repo_issues(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _GITHUB_PROVIDERS, label="GitHub")
        client = await _github_client(db, row)
        st = str(args.get("state") or "open")
        if st not in ("open", "closed", "all"):
            st = "open"
        items = await client.list_repo_issues(
            str(args["owner"]),
            str(args["repo"]),
            state=st,
            page=int(args.get("page") or 1),
            per_page=int(args.get("per_page") or 30),
        )
        return {"issues": items}

    @staticmethod
    async def _tool_slack_list_conversations(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _SLACK_PROVIDERS, label="Slack")
        client = await _slack_api_client(db, row)
        return await client.conversations_list(
            types=str(args.get("types") or "public_channel,private_channel"),
            cursor=args.get("cursor"),
            limit=int(args.get("limit") or 200),
        )

    @staticmethod
    async def _tool_slack_get_conversation_history(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _SLACK_PROVIDERS, label="Slack")
        client = await _slack_api_client(db, row)
        return await client.conversations_history(
            str(args["channel_id"]),
            limit=int(args.get("limit") or 50),
            cursor=args.get("cursor"),
        )

    @staticmethod
    async def _tool_linear_list_issues(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _LINEAR_PROVIDERS, label="Linear")
        client = await _linear_client(db, row)
        data = await client.list_issues(first=int(args.get("first") or 25))
        return data

    @staticmethod
    async def _tool_linear_get_issue(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _LINEAR_PROVIDERS, label="Linear")
        client = await _linear_client(db, row)
        return await client.get_issue(str(args["issue_id"]))

    @staticmethod
    async def _tool_notion_search(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _NOTION_PROVIDERS, label="Notion")
        client = await _notion_client(db, row)
        return await client.search(
            str(args.get("query") or ""),
            page_size=int(args.get("page_size") or 20),
        )

    @staticmethod
    async def _tool_notion_get_page(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _NOTION_PROVIDERS, label="Notion")
        client = await _notion_client(db, row)
        return await client.get_page(str(args["page_id"]))

    @staticmethod
    async def _tool_telegram_get_me(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _TELEGRAM_PROVIDERS, label="Telegram")
        client = await _telegram_client(db, row)
        return await client.get_me()

    @staticmethod
    async def _tool_telegram_get_updates(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _TELEGRAM_PROVIDERS, label="Telegram")
        client = await _telegram_client(db, row)
        off = args.get("offset")
        return await client.get_updates(
            offset=int(off) if off is not None else None,
            limit=int(args.get("limit") or 40),
        )

    @staticmethod
    async def _tool_discord_list_guilds(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _DISCORD_PROVIDERS, label="Discord")
        client = await _discord_client(db, row)
        guilds = await client.list_guilds()
        return {"guilds": guilds}

    @staticmethod
    async def _tool_discord_list_guild_channels(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _DISCORD_PROVIDERS, label="Discord")
        client = await _discord_client(db, row)
        ch = await client.list_guild_channels(str(args["guild_id"]))
        return {"channels": ch}

    @staticmethod
    async def _tool_discord_get_channel_messages(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _DISCORD_PROVIDERS, label="Discord")
        client = await _discord_client(db, row)
        msgs = await client.list_messages(
            str(args["channel_id"]),
            limit=int(args.get("limit") or 25),
        )
        return {"messages": msgs}

    @staticmethod
    async def _tool_device_list_ingested_files(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            "items": await DeviceIngestService.list_recent(
                db, user, limit=int(args.get("limit") or 50)
            )
        }

    @staticmethod
    async def _tool_device_get_ingested_file(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        return await DeviceIngestService.get_for_agent(
            db, user, int(args.get("ingest_id") or 0)
        )

    @staticmethod
    async def _tool_icloud_calendar_list_calendars(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _ICLOUD_CAL_PROVIDERS, label="iCloud Calendar")
        client = _icloud_caldav_client(row)
        return {"calendars": await client.list_calendars()}

    @staticmethod
    async def _tool_icloud_calendar_list_events(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        from datetime import date as date_cls

        row = await _resolve_connection(db, user, args, _ICLOUD_CAL_PROVIDERS, label="iCloud Calendar")
        client = _icloud_caldav_client(row)
        start_s = str(args.get("start_date") or "").strip()
        end_s = str(args.get("end_date") or "").strip()
        try:
            sd = date_cls.fromisoformat(start_s) if start_s else date_cls.today()
            ed = date_cls.fromisoformat(end_s) if end_s else sd
        except ValueError:
            return {"error": "start_date and end_date must be YYYY-MM-DD when provided"}
        events = await client.list_events(str(args["calendar_url"]), start=sd, end=ed)
        return {"events": events, "calendar_url": str(args["calendar_url"])}

    @staticmethod
    async def _tool_icloud_calendar_create_event(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _ICLOUD_CAL_PROVIDERS, label="iCloud Calendar")
        client = _icloud_caldav_client(row)
        start = datetime.fromisoformat(str(args["start_iso"]).replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(args["end_iso"]).replace("Z", "+00:00"))
        return await client.create_event(
            str(args["calendar_url"]),
            summary=str(args["summary"]),
            start=start,
            end=end,
            description=str(args["description"]) if args.get("description") else None,
        )

    @staticmethod
    async def _tool_icloud_drive_list_folder(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _ICLOUD_CAL_PROVIDERS, label="iCloud")
        uid, pw, china = _icloud_app_password_creds(row)
        if not uid or not pw.strip():
            return {"error": "missing Apple ID or password on this iCloud connection"}
        path = str(args.get("path") or "")
        try:
            return await asyncio.to_thread(
                list_folder_sync,
                uid,
                pw,
                connection_id=row.id,
                china_mainland=china,
                path=path,
            )
        except ICloudDriveError as exc:
            return {"error": exc.detail, "status_code": exc.status_code}

    @staticmethod
    async def _tool_icloud_drive_get_file(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _ICLOUD_CAL_PROVIDERS, label="iCloud")
        uid, pw, china = _icloud_app_password_creds(row)
        if not uid or not pw.strip():
            return {"error": "missing Apple ID or password on this iCloud connection"}
        fpath = str(args.get("path") or "").strip()
        if not fpath:
            return {"error": "path is required (slash-separated from Drive root, e.g. Documents/notes.txt)"}
        max_b = int(args.get("max_bytes") or DEFAULT_DOWNLOAD_MAX_BYTES)
        try:
            return await asyncio.to_thread(
                download_file_sync,
                uid,
                pw,
                connection_id=row.id,
                china_mainland=china,
                path=fpath,
                max_bytes=max_b,
            )
        except ICloudDriveError as exc:
            return {"error": exc.detail, "status_code": exc.status_code}

    @staticmethod
    async def _tool_icloud_contacts_list(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _ICLOUD_CAL_PROVIDERS, label="iCloud")
        uid, pw, china = _icloud_app_password_creds(row)
        if not uid or not pw.strip():
            return {"error": "missing Apple ID or password on this iCloud connection"}
        try:
            return await icloud_carddav_list_contacts(
                uid,
                pw,
                china_mainland=china,
                max_results=int(args.get("max_results") or 200),
            )
        except ICloudContactsError as exc:
            return {"error": exc.detail, "status_code": exc.status_code}

    @staticmethod
    async def _tool_icloud_contacts_search(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _ICLOUD_CAL_PROVIDERS, label="iCloud")
        uid, pw, china = _icloud_app_password_creds(row)
        if not uid or not pw.strip():
            return {"error": "missing Apple ID or password on this iCloud connection"}
        try:
            return await icloud_carddav_search_contacts(
                uid,
                pw,
                str(args.get("query") or ""),
                china_mainland=china,
                max_results=int(args.get("max_results") or 50),
            )
        except ICloudContactsError as exc:
            return {"error": exc.detail, "status_code": exc.status_code}

    @staticmethod
    async def _tool_icloud_reminders_list(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _ICLOUD_CAL_PROVIDERS, label="iCloud")
        uid, pw, china = _icloud_app_password_creds(row)
        if not uid or not pw.strip():
            return {"error": "missing Apple ID or password on this iCloud connection"}
        try:
            return await icloud_pyicloud_list_reminders(
                uid,
                pw,
                connection_id=row.id,
                china_mainland=china,
                max_lists=int(args.get("max_lists") or 20),
                max_reminders_per_list=int(args.get("max_reminders_per_list") or 50),
            )
        except ICloudDriveError as exc:
            return {"error": exc.detail, "status_code": exc.status_code}

    @staticmethod
    async def _tool_icloud_notes_list(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _ICLOUD_CAL_PROVIDERS, label="iCloud")
        uid, pw, china = _icloud_app_password_creds(row)
        if not uid or not pw.strip():
            return {"error": "missing Apple ID or password on this iCloud connection"}
        try:
            return await icloud_pyicloud_list_notes(
                uid,
                pw,
                connection_id=row.id,
                china_mainland=china,
                limit=int(args.get("limit") or 40),
            )
        except ICloudDriveError as exc:
            return {"error": exc.detail, "status_code": exc.status_code}

    @staticmethod
    async def _tool_icloud_photos_list(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _ICLOUD_CAL_PROVIDERS, label="iCloud")
        uid, pw, china = _icloud_app_password_creds(row)
        if not uid or not pw.strip():
            return {"error": "missing Apple ID or password on this iCloud connection"}
        try:
            return await icloud_pyicloud_list_photos(
                uid,
                pw,
                connection_id=row.id,
                china_mainland=china,
                max_albums=int(args.get("max_albums") or 8),
                max_photos_per_album=int(args.get("max_photos_per_album") or 25),
            )
        except ICloudDriveError as exc:
            return {"error": exc.detail, "status_code": exc.status_code}

    @staticmethod
    async def _tool_submit_whatsapp_credentials(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        return await submit_whatsapp_credentials_service(
            db,
            user,
            setup_token=str(args.get("setup_token") or ""),
            access_token=str(args.get("access_token") or ""),
            phone_number_id=str(args.get("phone_number_id") or ""),
            graph_api_version=args.get("graph_api_version"),
        )

    @staticmethod
    async def _tool_submit_github_credentials(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        return await submit_github_credentials_service(
            db,
            user,
            setup_token=str(args.get("setup_token") or ""),
            access_token=str(args.get("access_token") or ""),
        )

    @staticmethod
    async def _tool_submit_slack_credentials(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        return await submit_slack_credentials_service(
            db,
            user,
            setup_token=str(args.get("setup_token") or ""),
            bot_token=str(args.get("bot_token") or ""),
        )

    @staticmethod
    async def _tool_submit_linear_credentials(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        return await submit_linear_credentials_service(
            db,
            user,
            setup_token=str(args.get("setup_token") or ""),
            api_key=str(args.get("api_key") or ""),
        )

    @staticmethod
    async def _tool_submit_notion_credentials(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        return await submit_notion_credentials_service(
            db,
            user,
            setup_token=str(args.get("setup_token") or ""),
            api_key=str(args.get("api_key") or ""),
        )

    @staticmethod
    async def _tool_submit_telegram_bot_credentials(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        return await submit_telegram_bot_credentials_service(
            db,
            user,
            setup_token=str(args.get("setup_token") or ""),
            bot_token=str(args.get("bot_token") or ""),
        )

    @staticmethod
    async def _tool_submit_discord_bot_credentials(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        return await submit_discord_bot_credentials_service(
            db,
            user,
            setup_token=str(args.get("setup_token") or ""),
            bot_token=str(args.get("bot_token") or ""),
        )

    @staticmethod
    async def _tool_submit_icloud_caldav_credentials(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        return await submit_icloud_caldav_credentials_service(
            db,
            user,
            setup_token=str(args.get("setup_token") or ""),
            apple_id=str(args.get("apple_id") or ""),
            app_password=str(args.get("app_password") or ""),
            china_mainland=bool(args.get("china_mainland")),
        )

    # ------------------------------------------------------------------
    # Outlook + Teams tools
    # ------------------------------------------------------------------
    @staticmethod
    async def _tool_outlook_list_messages(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _OUTLOOK_PROVIDERS, label="Outlook")
        client = await _graph_client(db, row)
        return await client.messages_delta(top=int(args.get("top") or 25))

    @staticmethod
    async def _tool_outlook_get_message(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _OUTLOOK_PROVIDERS, label="Outlook")
        client = await _graph_client(db, row)
        return await client.get_message(str(args["message_id"]))

    @staticmethod
    async def _tool_teams_list_teams(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _TEAMS_PROVIDERS, label="Microsoft Teams")
        client = await _graph_client(db, row)
        return await client._get("/me/joinedTeams")

    @staticmethod
    async def _tool_teams_list_channels(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _TEAMS_PROVIDERS, label="Microsoft Teams")
        client = await _graph_client(db, row)
        return await client._get(f"/teams/{args['team_id']}/channels")

    @staticmethod
    async def _tool_teams_post_message(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        import httpx

        row = await _resolve_connection(db, user, args, _TEAMS_PROVIDERS, label="Microsoft Teams")
        token = await TokenManager.get_valid_access_token(db, row)
        url = (
            f"https://graph.microsoft.com/v1.0/teams/{args['team_id']}"
            f"/channels/{args['channel_id']}/messages"
        )
        body = {"body": {"contentType": "html", "content": str(args.get("body") or "")}}
        async with httpx.AsyncClient(timeout=30.0) as http:
            r = await http.post(url, headers={"Authorization": f"Bearer {token}"}, json=body)
        if r.status_code >= 300:
            return {"ok": False, "status": r.status_code, "detail": r.text[:500]}
        return {"ok": True, "result": r.json()}

    # ------------------------------------------------------------------
    # Memory + skills tools
    # ------------------------------------------------------------------
    @staticmethod
    async def _tool_upsert_memory(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        """Persist scratchpad memory; return structured errors instead of raising when args are bad.

        The model sees ``{"error": ...}`` in the tool channel — phrases like "problema técnico con
        la memoria" usually mean this path returned an error dict (DB issue, missing fields, etc.).
        """
        if not isinstance(args, dict):
            return {"error": "invalid_arguments", "detail": "expected a JSON object of arguments"}
        rk = args.get("key")
        rc = args.get("content")
        if rk is None or rc is None:
            return {
                "error": "missing_fields",
                "detail": "Provide non-empty 'key' and 'content' (strings).",
            }
        key = str(rk).strip()
        content = str(rc).strip()
        if not key or not content:
            return {
                "error": "empty_key_or_content",
                "detail": "key and content must be non-empty after trimming.",
            }
        imp = 0
        if args.get("importance") is not None:
            try:
                imp = max(0, min(10, int(args["importance"])))
            except (TypeError, ValueError):
                imp = 0
        tags_arg = args.get("tags")
        tags: list[str] | None = None
        if isinstance(tags_arg, list):
            tags = [str(x).strip() for x in tags_arg if str(x).strip()][:50] or None

        try:
            row = await AgentMemoryService.upsert(
                db,
                user,
                key=key,
                content=content,
                importance=imp,
                tags=tags,
            )
        except Exception as exc:  # noqa: BLE001 — surface a clear payload to the model + ops logs
            _logger_memory_tools.exception(
                "upsert_memory persist_failed user_id=%s key_prefix=%s",
                user.id,
                key[:80],
            )
            return {
                "error": "persist_failed",
                "detail": str(exc)[:400],
            }
        return {"ok": True, "key": row.key, "id": row.id}

    @staticmethod
    async def _tool_delete_memory(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        ok = await AgentMemoryService.delete(db, user, key=str(args["key"]))
        return {"ok": ok}

    @staticmethod
    async def _tool_list_memory(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        rows = await AgentMemoryService.list_for_user(
            db, user, limit=int(args.get("limit") or 50)
        )
        return {
            "memories": [
                {
                    "key": r.key,
                    "content": r.content,
                    "importance": r.importance or 0,
                    "tags": r.tags,
                    "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                }
                for r in rows
            ]
        }

    @staticmethod
    async def _tool_recall_memory(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        hits = await AgentMemoryService.recall(
            db,
            user,
            query=(args.get("query") or None),
            tags=args.get("tags"),
            limit=int(args.get("limit") or 6),
        )
        return {"hits": hits}

    @staticmethod
    async def _tool_memory_get(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        key = str(args.get("key") or "").strip()
        if not key:
            return {"ok": False, "error": "key is required"}
        row = await AgentMemoryService.get(db, user, key=key)
        if not row:
            return {"ok": False, "error": "not_found", "key": key}
        return {
            "ok": True,
            "key": row.key,
            "content": row.content,
            "importance": row.importance or 0,
            "tags": row.tags,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    @staticmethod
    async def _tool_list_skills(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        del db, user, args
        return {
            "skills": [
                {"slug": s.slug, "title": s.title, "summary": s.summary}
                for s in _list_skills()
            ]
        }

    @staticmethod
    async def _tool_load_skill(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        del db, user
        s = _load_skill(str(args.get("slug") or ""))
        if not s:
            return {"found": False}
        return {
            "found": True,
            "slug": s.slug,
            "title": s.title,
            "summary": s.summary,
            "body": s.body,
            "metadata": s.metadata,
        }

    @staticmethod
    async def _tool_list_workspace_files(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        del db, user, args
        files = list_allowed_workspace_files(skills_root=_skills_dir())
        return {"files": files}

    @staticmethod
    async def _tool_read_workspace_file(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        del db, user
        path = str(args.get("path") or "")
        raw = read_allowed_workspace_file(path, skills_root=_skills_dir())
        if raw is None:
            return {"error": "file_not_found_or_not_allowed", "path": path}
        return {"path": path, "content": raw}

    @staticmethod
    async def _tool_describe_harness(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        del args
        from app.services.capability_registry import describe_capabilities

        prefs = await UserAISettingsService.get_or_create(db, user)
        rt = await resolve_for_user(db, user)
        provs = await linked_connector_providers(db, user.id)
        palette = await resolve_turn_tool_palette(db, user)
        hbm = max(1, min(60, int(getattr(settings, "agent_heartbeat_minutes", 15) or 15)))
        minute_marks = sorted({m for m in range(0, 60, hbm)})

        return {
            "harness": "agent-aquila",
            "harness_mode_configured": coerce_harness_mode(prefs),
            "tool_palette_mode": rt.agent_tool_palette,
            "tool_count_this_turn": len(palette),
            "tool_names_sample": [t["function"]["name"] for t in palette[:40]],
            "linked_connector_providers": provs,
            "agent_max_tool_steps": rt.agent_max_tool_steps,
            "prompt_tier": rt.agent_prompt_tier,
            "connector_gated_tools": rt.agent_connector_gated_tools,
            "agent_processing_paused": bool(getattr(prefs, "agent_processing_paused", False)),
            "capabilities": describe_capabilities(),
            "web_tools": {
                "enabled": bool(settings.web_search_enabled),
                "provider": (settings.web_search_provider or "duckduckgo").strip().lower(),
                "default_max_results": int(settings.web_search_max_results or 8),
                "fetch_max_chars": int(settings.web_fetch_max_chars or 12000),
            },
            "background_automation": {
                "heartbeat": {
                    "server_master_enabled": bool(settings.agent_heartbeat_enabled),
                    "worker_cron_fires_at_minute_marks_each_hour": minute_marks,
                    "worker_uses_instance_env_heartbeat_minutes": hbm,
                    "per_user_heartbeat_enabled": bool(rt.agent_heartbeat_enabled),
                    "per_user_check_gmail_on_heartbeat": bool(rt.agent_heartbeat_check_gmail),
                    "per_user_heartbeat_burst_per_hour": int(rt.agent_heartbeat_burst_per_hour),
                },
                "how_it_works": (
                    "When the ARQ worker and Redis are running and the instance has "
                    "AGENT_HEARTBEAT_ENABLED=true, the worker wakes the agent on a cron that fires "
                    "at the listed minute marks every hour. Each participating user (heartbeat "
                    "enabled in AI settings) gets a background turn that can use tools — e.g. Gmail "
                    "when 'Check Gmail on heartbeat' is on. It is not a single 'once daily at 9:30' "
                    "product toggle; exact wall-clock scheduling may need deployment tuning. "
                    "Gmail watch / Pub/Sub push (event-driven) is optional in some installs — see "
                    "docs. Outbound email still requires user approval; reads and digests are fine."
                ),
            },
        }

    # ------------------------------------------------------------------
    # Connector helpers
    # ------------------------------------------------------------------
    @staticmethod
    async def _tool_list_connectors(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        del args
        from app.services.connector_service import ConnectorService

        rows = await ConnectorService.list_connections(db, user)
        return {
            "connectors": [
                {
                    "id": ConnectorService.to_read(c).id,
                    "provider": c.provider,
                    "label": c.label,
                    "needs_reauth": ConnectorService.to_read(c).needs_reauth,
                    "missing_scopes": ConnectorService.to_read(c).missing_scopes,
                }
                for c in rows
            ]
        }

    @staticmethod
    async def _tool_get_session_time(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        del args
        prefs = await UserAISettingsService.get_or_create(db, user)
        return session_time_result(
            user_timezone=getattr(prefs, "user_timezone", None),
            time_format=getattr(prefs, "time_format", None) or "auto",
        )

    @staticmethod
    async def _tool_web_search(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        del db, user
        if not bool(settings.web_search_enabled):
            return {"error": "web_search is disabled by server config"}
        query = str(args.get("query") or "").strip()
        if not query:
            return {"error": "query is required"}
        max_results = min(
            max(int(args.get("max_results") or settings.web_search_max_results or 8), 1),
            20,
        )
        client = WebSearchClient()
        return await client.search(query, max_results=max_results)

    @staticmethod
    async def _tool_web_fetch(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        del db, user
        if not bool(settings.web_search_enabled):
            return {"error": "web_search/web_fetch is disabled by server config"}
        url = str(args.get("url") or "").strip()
        if not url:
            return {"error": "url is required"}
        max_chars_raw = args.get("max_chars")
        max_chars = int(max_chars_raw) if max_chars_raw is not None else None
        client = WebSearchClient()
        return await client.fetch_url(url, max_chars=max_chars)

    @staticmethod
    async def _tool_start_connector_setup(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        from app.services.connector_setup_service import start_setup

        return await start_setup(db, user, str(args.get("provider") or ""))

    @staticmethod
    async def _tool_submit_connector_credentials(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        from app.services.connector_setup_service import submit_credentials

        token = str(args.get("setup_token") or "").strip()
        cid = str(args.get("client_id") or "").strip()
        secret = str(args.get("client_secret") or "").strip()
        if not (token and cid and secret):
            return {"error": "setup_token, client_id and client_secret are required"}
        return await submit_credentials(
            db,
            user,
            setup_token=token,
            client_id=cid,
            client_secret=secret,
            redirect_uri=args.get("redirect_uri"),
            tenant=args.get("tenant"),
        )

    @staticmethod
    async def _tool_start_oauth_flow(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        from app.services.connector_setup_service import start_oauth

        return await start_oauth(
            db,
            user,
            provider=str(args.get("provider") or ""),
            service=str(args.get("service") or "all"),
        )

    # ------------------------------------------------------------------
    # Proposal tools (email / WhatsApp / YouTube upload — human approval)
    # ------------------------------------------------------------------
    @staticmethod
    async def _insert_proposal(
        db: AsyncSession,
        user: User,
        run_id: int,
        kind: str,
        payload: dict[str, Any],
        summary: str,
        *,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        ikey = (idempotency_key or "").strip()[:128] or None
        if ikey:
            r = await db.execute(
                select(PendingProposal).where(
                    PendingProposal.user_id == user.id,
                    PendingProposal.idempotency_key == ikey,
                    PendingProposal.status == "pending",
                )
            )
            existing = r.scalar_one_or_none()
            if existing:
                return {
                    "proposal_id": existing.id,
                    "kind": existing.kind,
                    "status": "pending",
                    "deduplicated": True,
                    "message": "Existing pending operation with the same idempotency key.",
                }
        prop = PendingProposal(
            user_id=user.id,
            run_id=run_id,
            idempotency_key=ikey,
            kind=kind,
            summary=summary[:500] if summary else None,
            status="pending",
            payload=payload,
        )
        db.add(prop)
        await db.flush()
        return {
            "proposal_id": prop.id,
            "kind": kind,
            "status": "pending",
            "message": "Proposal recorded. The user must approve it before it is executed.",
        }

    @staticmethod
    def _idem(args: dict[str, Any]) -> str | None:
        raw = args.get("idempotency_key")
        return str(raw).strip()[:128] if raw is not None and str(raw).strip() else None

    @staticmethod
    async def _tool_propose_email_send(
        db: AsyncSession, user: User, run_id: int, args: dict[str, Any]
    ) -> dict[str, Any]:
        to_raw = args["to"]
        to_list = to_raw if isinstance(to_raw, list) else [str(to_raw)]
        payload = {
            "connection_id": int(args["connection_id"]),
            "to": [str(x) for x in to_list],
            "subject": str(args["subject"])[:998],
            "body": str(args["body"]),
            "content_type": str(args.get("content_type") or "text"),
        }
        return await AgentService._insert_proposal(
            db,
            user,
            run_id,
            "email_send",
            payload,
            f"Send email: {payload['subject'][:80]}",
            idempotency_key=AgentService._idem(args),
        )

    @staticmethod
    async def _tool_propose_email_reply(
        db: AsyncSession, user: User, run_id: int, args: dict[str, Any]
    ) -> dict[str, Any]:
        thread_id = str(args.get("thread_id") or "").strip()
        if not thread_id:
            return {"error": "thread_id required"}
        to_raw = args.get("to")
        to_list: list[str] | None = None
        if to_raw:
            to_list = to_raw if isinstance(to_raw, list) else [str(to_raw)]
        # If 'to' is omitted we leave it for the executor to derive from
        # the live thread headers; we no longer have a local Email mirror
        # to look up the last inbound sender, so the agent SHOULD include
        # ``to`` (or call ``gmail_get_thread`` first to discover it).
        if not to_list:
            return {
                "error": "no `to` provided. Call gmail_get_thread first and pass the sender as `to`."
            }
        payload = {
            "connection_id": int(args["connection_id"]),
            "to": [str(x) for x in to_list],
            "subject": str(args.get("subject") or "")[:998],
            "body": str(args["body"]),
            "content_type": str(args.get("content_type") or "text"),
            "thread_id": thread_id,
            "in_reply_to": args.get("in_reply_to"),
        }
        return await AgentService._insert_proposal(
            db,
            user,
            run_id,
            "email_reply",
            payload,
            f"Reply in thread: {payload['subject'][:80] or thread_id}",
            idempotency_key=AgentService._idem(args),
        )

    @staticmethod
    async def _tool_propose_whatsapp_send(
        db: AsyncSession, user: User, run_id: int, args: dict[str, Any]
    ) -> dict[str, Any]:
        to_e164 = str(args.get("to_e164") or "").strip()
        if not to_e164:
            return {"error": "to_e164 is required (E.164, e.g. +34600111222)."}
        tname = (args.get("template_name") or "").strip() or None
        tlang = str(args.get("template_language") or "en")
        body = str(args.get("body") or "")
        if not tname and not body.strip():
            return {
                "error": "Provide `body` for session text, or `template_name` for outside the 24h window.",
            }
        payload = {
            "connection_id": int(args["connection_id"]),
            "to_e164": to_e164,
            "body": body if not tname else "",
            "template_name": tname,
            "template_language": tlang,
        }
        return await AgentService._insert_proposal(
            db,
            user,
            run_id,
            "whatsapp_send",
            payload,
            f"WhatsApp → {to_e164[:40]}",
            idempotency_key=AgentService._idem(args),
        )

    @staticmethod
    async def _tool_propose_youtube_upload(
        db: AsyncSession, user: User, run_id: int, args: dict[str, Any]
    ) -> dict[str, Any]:
        b64 = str(args.get("content_base64") or "")
        try:
            raw = base64.b64decode(b64, validate=True)
        except Exception as exc:  # noqa: BLE001
            return {"error": f"Invalid base64: {exc}"}
        max_bytes = 12 * 1024 * 1024
        if len(raw) > max_bytes:
            return {"error": f"Decoded file exceeds {max_bytes} bytes."}
        payload = {
            "connection_id": int(args["connection_id"]),
            "title": str(args.get("title") or "")[:100],
            "description": str(args.get("description") or "")[:5000],
            "content_base64": b64,
            "mime_type": str(args.get("mime_type") or "video/mp4"),
            "privacy_status": str(args.get("privacy_status") or "private"),
        }
        if not payload["title"].strip():
            return {"error": "title is required."}
        return await AgentService._insert_proposal(
            db,
            user,
            run_id,
            "youtube_upload",
            payload,
            f"YouTube upload: {payload['title'][:60]}",
            idempotency_key=AgentService._idem(args),
        )

    @staticmethod
    async def _tool_propose_slack_post_message(
        db: AsyncSession, user: User, run_id: int, args: dict[str, Any]
    ) -> dict[str, Any]:
        channel = str(args.get("channel_id") or "").strip()
        if not channel:
            return {"error": "channel_id is required (from slack_list_conversations)"}
        text = str(args.get("text") or "").strip()
        if not text:
            return {"error": "text is required"}
        payload: dict[str, Any] = {
            "connection_id": int(args["connection_id"]),
            "channel_id": channel,
            "text": text[:4000],
        }
        if args.get("thread_ts"):
            payload["thread_ts"] = str(args["thread_ts"]).strip()
        return await AgentService._insert_proposal(
            db,
            user,
            run_id,
            "slack_post",
            payload,
            f"Slack post → {channel[:40]}",
            idempotency_key=AgentService._idem(args),
        )

    @staticmethod
    async def _tool_propose_linear_create_comment(
        db: AsyncSession, user: User, run_id: int, args: dict[str, Any]
    ) -> dict[str, Any]:
        iid = str(args.get("issue_id") or "").strip()
        if not iid:
            return {"error": "issue_id is required"}
        body = str(args.get("body") or "").strip()
        if not body:
            return {"error": "body is required"}
        payload = {
            "connection_id": int(args["connection_id"]),
            "issue_id": iid,
            "body": body[:20000],
        }
        return await AgentService._insert_proposal(
            db,
            user,
            run_id,
            "linear_comment",
            payload,
            f"Linear comment → {iid[:40]}",
            idempotency_key=AgentService._idem(args),
        )

    @staticmethod
    async def _tool_propose_telegram_send_message(
        db: AsyncSession, user: User, run_id: int, args: dict[str, Any]
    ) -> dict[str, Any]:
        text = str(args.get("text") or "").strip()
        if not text:
            return {"error": "text is required"}
        cid = args.get("chat_id")
        if cid is None:
            return {"error": "chat_id is required"}
        payload = {
            "connection_id": int(args["connection_id"]),
            "chat_id": cid,
            "text": text[:4096],
        }
        return await AgentService._insert_proposal(
            db,
            user,
            run_id,
            "telegram_message",
            payload,
            f"Telegram → {str(cid)[:40]}",
            idempotency_key=AgentService._idem(args),
        )

    @staticmethod
    async def _tool_propose_discord_post_message(
        db: AsyncSession, user: User, run_id: int, args: dict[str, Any]
    ) -> dict[str, Any]:
        channel = str(args.get("channel_id") or "").strip()
        content = str(args.get("content") or "").strip()
        if not channel or not content:
            return {"error": "channel_id and content are required"}
        payload = {
            "connection_id": int(args["connection_id"]),
            "channel_id": channel,
            "content": content[:2000],
        }
        return await AgentService._insert_proposal(
            db,
            user,
            run_id,
            "discord_message",
            payload,
            f"Discord → {channel[:40]}",
            idempotency_key=AgentService._idem(args),
        )

    # ------------------------------------------------------------------
    # Tool dispatch — single source of truth for routing model-issued
    # tool calls to the matching internal handler.
    # ------------------------------------------------------------------

    _DISPATCH = AGENT_TOOL_DISPATCH

    @staticmethod
    async def _dispatch_tool(
        db: AsyncSession,
        user: User,
        run_id: int,
        thread_id: int | None,
        call: ChatToolCall,
    ) -> tuple[dict[str, Any], PendingProposal | None]:
        """Execute one model-issued tool call.

        Returns ``(result_dict, pending_proposal_or_None)``. The result is
        what we feed back to the model and persist as the tool step.
        """
        del thread_id  # not needed in the OpenClaw dispatcher (no auto-apply CRM)
        tool_name = call.name or ""
        args = call.arguments if isinstance(call.arguments, dict) else {}

        if tool_name not in AGENT_TOOL_NAMES:
            return ({"error": f"unknown tool {tool_name!r}"}, None)

        replay = _replay_ctx.get()
        if replay is not None:
            result = replay.next_tool_result()
            prop_id = result.get("proposal_id") if isinstance(result, dict) else None
            if prop_id:
                prop = await db.get(PendingProposal, int(prop_id))
                return (result, prop)
            return (result, None)

        entry = AgentService._DISPATCH.get(tool_name)
        if entry is None:
            return ({"error": f"unhandled tool: {tool_name}"}, None)
        handler_name, takes_run_id = entry
        handler = getattr(AgentService, handler_name)

        try:
            if takes_run_id:
                result = await handler(db, user, run_id, args)
            else:
                result = await handler(db, user, args)
        except ConnectorNeedsReauth as exc:
            return (
                {
                    "error": "connector_needs_reauth",
                    "connection_id": exc.connection_id,
                    "provider": exc.provider,
                    "message": str(exc),
                },
                None,
            )
        except OAuthError as exc:
            return ({"error": f"oauth_error: {exc}"}, None)
        except (
            GmailAPIError,
            CalendarAPIError,
            DriveAPIError,
            GraphAPIError,
            YoutubeAPIError,
            WhatsAppAPIError,
            GoogleTasksAPIError,
            GooglePeopleAPIError,
            GoogleSheetsAPIError,
            GoogleDocsAPIError,
            ICloudCalDAVError,
            GitHubAPIError,
            SlackAPIError,
            LinearAPIError,
            NotionAPIError,
            TelegramAPIError,
            DiscordAPIError,
            WebSearchAPIError,
        ) as exc:
            return ({"error": f"upstream {exc.status_code}: {exc.detail[:300]}"}, None)
        except Exception as exc:  # noqa: BLE001 — surface tool errors to the model
            return ({"error": str(exc)[:500]}, None)

        prop_id = result.get("proposal_id") if isinstance(result, dict) else None
        if prop_id:
            prop = await db.get(PendingProposal, int(prop_id))
            return (result, prop)
        return (result, None)

    # ------------------------------------------------------------------
    # Memory flush (OpenClaw-style, before thread compaction)
    # ------------------------------------------------------------------
    @staticmethod
    async def run_memory_flush_turn(
        db: AsyncSession,
        user: User,
        *,
        thread_id: int,
        dropped_messages: list[dict[str, str]],
    ) -> None:
        """Persist facts from chat turns that are about to be dropped from context."""
        rt = await resolve_for_user(db, user)
        if not dropped_messages or not rt.agent_memory_flush_enabled:
            return
        settings_row = await UserAISettingsService.get_or_create(db, user)
        if getattr(settings_row, "agent_processing_paused", False) or settings_row.ai_disabled:
            return
        api_key = await UserAISettingsService.get_api_key(db, user)
        if provider_kind_requires_api_key(settings_row.provider_kind) and not api_key:
            return
        lines: list[str] = []
        for m in dropped_messages:
            role = str(m.get("role") or "user")
            content = str(m.get("content") or "")
            if len(content) > 8000:
                content = content[:7997] + "…"
            lines.append(f"{role.upper()}: {content}")
        transcript = "\n\n".join(lines)
        max_c = rt.agent_memory_flush_max_transcript_chars
        if len(transcript) > max_c:
            transcript = transcript[: max_c - 20] + "\n…[truncated]"
        root_trace = new_trace_id()
        run = AgentRun(
            user_id=user.id,
            status="running",
            user_message=(
                "[memory_flush] The following turns will be omitted from chat context — "
                "persist important facts with upsert_memory.\n\n" + transcript
            ),
            root_trace_id=root_trace,
            chat_thread_id=thread_id,
            turn_profile="memory_flush",
        )
        db.add(run)
        await db.flush()
        harness_pref = getattr(settings_row, "harness_mode", None) or "auto"
        effective = resolve_effective_mode(
            harness_pref, settings_row.provider_kind, settings_row.chat_model
        )
        palette = memory_flush_tools()
        system_prompt = await build_memory_flush_system_prompt(
            db,
            user,
            tool_palette=palette,
            harness_mode=effective,
            user_timezone=getattr(settings_row, "user_timezone", None),
            time_format=normalize_time_format(getattr(settings_row, "time_format", None)),
            prompt_tier="minimal",
            runtime=rt,
        )
        await AgentService._execute_agent_loop(
            db,
            user,
            run,
            prior_messages=None,
            thread_context_hint=None,
            replay=None,
            tool_palette_override=palette,
            system_prompt_override=system_prompt,
            max_tool_steps_override=rt.agent_memory_flush_max_steps,
        )

    # ------------------------------------------------------------------
    # ReAct loop
    # ------------------------------------------------------------------
    @staticmethod
    async def run_agent_invalid_preflight(
        db: AsyncSession,
        user: User,
        message: str,
        *,
        thread_id: int | None = None,
    ) -> AgentRunRead | None:
        settings_row = await UserAISettingsService.get_or_create(db, user)
        if getattr(settings_row, "agent_processing_paused", False):
            run = AgentRun(
                user_id=user.id,
                status="failed",
                user_message=message,
                error="The agent is paused. Resume it from the dashboard (Settings).",
                chat_thread_id=thread_id,
            )
            db.add(run)
            await db.commit()
            await db.refresh(run)
            return AgentService._to_read(run, [], [])
        if settings_row.ai_disabled:
            run = AgentRun(
                user_id=user.id,
                status="failed",
                user_message=message,
                error="AI is disabled for this user",
                chat_thread_id=thread_id,
            )
            db.add(run)
            await db.commit()
            await db.refresh(run)
            return AgentService._to_read(run, [], [])

        api_key = await UserAISettingsService.get_api_key(db, user)
        if provider_kind_requires_api_key(settings_row.provider_kind) and not api_key:
            run = AgentRun(
                user_id=user.id,
                status="failed",
                user_message=message,
                error="API key not configured",
                chat_thread_id=thread_id,
            )
            db.add(run)
            await db.commit()
            await db.refresh(run)
            return AgentService._to_read(run, [], [])
        return None

    @staticmethod
    async def abort_pending_run_queue_unavailable(
        db: AsyncSession,
        *,
        run: AgentRun,
        placeholder_message: ChatMessage,
    ) -> AgentRunRead:
        """The worker queue could not take this run — never run the LLM in the HTTP handler.

        OpenClaw-style: agent turns are processed out-of-band. A failed enqueue means the
        infrastructure is down or misconfigured; we surface a clear system row instead
        of blocking the request (and tripping Next.js / reverse-proxy timeouts) or leaving
        a ``…`` placeholder row up forever.
        """
        err = (
            "Could not start the assistant: the job queue is unavailable. "
            "Ensure Redis and the ARQ worker are running and REDIS_URL is set."
        )
        run.status = "failed"
        run.error = err
        placeholder_message.role = "system"
        placeholder_message.content = err
        await db.commit()
        await db.refresh(run)
        await db.refresh(placeholder_message)
        return AgentService._to_read(run, [], [])

    @staticmethod
    async def create_pending_agent_run(
        db: AsyncSession,
        user: User,
        message: str,
        *,
        thread_id: int | None = None,
        turn_profile: str = TURN_PROFILE_USER_CHAT,
    ) -> AgentRun:
        root_trace = new_trace_id()
        run = AgentRun(
            user_id=user.id,
            status="pending",
            user_message=message,
            root_trace_id=root_trace,
            chat_thread_id=thread_id,
            turn_profile=normalize_turn_profile(turn_profile),
        )
        db.add(run)
        await db.flush()
        return run

    @staticmethod
    async def run_agent(
        db: AsyncSession,
        user: User,
        message: str,
        *,
        prior_messages: list[dict[str, str]] | None = None,
        thread_id: int | None = None,
        thread_context_hint: str | None = None,
        replay: AgentReplayContext | None = None,
        turn_profile: str | None = None,
    ) -> AgentRunRead:
        """Run one agent turn.

        ``prior_messages``: optional ``[{role, content}, ...]`` of previous user/assistant
          turns from the same chat thread (so multi-turn conversations are coherent).
        ``thread_id``: persisted on AgentRun so executed actions / proposals can route
          their inline cards back into the right chat thread.
        ``thread_context_hint``: a short system-injected context blurb such as
          ``"Conversation about thread #42"``.
        ``replay``: when set, non-``final_answer`` tools consume scripted results from
          :class:`~app.services.agent_replay.AgentReplayContext` (regression tests).
        ``turn_profile``: harness kind (``user_chat``, ``channel_inbound``, ``heartbeat``, etc.).
        """
        early = await AgentService.run_agent_invalid_preflight(db, user, message, thread_id=thread_id)
        if early is not None:
            return early

        root_trace = new_trace_id()
        tpf = normalize_turn_profile(turn_profile)
        run = AgentRun(
            user_id=user.id,
            status="running",
            user_message=message,
            root_trace_id=root_trace,
            chat_thread_id=thread_id,
            turn_profile=tpf,
        )
        db.add(run)
        await db.flush()
        return await AgentService._execute_agent_loop(
            db,
            user,
            run,
            prior_messages=prior_messages,
            thread_context_hint=thread_context_hint,
            replay=replay,
        )

    @staticmethod
    async def _execute_agent_loop(
        db: AsyncSession,
        user: User,
        run: AgentRun,
        *,
        prior_messages: list[dict[str, str]] | None = None,
        thread_context_hint: str | None = None,
        replay: AgentReplayContext | None = None,
        tool_palette_override: list[dict[str, Any]] | None = None,
        system_prompt_override: str | None = None,
        max_tool_steps_override: int | None = None,
    ) -> AgentRunRead:
        message = run.user_message
        thread_id = run.chat_thread_id
        settings_row = await UserAISettingsService.get_or_create(db, user)
        rt = await resolve_for_user(db, user)
        api_key = await UserAISettingsService.get_api_key(db, user)
        tp = normalize_turn_profile(getattr(run, "turn_profile", None) or TURN_PROFILE_USER_CHAT)
        eff_max = resolve_max_tool_steps_for_turn(rt, tp)
        if max_tool_steps_override is not None:
            eff_max = int(max_tool_steps_override)
        turn_tools = (
            tool_palette_override
            if tool_palette_override is not None
            else await resolve_turn_tool_palette(db, user, turn_profile=tp)
        )
        user_ctx_block = await injectable_user_context_section(
            db,
            user,
            settings_row=settings_row,
            turn_profile=tp,
            inject_in_chat=rt.agent_inject_user_context_in_chat,
        )
        harness_pref = getattr(settings_row, "harness_mode", None) or "auto"
        effective = resolve_effective_mode(
            harness_pref, settings_row.provider_kind, settings_row.chat_model
        )
        allow_native_fallback = effective == "native"

        root_trace = run.root_trace_id or new_trace_id()
        if run.root_trace_id is None:
            run.root_trace_id = root_trace
        root_span = new_span_id()

        await emit_trace_event(
            db,
            run_id=run.id,
            event_type=EV_RUN_STARTED,
            trace_id=root_trace,
            span_id=root_span,
            payload={
                "schema": "agent_trace.v1",
                "user_message_sha256": content_sha256_preview(message),
                "thread_id": thread_id,
                "tool_palette_size": len(turn_tools),
                "harness_mode_effective": effective,
                "replay": replay is not None,
                "memory_flush": tool_palette_override is not None,
                "turn_profile": tp,
                "max_tool_steps_effective": eff_max,
            },
        )

        async def _assemble_system(harness_mode: object) -> str:
            return await build_system_prompt(
                db,
                user,
                tool_palette=turn_tools,
                harness_mode=harness_mode,  # type: ignore[arg-type]
                thread_context_hint=thread_context_hint,
                user_timezone=getattr(settings_row, "user_timezone", None),
                time_format=normalize_time_format(getattr(settings_row, "time_format", None)),
                prompt_tier=rt.agent_prompt_tier,
                agent_processing_paused=bool(getattr(settings_row, "agent_processing_paused", False)),
                runtime=rt,
                turn_profile=tp,
                injected_user_context=user_ctx_block,
                max_tool_steps_effective=eff_max,
            )

        if system_prompt_override is not None:
            system_prompt = system_prompt_override
        else:
            system_prompt = await _assemble_system(effective)
        conversation: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt}
        ]
        if prior_messages:
            conversation.extend(
                [
                    {"role": str(m.get("role") or "user"), "content": str(m.get("content") or "")}
                    for m in prior_messages
                    if m.get("content")
                ]
            )
        conversation.append({"role": "user", "content": message})

        if heuristic_wants_post_turn_extraction(message, ""):
            conversation[0] = {
                "role": "system",
                "content": (conversation[0].get("content") or "")
                + _IDENTITY_AND_MEMORY_TOOL_NUDGE,
            }

        model_limits = await resolve_model_limits(
            api_key=api_key or "",
            settings_row=settings_row,
            model=settings_row.chat_model,
        )
        budget = plan_budget(messages=conversation, limits=model_limits)
        if rt.context_budget_v2 and budget.compacted:
            conversation, _ = _reduce_conversation_for_budget(
                conversation, input_budget_tokens=budget.input_budget
            )
            budget = plan_budget(messages=conversation, limits=model_limits)

        step_idx = 0
        proposals_created: list[PendingProposal] = []
        if thread_id is not None:
            db.add(
                AgentRunStep(
                    run_id=run.id,
                    step_index=0,
                    kind="meta",
                    name="thread",
                    payload={"thread_id": int(thread_id)},
                )
            )

        _replay_token = None
        if replay is not None:
            _replay_token = _replay_ctx.set(replay)

        try:
            final_answer_text: str | None = None
            max_steps = eff_max
            overflow_retried = False
            empty_gmail_search_streak = 0
            empty_gmail_queries: list[str] = []
            for _ in range(max_steps):
                parse_errors: list[str] = []
                llm_span = new_span_id()
                await emit_trace_event(
                    db,
                    run_id=run.id,
                    event_type=EV_LLM_REQUEST,
                    trace_id=root_trace,
                    span_id=llm_span,
                    parent_span_id=root_span,
                    payload={
                        "approx_prompt_tokens": _approx_prompt_tokens(conversation),
                        "estimated_prompt_tokens": estimate_message_tokens(conversation),
                        "input_budget_tokens": budget.input_budget,
                        "reserved_output_tokens": budget.reserved_output_tokens,
                        "tool_defs_count": len(turn_tools),
                        "harness_mode": effective,
                        "turn_profile": tp,
                        "max_tool_steps_effective": eff_max,
                    },
                )
                _llm_t0 = time.monotonic()
                try:
                    if effective == "native":
                        response = await chat_turn_native(
                            api_key or "",
                            settings_row,
                            messages=conversation,
                            tools=turn_tools,
                            temperature=0.15,
                            max_tokens=budget.reserved_output_tokens if rt.context_budget_v2 else None,
                        )
                    else:
                        raw_text, finish_reason, raw_msg, usage_cf = await LLMClient.chat_completion_full(
                            api_key or "",
                            settings_row,
                            messages=conversation,
                            temperature=0.15,
                            max_tokens=budget.reserved_output_tokens if rt.context_budget_v2 else None,
                        )
                        calls, parse_errors = parse_tool_calls_from_content(raw_text)
                        response = ChatResponse(
                            content=raw_text,
                            tool_calls=calls,
                            raw_message=raw_msg,
                            finish_reason=finish_reason,
                            usage=usage_cf,
                        )
                except LLMProviderError as exc:
                    if rt.context_budget_v2 and _is_context_overflow(exc) and not overflow_retried:
                        overflow_retried = True
                        tighter_output = max(256, budget.reserved_output_tokens // 2)
                        budget = plan_budget(
                            messages=conversation,
                            limits=model_limits,
                            requested_output_tokens=tighter_output,
                        )
                        conversation, _ = _reduce_conversation_for_budget(
                            conversation, input_budget_tokens=budget.input_budget
                        )
                        continue
                    raise
                _llm_duration_ms = int((time.monotonic() - _llm_t0) * 1000)

                if (
                    effective == "native"
                    and allow_native_fallback
                    and not response.has_tool_calls
                ):
                    effective = "prompted"
                    allow_native_fallback = False
                    system_prompt = await _assemble_system("prompted")
                    conversation[0] = {"role": "system", "content": system_prompt}
                    _llm_t0_fb = time.monotonic()
                    raw_text, finish_reason, raw_msg, usage_fb = await LLMClient.chat_completion_full(
                        api_key or "",
                        settings_row,
                        messages=conversation,
                        temperature=0.15,
                        max_tokens=budget.reserved_output_tokens if rt.context_budget_v2 else None,
                    )
                    _llm_duration_ms = int((time.monotonic() - _llm_t0_fb) * 1000)
                    calls, parse_errors = parse_tool_calls_from_content(raw_text)
                    response = ChatResponse(
                        content=raw_text,
                        tool_calls=calls,
                        raw_message=raw_msg,
                        finish_reason=finish_reason,
                        usage=usage_fb,
                    )

                if effective == "native" and response.has_tool_calls:
                    allow_native_fallback = False

                step_idx += 1
                await emit_trace_event(
                    db,
                    run_id=run.id,
                    event_type=EV_LLM_RESPONSE,
                    trace_id=root_trace,
                    span_id=llm_span,
                    parent_span_id=root_span,
                    step_index=step_idx,
                    payload={
                        "finish_reason": response.finish_reason,
                        "usage": response.usage,
                        "tool_call_names": [tc.name for tc in response.tool_calls],
                        "has_tool_calls": response.has_tool_calls,
                        "duration_ms": _llm_duration_ms,
                    },
                )
                db.add(
                    AgentRunStep(
                        run_id=run.id,
                        step_index=step_idx,
                        kind="llm",
                        name="turn",
                        payload={
                            "content": (response.content or "")[:4000],
                            "tool_calls": [
                                {"name": tc.name, "arguments": tc.arguments}
                                for tc in response.tool_calls
                            ],
                            "harness_mode": effective,
                            "finish_reason": response.finish_reason,
                            "raw_response_text": (response.content or "")[:20000],
                            "raw_request_messages": _conversation_trace_snapshot(conversation),
                            "tool_call_parse_errors": parse_errors,
                            "usage": response.usage,
                            "approx_prompt_tokens": _approx_prompt_tokens(conversation),
                        },
                    )
                )

                if not response.has_tool_calls:
                    plain_reply = (response.content or "").strip()
                    if plain_reply:
                        run.assistant_reply = plain_reply
                        run.status = "completed"
                    else:
                        run.status = "failed"
                        run.error = (
                            "Model returned an empty response without tool calls. "
                            "Try again."
                        )
                    break

                if effective == "native":
                    conversation.append(_assistant_message_from(response))
                else:
                    conversation.append({"role": "assistant", "content": response.content or ""})

                tool_result_dicts: list[dict[str, Any]] = []
                stop_due_to_repeated_empty_gmail_search = False
                for call in response.tool_calls:
                    tool_name = call.name or ""
                    args = call.arguments if isinstance(call.arguments, dict) else {}
                    tool_span = new_span_id()
                    await emit_trace_event(
                        db,
                        run_id=run.id,
                        event_type=EV_TOOL_STARTED,
                        trace_id=root_trace,
                        span_id=tool_span,
                        parent_span_id=llm_span,
                        step_index=step_idx + 1,
                        payload={"tool_name": tool_name},
                    )
                    if tool_name == FINAL_ANSWER_TOOL_NAME:
                        text = str(args.get("text") or "").strip()
                        citations = args.get("citations") or []
                        if not text:
                            result = {
                                "error": "final_answer requires a non-empty 'text' field"
                            }
                            prop = None
                        else:
                            if isinstance(citations, list) and citations:
                                cite_txt = ", ".join(str(c) for c in citations)
                                final_answer_text = f"{text}\n\n— {cite_txt}"
                            else:
                                final_answer_text = text
                            result = {"ok": True}
                            prop = None
                    else:
                        result, prop = await AgentService._dispatch_tool(
                            db, user, run.id, thread_id, call
                        )
                    if prop is not None:
                        proposals_created.append(prop)
                    step_idx += 1
                    db.add(
                        AgentRunStep(
                            run_id=run.id,
                            step_index=step_idx,
                            kind="tool",
                            name=tool_name,
                            payload={"args": args, "result": result},
                        )
                    )
                    tool_result_dicts.append(result if isinstance(result, dict) else {"result": result})
                    if tool_name == "gmail_list_messages" and isinstance(result, dict):
                        result_size = result.get("resultSizeEstimate")
                        msgs = result.get("messages")
                        empty_result = False
                        if isinstance(result_size, int):
                            empty_result = result_size == 0
                        elif isinstance(msgs, list):
                            empty_result = len(msgs) == 0
                        if empty_result:
                            empty_gmail_search_streak += 1
                            q = str(args.get("q") or "").strip()
                            if q and q not in empty_gmail_queries:
                                empty_gmail_queries.append(q)
                        else:
                            empty_gmail_search_streak = 0
                            empty_gmail_queries.clear()
                        if empty_gmail_search_streak >= 4 and final_answer_text is None:
                            tried = ", ".join(f"'{q}'" for q in empty_gmail_queries[:4]) or "several queries"
                            run.assistant_reply = (
                                "No encuentro correos coincidentes en Gmail tras varias busquedas "
                                f"({tried}). Para continuar sin fallar: dime 1-2 remitentes, un rango "
                                "de fechas, o un fragmento exacto del asunto/cuerpo y lo intento de nuevo."
                            )
                            run.status = "completed"
                            stop_due_to_repeated_empty_gmail_search = True
                    elif tool_name != FINAL_ANSWER_TOOL_NAME:
                        empty_gmail_search_streak = 0
                        empty_gmail_queries.clear()
                    if effective == "native":
                        tool_payload = json.dumps(result, ensure_ascii=False, default=str)
                        conversation.append(
                            {
                                "role": "tool",
                                "tool_call_id": call.id,
                                "name": tool_name,
                                "content": clamp_tool_content_by_tokens(tool_payload, 3000),
                            }
                        )
                    try:
                        result_fingerprint = content_sha256_preview(
                            json.dumps(result, ensure_ascii=False, default=str)[:8000]
                        )
                    except (TypeError, ValueError):
                        result_fingerprint = ""
                    await emit_trace_event(
                        db,
                        run_id=run.id,
                        event_type=EV_TOOL_FINISHED,
                        trace_id=root_trace,
                        span_id=tool_span,
                        parent_span_id=llm_span,
                        step_index=step_idx,
                        payload={
                            "tool_name": tool_name,
                            "result_sha256": result_fingerprint,
                            "proposal": bool(prop),
                        },
                    )
                    if stop_due_to_repeated_empty_gmail_search:
                        break

                if stop_due_to_repeated_empty_gmail_search:
                    break

                executed_non_final = any(
                    (c.name or "") != FINAL_ANSWER_TOOL_NAME for c in response.tool_calls
                )
                if (
                    effective == "prompted"
                    and response.tool_calls
                    and (executed_non_final or final_answer_text is None)
                ):
                    conversation.append(
                        {
                            "role": "user",
                            "content": format_tool_results_for_prompt(
                                response.tool_calls, tool_result_dicts
                            ),
                        }
                    )
                if rt.context_budget_v2:
                    budget = plan_budget(messages=conversation, limits=model_limits)
                    if budget.compacted:
                        conversation, _ = _reduce_conversation_for_budget(
                            conversation, input_budget_tokens=budget.input_budget
                        )
                        budget = plan_budget(messages=conversation, limits=model_limits)

                if final_answer_text is not None:
                    run.assistant_reply = final_answer_text
                    run.status = "completed"
                    break

            else:
                run.status = "failed"
                run.error = "Step budget exceeded"

        except LLMProviderError as exc:
            step_idx += 1
            db.add(
                AgentRunStep(
                    run_id=run.id,
                    step_index=step_idx,
                    kind="provider_error",
                    name=exc.provider,
                    payload=exc.to_dict(),
                )
            )
            run.status = "failed"
            run.error = f"{exc.message} {exc.hint}".strip()[:2000]
        except KeyDecryptError as exc:
            step_idx += 1
            db.add(
                AgentRunStep(
                    run_id=run.id,
                    step_index=step_idx,
                    kind="key_decrypt_error",
                    name=exc.scope,
                    payload={
                        "kind": "key_decrypt_error",
                        "scope": exc.scope,
                        "reason": exc.reason,
                        "settings_url": "/settings#ai",
                    },
                )
            )
            run.status = "failed"
            run.error = (
                "An API key for the active provider exists but cannot be decrypted. "
                "Re-enter it in Settings → AI to recover."
            )
        except NoActiveProviderError as exc:
            run.status = "failed"
            run.error = str(exc) or "No AI provider is selected as active."
            run.assistant_reply = run.error
        except Exception as exc:
            run.status = "failed"
            run.error = str(exc)[:2000]

        finally:
            if _replay_token is not None:
                _replay_ctx.reset(_replay_token)

        if run.root_trace_id:
            if run.status == "completed":
                await emit_trace_event(
                    db,
                    run_id=run.id,
                    event_type=EV_RUN_COMPLETED,
                    trace_id=run.root_trace_id,
                    span_id=root_span,
                    payload={
                        "assistant_reply_sha256": content_sha256_preview(run.assistant_reply or ""),
                    },
                )
            elif run.status == "failed":
                await emit_trace_event(
                    db,
                    run_id=run.id,
                    event_type=EV_RUN_FAILED,
                    trace_id=run.root_trace_id,
                    span_id=root_span,
                    payload={"error": (run.error or "")[:500]},
                )

        run.updated_at = datetime.now(UTC)
        await db.commit()
        await db.refresh(run)

        for p in proposals_created:
            await db.refresh(p)
        prop_reads = [proposal_to_read(p) for p in proposals_created]
        steps = await AgentService._load_steps(db, run.id)
        return AgentService._to_read(run, steps, prop_reads)

    @staticmethod
    async def _load_steps(db: AsyncSession, run_id: int) -> list[AgentStepRead]:
        result = await db.execute(
            select(AgentRunStep).where(AgentRunStep.run_id == run_id).order_by(AgentRunStep.step_index)
        )
        rows = result.scalars().all()
        return [
            AgentStepRead(step_index=s.step_index, kind=s.kind, name=s.name, payload=s.payload)
            for s in rows
        ]

    @staticmethod
    def _to_read(
        run: AgentRun,
        steps: list[AgentStepRead],
        proposals: list[PendingProposalRead],
        *,
        attention: AgentRunAttentionRead | None = None,
    ) -> AgentRunRead:
        return AgentRunRead(
            id=run.id,
            status=run.status,
            user_message=run.user_message,
            assistant_reply=run.assistant_reply,
            error=run.error,
            root_trace_id=run.root_trace_id,
            chat_thread_id=run.chat_thread_id,
            turn_profile=getattr(run, "turn_profile", None) or TURN_PROFILE_USER_CHAT,
            attention=attention,
            steps=steps,
            pending_proposals=proposals,
        )

    @staticmethod
    async def list_recent_runs(db: AsyncSession, user: User, *, limit: int = 30) -> list[AgentRunSummaryRead]:
        lim = max(1, min(100, int(limit)))
        result = await db.execute(
            select(AgentRun)
            .where(AgentRun.user_id == user.id)
            .order_by(AgentRun.id.desc())
            .limit(lim)
        )
        rows = result.scalars().all()
        out: list[AgentRunSummaryRead] = []
        for r in rows:
            um = r.user_message or ""
            preview = um[:240] + ("…" if len(um) > 240 else "")
            out.append(
                AgentRunSummaryRead(
                    id=r.id,
                    status=r.status,
                    user_message_preview=preview,
                    created_at=r.created_at,
                    root_trace_id=r.root_trace_id,
                    chat_thread_id=r.chat_thread_id,
                )
            )
        return out

    @staticmethod
    async def list_trace_events(
        db: AsyncSession, user: User, run_id: int
    ) -> list[AgentTraceEventRead] | None:
        run = await db.get(AgentRun, run_id)
        if not run or run.user_id != user.id:
            return None
        result = await db.execute(
            select(AgentTraceEvent).where(AgentTraceEvent.run_id == run_id).order_by(AgentTraceEvent.id)
        )
        rows = result.scalars().all()
        return [
            AgentTraceEventRead(
                id=r.id,
                schema_version=r.schema_version,
                event_type=r.event_type,
                trace_id=r.trace_id,
                span_id=r.span_id,
                parent_span_id=r.parent_span_id,
                step_index=r.step_index,
                payload=_trim_step_payload_for_client(r.payload)
                if isinstance(r.payload, dict)
                else r.payload,
                created_at=r.created_at,
            )
            for r in rows
        ]

    @staticmethod
    async def get_run(db: AsyncSession, user: User, run_id: int) -> AgentRunRead | None:
        run = await db.get(AgentRun, run_id)
        if not run or run.user_id != user.id:
            return None
        steps_raw = await AgentService._load_steps(db, run.id)
        steps = [
            AgentStepRead(
                step_index=s.step_index,
                kind=s.kind,
                name=s.name,
                payload=_trim_step_payload_for_client(s.payload),
            )
            for s in steps_raw
        ]
        pr = await db.execute(
            select(PendingProposal).where(
                PendingProposal.run_id == run_id, PendingProposal.user_id == user.id
            )
        )
        props = [proposal_to_read(p) for p in pr.scalars().all()]
        attention = None
        if run.status in {"pending", "running", "needs_attention"}:
            snap = await build_attention_snapshot(db, run)
            attention = AgentRunAttentionRead(
                stage=snap.stage,
                last_event_at=snap.last_event_at,
                hint=snap.hint,
            )
        return AgentService._to_read(run, steps, props, attention=attention)
