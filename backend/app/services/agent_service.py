"""ReAct loop + tool dispatch for the OpenClaw-style agent.

After the refactor the agent has *no* local mirrors to read from — every
read tool talks straight to the upstream provider (Gmail, Calendar,
Drive, Outlook, Teams). Most writes auto-execute; only outbound email
(send + reply) goes through the human-approval ``PendingProposal``
flow. Memory and skills are the agent's own state.

Harness contract (intentionally tiny):

1. Send the FULL tool palette + the conversation to the LLM.
2. ``tool_choice="required"`` — every turn must end in a tool call.
3. Execute every tool call the model issued, feed results back as
   ``role:"tool"`` messages.
4. Stop when the model calls ``final_answer`` (the universal
   terminator) OR when ``settings.agent_max_tool_steps`` is reached.

The agent picks tools by reading their ``description`` fields. There is
NO model-compensating logic: no tool-name aliasing, no argument coercion,
no "must-ground" gates, no consecutive-unknown-call loop breakers. Those
were band-aids for weak local models and they actively harm scalability;
when a tool is misused the model gets a structured error back and is
expected to retry.
"""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.envelope_crypto import KeyDecryptError
from app.models.agent_run import AgentRun, AgentRunStep
from app.models.connector_connection import ConnectorConnection
from app.models.pending_proposal import PendingProposal
from app.models.user import User
from app.schemas.agent import AgentRunRead, AgentStepRead, PendingProposalRead
from app.services.agent_memory_service import AgentMemoryService
from app.services.agent_tools import (
    AGENT_TOOL_NAMES,
    AGENT_TOOLS,
    FINAL_ANSWER_TOOL_NAME,
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
from app.services.connectors.graph_client import GraphAPIError, GraphClient
from app.services.llm_client import ChatResponse, ChatToolCall, LLMClient
from app.services.llm_errors import LLMProviderError, NoActiveProviderError
from app.services.oauth import TokenManager
from app.services.oauth.errors import ConnectorNeedsReauth, OAuthError
from app.services.proposal_service import proposal_to_read
from app.services.skills_service import list_skills as _list_skills
from app.services.skills_service import load_skill as _load_skill
from app.services.user_ai_settings_service import UserAISettingsService

# Provider id sets used by ``_resolve_connection``.
_GMAIL_PROVIDERS = ("google_gmail", "gmail")
_CAL_PROVIDERS = ("google_calendar", "gcal")
_DRIVE_PROVIDERS = ("google_drive", "gdrive")
_OUTLOOK_PROVIDERS = ("graph_mail",)
_TEAMS_PROVIDERS = ("graph_teams", "ms_teams")


AGENT_SYSTEM = """You are the user's personal operations agent. The user is NON-TECHNICAL — never mention APIs, OAuth, JSON, model names, or any internal implementation. Speak like a friendly colleague.

You operate inside a chat app and have full live access to the user's Gmail, Google Calendar, Google Drive, Microsoft Outlook, and Microsoft Teams via the tools listed in this turn. You also have a small persistent memory (key/value scratchpad) for things the user wants you to remember across sessions, and a folder of skills (markdown recipes for common workflows).

# Rules of engagement

1. Every assistant turn MUST end in a tool call. The tools available to you this turn are listed in the ``tools`` array — pick from that list using the exact name spelled in the schema.
2. ``final_answer`` is the terminator: call it (exactly once) to deliver the user-facing reply. After ``final_answer`` the turn ends. Never write a free-form text reply outside ``final_answer`` — the user will not see it.
3. Ground factual claims with a tool BEFORE answering. For any question about the user's data (mail, calendar, files, Teams), or any preference / action the user asks you to remember or perform, first call the tool whose ``description`` matches the request, then summarize its result in ``final_answer.text``. Never invent data; never paraphrase what a previous turn said about that data — re-check with a tool every time.
4. Reply in the same language the user uses (default: Spanish). Be concise. Cite bare ids inline in ``final_answer.text`` (e.g. "(gmail:msg_xyz)") and/or in ``final_answer.citations``.

Almost every action runs immediately (label, mute, spam, archive, calendar, Drive). The ONLY exception is outbound email: ``propose_email_send`` and ``propose_email_reply`` create approval cards the user must tap before anything is sent. Never describe a sent reply as if it had already gone out.

When you discover a stable preference or a useful fact about the user, save it via ``upsert_memory`` so future turns benefit. When facing a multi-step workflow you've handled before, check ``list_skills`` and ``load_skill`` for a matching recipe.
"""


def get_tool_palette(
    user: User,
    *,
    tenant_hint: str | None = None,
) -> list[dict[str, Any]]:
    """Extension seam: which tool schemas to advertise to the agent this run.

    Today: returns the full ``AGENT_TOOLS`` palette for everyone. The agent
    picks the right tool by reading each tool's ``description``.

    Tomorrow: this is where per-tenant skill toggles plug in (e.g. "starter"
    tier gets only read-only tools, B2B vertical gets a CRM-flavored
    palette). The signature accepts ``user`` and ``tenant_hint`` so
    per-user/per-vertical filtering is a one-function change.
    """
    del user, tenant_hint  # explicit: today the palette is universal
    return AGENT_TOOLS


async def build_system_prompt(
    db: AsyncSession,
    user: User,
    *,
    thread_context_hint: str | None = None,
    tenant_hint: str | None = None,
) -> str:
    """Assemble the system prompt: persona + memory warmup + thread hint.

    The memory warmup (top N rows from ``agent_memories``) is appended so
    the model starts each turn knowing what it has already learned. This
    is the OpenClaw-style "scratchpad in the prompt" trick.
    """
    del tenant_hint  # explicit: today the persona is universal
    parts: list[str] = [AGENT_SYSTEM]
    memory_blob = await AgentMemoryService.recent_for_prompt(db, user)
    if memory_blob:
        parts.append(memory_blob)
    if thread_context_hint:
        parts.append(f"Thread context: {thread_context_hint.strip()}")
    return "\n\n".join(parts)


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
        client = await _gmail_client(db, row)
        return await client.get_message(
            str(args["message_id"]), format=str(args.get("format") or "full")
        )

    @staticmethod
    async def _tool_gmail_get_thread(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _GMAIL_PROVIDERS, label="Gmail")
        client = await _gmail_client(db, row)
        return await client.get_thread(
            str(args["thread_id"]), format=str(args.get("format") or "metadata")
        )

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
        return await client.modify_message(
            str(args["message_id"]),
            add_label_ids=args.get("add_label_ids"),
            remove_label_ids=args.get("remove_label_ids"),
        )

    @staticmethod
    async def _tool_gmail_modify_thread(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _GMAIL_PROVIDERS, label="Gmail")
        client = await _gmail_client(db, row)
        return await client.modify_thread(
            str(args["thread_id"]),
            add_label_ids=args.get("add_label_ids"),
            remove_label_ids=args.get("remove_label_ids"),
        )

    @staticmethod
    async def _tool_gmail_trash_message(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _GMAIL_PROVIDERS, label="Gmail")
        client = await _gmail_client(db, row)
        return await client.trash_message(str(args["message_id"]))

    @staticmethod
    async def _tool_gmail_untrash_message(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _GMAIL_PROVIDERS, label="Gmail")
        client = await _gmail_client(db, row)
        return await client.untrash_message(str(args["message_id"]))

    @staticmethod
    async def _tool_gmail_trash_thread(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _GMAIL_PROVIDERS, label="Gmail")
        client = await _gmail_client(db, row)
        return await client.trash_thread(str(args["thread_id"]))

    @staticmethod
    async def _tool_gmail_untrash_thread(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _GMAIL_PROVIDERS, label="Gmail")
        client = await _gmail_client(db, row)
        return await client.untrash_thread(str(args["thread_id"]))

    @staticmethod
    async def _tool_gmail_mark_read(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _GMAIL_PROVIDERS, label="Gmail")
        client = await _gmail_client(db, row)
        if args.get("thread_id"):
            return await client.modify_thread(
                str(args["thread_id"]), remove_label_ids=["UNREAD"]
            )
        if args.get("message_id"):
            return await client.modify_message(
                str(args["message_id"]), remove_label_ids=["UNREAD"]
            )
        return {"error": "either message_id or thread_id is required"}

    @staticmethod
    async def _tool_gmail_mark_unread(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        row = await _resolve_connection(db, user, args, _GMAIL_PROVIDERS, label="Gmail")
        client = await _gmail_client(db, row)
        if args.get("thread_id"):
            return await client.modify_thread(
                str(args["thread_id"]), add_label_ids=["UNREAD"]
            )
        if args.get("message_id"):
            return await client.modify_message(
                str(args["message_id"]), add_label_ids=["UNREAD"]
            )
        return {"error": "either message_id or thread_id is required"}

    @staticmethod
    async def _tool_gmail_silence_sender(
        db: AsyncSession, user: User, args: dict[str, Any]
    ) -> dict[str, Any]:
        """High-level: create a filter that mutes (or spams) future mail.

        ``mode='mute'`` (default): future messages skip the inbox.
        ``mode='spam'``: same, plus the SPAM label is applied.
        """
        email = str(args.get("email") or "").strip()
        if not email:
            return {"error": "email (sender address) is required"}
        mode = str(args.get("mode") or "mute").lower()
        row = await _resolve_connection(db, user, args, _GMAIL_PROVIDERS, label="Gmail")
        client = await _gmail_client(db, row)
        criteria = {"from": email}
        action: dict[str, Any] = {"removeLabelIds": ["INBOX"]}
        if mode == "spam":
            action["addLabelIds"] = ["SPAM"]
        result = await client.create_filter(criteria=criteria, action=action)
        return {
            "ok": True,
            "mode": mode,
            "sender": email,
            "filter_id": result.get("id"),
            "summary": (
                f"Future mail from {email} will skip the inbox"
                + (" and be marked as spam." if mode == "spam" else ".")
            ),
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
        # Auto-apply Gmail
        "gmail_modify_message": ("_tool_gmail_modify_message", False),
        "gmail_modify_thread": ("_tool_gmail_modify_thread", False),
        "gmail_trash_message": ("_tool_gmail_trash_message", False),
        "gmail_untrash_message": ("_tool_gmail_untrash_message", False),
        "gmail_trash_thread": ("_tool_gmail_trash_thread", False),
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
    async def run_agent(
        db: AsyncSession,
        user: User,
        message: str,
        *,
        prior_messages: list[dict[str, str]] | None = None,
        thread_id: int | None = None,
        thread_context_hint: str | None = None,
    ) -> AgentRunRead:
        """Run one agent turn.

        ``prior_messages``: optional ``[{role, content}, ...]`` of previous user/assistant
          turns from the same chat thread (so multi-turn conversations are coherent).
        ``thread_id``: persisted on AgentRun so executed actions / proposals can route
          their inline cards back into the right chat thread.
        ``thread_context_hint``: a short system-injected context blurb such as
          ``"Conversation about thread #42"``.
        """
        settings_row = await UserAISettingsService.get_or_create(db, user)
        if settings_row.ai_disabled:
            run = AgentRun(
                user_id=user.id,
                status="failed",
                user_message=message,
                error="AI is disabled for this user",
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
            )
            db.add(run)
            await db.commit()
            await db.refresh(run)
            return AgentService._to_read(run, [], [])

        run = AgentRun(user_id=user.id, status="running", user_message=message)
        db.add(run)
        await db.flush()

        system_prompt = await build_system_prompt(
            db, user, thread_context_hint=thread_context_hint
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

        turn_tools = get_tool_palette(user)

        try:
            final_answer_text: str | None = None
            for _ in range(settings.agent_max_tool_steps):
                response = await LLMClient.chat_with_tools(
                    api_key or "",
                    settings_row,
                    messages=conversation,
                    tools=turn_tools,
                    tool_choice="required",
                    temperature=0.15,
                )
                step_idx += 1
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
                        },
                    )
                )

                if not response.has_tool_calls:
                    run.assistant_reply = (response.content or "").strip()
                    run.status = "completed"
                    break

                conversation.append(_assistant_message_from(response))

                for call in response.tool_calls:
                    tool_name = call.name or ""
                    args = call.arguments if isinstance(call.arguments, dict) else {}
                    if tool_name == FINAL_ANSWER_TOOL_NAME:
                        text = str(args.get("text") or "").strip()
                        citations = args.get("citations") or []
                        if not text:
                            result: dict[str, Any] = {
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
                    conversation.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.id,
                            "name": tool_name,
                            "content": json.dumps(result, ensure_ascii=False)[:12000],
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
            steps=steps,
            pending_proposals=proposals,
        )

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
