"""ReAct loop + tool dispatch for the OpenClaw-style agent.

After the refactor the agent has *no* local mirrors to read from — every
read tool talks straight to the upstream provider (Gmail, Calendar,
Drive, Outlook, Teams). Most writes auto-execute; only outbound email
(send + reply) goes through the human-approval ``PendingProposal``
flow. Memory and skills are the agent's own state.

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

import base64
import json
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.envelope_crypto import KeyDecryptError
from app.models.agent_run import AgentRun, AgentRunStep, AgentTraceEvent
from app.models.connector_connection import ConnectorConnection
from app.models.pending_proposal import PendingProposal
from app.models.user import User
from app.schemas.agent import AgentRunRead, AgentStepRead, AgentTraceEventRead, PendingProposalRead
from app.services.agent_harness.native import chat_turn_native
from app.services.agent_harness.prompted import (
    format_tool_results_for_prompt,
    parse_tool_calls_from_content,
)
from app.services.agent_harness.selector import resolve_effective_mode
from app.services.agent_memory_service import AgentMemoryService
from app.services.agent_replay import AgentReplayContext
from app.services.agent_tools import (
    AGENT_TOOL_NAMES,
    AGENT_TOOLS,
    FINAL_ANSWER_TOOL_NAME,
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
from app.services.agent_workspace import build_system_prompt
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
from app.services.connectors.graph_client import GraphAPIError, GraphClient
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
from app.services.oauth import TokenManager
from app.services.oauth.errors import ConnectorNeedsReauth, OAuthError
from app.services.proposal_service import proposal_to_read
from app.services.skills_service import list_skills as _list_skills
from app.services.skills_service import load_skill as _load_skill
from app.services.user_ai_settings_service import UserAISettingsService
from app.services.user_time_context import normalize_time_format, session_time_result

# Provider id sets used by ``_resolve_connection``.
_GMAIL_PROVIDERS = ("google_gmail", "gmail")
_CAL_PROVIDERS = ("google_calendar", "gcal")
_DRIVE_PROVIDERS = ("google_drive", "gdrive")
_OUTLOOK_PROVIDERS = ("graph_mail",)
_TEAMS_PROVIDERS = ("graph_teams", "ms_teams")

_replay_ctx: ContextVar[AgentReplayContext | None] = ContextVar("agent_replay", default=None)


def get_tool_palette(
    user: User,
    *,
    tenant_hint: str | None = None,
    palette_mode: str | None = None,
) -> list[dict[str, Any]]:
    """Which tool schemas to advertise this run (full vs compact via settings or override).

    Per-tenant toggles can plug in via ``tenant_hint`` and ``palette_mode`` later.
    """
    del tenant_hint
    del user  # reserved for future per-user allowlists
    mode = palette_mode if palette_mode is not None else settings.agent_tool_palette
    return tools_for_palette_mode(mode)


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


def _approx_prompt_tokens(messages: list[dict[str, Any]]) -> int:
    """Rough token estimate for trace metrics (not billing-accurate)."""
    try:
        raw = json.dumps(messages, ensure_ascii=False)
    except (TypeError, ValueError):
        raw = ""
    return max(1, len(raw) // 4)


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


async def _graph_client(db: AsyncSession, row: ConnectorConnection) -> GraphClient:
    token = await TokenManager.get_valid_access_token(db, row)
    return GraphClient(token)


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
        return await client.list_events(
            str(args.get("calendar_id") or "primary"),
            page_token=args.get("page_token"),
            max_results=int(args.get("max_results") or 50),
        )

    @staticmethod
    async def _tool_calendar_create_event(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _CAL_PROVIDERS, label="Google Calendar")
        _token, creds, provider = await TokenManager.get_valid_creds(db, row)
        return await create_calendar_event(provider, creds, args)

    @staticmethod
    async def _tool_calendar_update_event(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _CAL_PROVIDERS, label="Google Calendar")
        _token, creds, provider = await TokenManager.get_valid_creds(db, row)
        return await update_calendar_event(provider, creds, args)

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
        row = await AgentMemoryService.upsert(
            db,
            user,
            key=str(args["key"]),
            content=str(args["content"]),
            importance=int(args.get("importance") or 0),
            tags=args.get("tags"),
        )
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
    # Proposal tools (only outbound EMAIL is gated)
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

    # ------------------------------------------------------------------
    # Tool dispatch — single source of truth for routing model-issued
    # tool calls to the matching internal handler.
    # ------------------------------------------------------------------

    # name → (handler attr, takes_run_id)
    _DISPATCH: dict[str, tuple[str, bool]] = {
        # Reads
        "gmail_list_messages": ("_tool_gmail_list_messages", False),
        "gmail_get_message": ("_tool_gmail_get_message", False),
        "gmail_get_thread": ("_tool_gmail_get_thread", False),
        "gmail_list_labels": ("_tool_gmail_list_labels", False),
        "gmail_list_filters": ("_tool_gmail_list_filters", False),
        "calendar_list_events": ("_tool_calendar_list_events", False),
        "drive_list_files": ("_tool_drive_list_files", False),
        "outlook_list_messages": ("_tool_outlook_list_messages", False),
        "outlook_get_message": ("_tool_outlook_get_message", False),
        "teams_list_teams": ("_tool_teams_list_teams", False),
        "teams_list_channels": ("_tool_teams_list_channels", False),
        "list_connectors": ("_tool_list_connectors", False),
        "get_session_time": ("_tool_get_session_time", False),
        # Auto-apply Gmail
        "gmail_modify_message": ("_tool_gmail_modify_message", False),
        "gmail_modify_thread": ("_tool_gmail_modify_thread", False),
        "gmail_trash_message": ("_tool_gmail_trash_message", False),
        "gmail_untrash_message": ("_tool_gmail_untrash_message", False),
        "gmail_trash_thread": ("_tool_gmail_trash_thread", False),
        "gmail_trash_bulk_query": ("_tool_gmail_trash_bulk_query", False),
        "gmail_untrash_thread": ("_tool_gmail_untrash_thread", False),
        "gmail_mark_read": ("_tool_gmail_mark_read", False),
        "gmail_mark_unread": ("_tool_gmail_mark_unread", False),
        "gmail_silence_sender": ("_tool_gmail_silence_sender", False),
        "gmail_create_filter": ("_tool_gmail_create_filter", False),
        "gmail_delete_filter": ("_tool_gmail_delete_filter", False),
        # Auto-apply calendar
        "calendar_create_event": ("_tool_calendar_create_event", False),
        "calendar_update_event": ("_tool_calendar_update_event", False),
        "calendar_delete_event": ("_tool_calendar_delete_event", False),
        # Auto-apply drive
        "drive_upload_file": ("_tool_drive_upload_file", False),
        "drive_share_file": ("_tool_drive_share_file", False),
        # Auto-apply teams
        "teams_post_message": ("_tool_teams_post_message", False),
        # Memory + skills
        "upsert_memory": ("_tool_upsert_memory", False),
        "delete_memory": ("_tool_delete_memory", False),
        "list_memory": ("_tool_list_memory", False),
        "recall_memory": ("_tool_recall_memory", False),
        "list_skills": ("_tool_list_skills", False),
        "load_skill": ("_tool_load_skill", False),
        # Connector setup
        "start_connector_setup": ("_tool_start_connector_setup", False),
        "submit_connector_credentials": ("_tool_submit_connector_credentials", False),
        "start_oauth_flow": ("_tool_start_oauth_flow", False),
        # Proposals (gated)
        "propose_email_send": ("_tool_propose_email_send", True),
        "propose_email_reply": ("_tool_propose_email_reply", True),
    }

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
        except (GmailAPIError, CalendarAPIError, DriveAPIError, GraphAPIError) as exc:
            return ({"error": f"upstream {exc.status_code}: {exc.detail[:300]}"}, None)
        except Exception as exc:  # noqa: BLE001 — surface tool errors to the model
            return ({"error": str(exc)[:500]}, None)

        prop_id = result.get("proposal_id") if isinstance(result, dict) else None
        if prop_id:
            prop = await db.get(PendingProposal, int(prop_id))
            return (result, prop)
        return (result, None)

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
    async def create_pending_agent_run(
        db: AsyncSession,
        user: User,
        message: str,
        *,
        thread_id: int | None = None,
    ) -> AgentRun:
        root_trace = new_trace_id()
        run = AgentRun(
            user_id=user.id,
            status="pending",
            user_message=message,
            root_trace_id=root_trace,
            chat_thread_id=thread_id,
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
        """
        early = await AgentService.run_agent_invalid_preflight(db, user, message, thread_id=thread_id)
        if early is not None:
            return early

        root_trace = new_trace_id()
        run = AgentRun(
            user_id=user.id,
            status="running",
            user_message=message,
            root_trace_id=root_trace,
            chat_thread_id=thread_id,
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
    ) -> AgentRunRead:
        message = run.user_message
        thread_id = run.chat_thread_id
        settings_row = await UserAISettingsService.get_or_create(db, user)
        api_key = await UserAISettingsService.get_api_key(db, user)
        turn_tools = get_tool_palette(user)
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
            },
        )

        system_prompt = await build_system_prompt(
            db,
            user,
            tool_palette=turn_tools,
            harness_mode=effective,
            thread_context_hint=thread_context_hint,
            user_timezone=getattr(settings_row, "user_timezone", None),
            time_format=normalize_time_format(getattr(settings_row, "time_format", None)),
        )
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
            for _ in range(settings.agent_max_tool_steps):
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
                        "tool_defs_count": len(turn_tools),
                        "harness_mode": effective,
                    },
                )
                if effective == "native":
                    response = await chat_turn_native(
                        api_key or "",
                        settings_row,
                        messages=conversation,
                        tools=turn_tools,
                        temperature=0.15,
                    )
                else:
                    raw_text, finish_reason, raw_msg, usage_cf = await LLMClient.chat_completion_full(
                        api_key or "",
                        settings_row,
                        messages=conversation,
                        temperature=0.15,
                    )
                    calls, parse_errors = parse_tool_calls_from_content(raw_text)
                    response = ChatResponse(
                        content=raw_text,
                        tool_calls=calls,
                        raw_message=raw_msg,
                        finish_reason=finish_reason,
                        usage=usage_cf,
                    )

                if (
                    effective == "native"
                    and allow_native_fallback
                    and not response.has_tool_calls
                    and (response.content or "").strip()
                ):
                    effective = "prompted"
                    allow_native_fallback = False
                    system_prompt = await build_system_prompt(
                        db,
                        user,
                        tool_palette=turn_tools,
                        harness_mode="prompted",
                        thread_context_hint=thread_context_hint,
                        user_timezone=getattr(settings_row, "user_timezone", None),
                        time_format=normalize_time_format(getattr(settings_row, "time_format", None)),
                    )
                    conversation[0] = {"role": "system", "content": system_prompt}
                    raw_text, finish_reason, raw_msg, usage_fb = await LLMClient.chat_completion_full(
                        api_key or "",
                        settings_row,
                        messages=conversation,
                        temperature=0.15,
                    )
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
                    run.assistant_reply = (response.content or "").strip()
                    run.status = "completed"
                    break

                if effective == "native":
                    conversation.append(_assistant_message_from(response))
                else:
                    conversation.append({"role": "assistant", "content": response.content or ""})

                tool_result_dicts: list[dict[str, Any]] = []
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
                    if effective == "native":
                        conversation.append(
                            {
                                "role": "tool",
                                "tool_call_id": call.id,
                                "name": tool_name,
                                "content": json.dumps(result, ensure_ascii=False)[:12000],
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
    ) -> AgentRunRead:
        return AgentRunRead(
            id=run.id,
            status=run.status,
            user_message=run.user_message,
            assistant_reply=run.assistant_reply,
            error=run.error,
            root_trace_id=run.root_trace_id,
            chat_thread_id=run.chat_thread_id,
            steps=steps,
            pending_proposals=proposals,
        )

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
                payload=r.payload,
                created_at=r.created_at,
            )
            for r in rows
        ]

    @staticmethod
    async def get_run(db: AsyncSession, user: User, run_id: int) -> AgentRunRead | None:
        run = await db.get(AgentRun, run_id)
        if not run or run.user_id != user.id:
            return None
        steps = await AgentService._load_steps(db, run.id)
        pr = await db.execute(
            select(PendingProposal).where(
                PendingProposal.run_id == run_id, PendingProposal.user_id == user.id
            )
        )
        props = [proposal_to_read(p) for p in pr.scalars().all()]
        return AgentService._to_read(run, steps, props)
