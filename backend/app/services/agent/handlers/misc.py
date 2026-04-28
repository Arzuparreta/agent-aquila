"""Miscellaneous tool handlers."""
from __future__ import annotations
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.connector_connection import ConnectorConnection
from app.models.user import User
from app.models.scheduled_task import ScheduledTask
from app.services.ai_providers import provider_kind_requires_api_key
from app.services.agent.runtime import web_search, web_fetch
from app.services.connector_service import start_connector_setup, submit_connector_credentials, start_oauth_flow
from app.services.agent.runtime_clients import DeviceFilesClient

There are no local mailbox mirrors: every read tool calls the upstream API (Gmail, Calendar,
Drive, Outlook, Teams, and other linked connectors). Most writes run immediately; outbound email
and select high-risk sends use ``PendingProposal`` for human approval. Memory and skills are
agent-local state. ``turn_profile`` on each :class:`AgentRun` controls palette width and step
limits for context-first **non-chat** entry points.

Harness contract:

1. Send the FULL tool palette + the conversation to the LLM (native
   ``tools=`` parameter when the **native** harness is active; embedded JSON +
   ``<tool_call>`` tags when **prompted** — see ``agent_harness``).
2. Native path may use ``tool_choice="required"`` when enabled in runtime
   settings; otherwise ``auto`` is used (better compatibility with routed providers).
   Ollama may still ignore tool calling — we auto-fallback to prompted once per run.
3. Execute every tool call, feed results back (``role:"tool"`` for native;
   ``role:"user"`` + ``<tool_response>`` for prompted).
4. Stop when the model calls ``final_answer`` OR when ``settings.agent_max_tool_steps``.

Mis-invoked tools return structured errors; the model is expected to retry.
"""

from __future__ import annotations

import asyncio
import base64
import json

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
    row = await _resolve_connection(db, user, args, GMAIL_TOOL_PROVIDERS, label="Gmail")
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

        else:
            end_d = start_d + timedelta(days=30)
        events = await client.list_events(cal_url, start=start_d, end=end_d)
        return {"provider": prov, "calendar_url": cal_url, "events": events}

    if prov in GRAPH_CALENDAR_TOOL_PROVIDERS:
        token = await TokenManager.get_valid_access_token(db, row)
        g = GraphClient(token)
        end_s = str(time_max) if time_max else None
        if not end_s:
            try:
                start_dt = _parse_rfc3339_to_utc_datetime(str(time_min))
            except ValueError:
                start_dt = datetime.now(UTC)
            end_dt = start_dt + timedelta(days=30)
            end_s = end_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            raw = await g.list_calendar_view(
                start_datetime=str(time_min),
                end_datetime=end_s,
                top=min(max(max_results, 1), 250),

            )
        except GraphAPIError as exc:
            return {"provider": prov, "error": exc.detail, "status": exc.status_code}
        return {"provider": prov, "events": raw.get("value") or [], "@odata": raw.get("@odata.nextLink")}

    return {"error": f"unsupported calendar provider: {prov}"}

@staticmethod
async def _tool_calendar_create_event(
    db: AsyncSession, user: User, args: dict[str, Any]
) -> dict[str, Any]:

    row = await _resolve_connection(db, user, args, CALENDAR_TOOL_PROVIDERS, label="calendar")
    prov = row.provider
    if prov == "icloud_caldav":
        client = _icloud_caldav_client(row)
        cal_url = str(args.get("calendar_url") or "").strip()
        if not cal_url:
            cal_url = await _default_icloud_calendar_url(client)
        start = datetime.fromisoformat(str(args["start_iso"]).replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(args["end_iso"]).replace("Z", "+00:00"))
        return await client.create_event(
            cal_url,
            summary=str(args["summary"]),
            start=start,
            end=end,
            description=str(args["description"]) if args.get("description") else None,
        )
    _token, creds, provider = await TokenManager.get_valid_creds(db, row)

    payload = await merge_calendar_timezone_from_user_prefs(db, user, args)
    return await create_calendar_event(provider, creds, payload)

@staticmethod
async def _tool_calendar_update_event(
    db: AsyncSession, user: User, args: dict[str, Any]
) -> dict[str, Any]:
    row = await _resolve_connection(db, user, args, CALENDAR_TOOL_PROVIDERS, label="calendar")
    if row.provider == "icloud_caldav":
        return {
            "ok": False,
            "error": "iCloud calendar updates are not supported via this tool yet; delete and recreate, or use another calendar client.",
        }
    _token, creds, provider = await TokenManager.get_valid_creds(db, row)
    payload = await merge_calendar_timezone_from_user_prefs(db, user, args)

    return await update_calendar_event(provider, creds, payload)

@staticmethod
async def _tool_calendar_delete_event(
    db: AsyncSession, user: User, args: dict[str, Any]
) -> dict[str, Any]:
    row = await _resolve_connection(db, user, args, CALENDAR_TOOL_PROVIDERS, label="calendar")
    if row.provider == "icloud_caldav":

        return {
            "ok": False,
            "error": "iCloud calendar deletes are not supported via this tool yet; remove the event in Apple Calendar or another CalDAV client.",
        }
    _token, creds, provider = await TokenManager.get_valid_creds(db, row)
    return await delete_calendar_event(provider, creds, str(args["event_id"]))

# ------------------------------------------------------------------
# Drive tools
# ------------------------------------------------------------------
@staticmethod
async def _tool_drive_list_files(
    db: AsyncSession, user: User, args: dict[str, Any]
) -> dict[str, Any]:
    row = await _resolve_connection(db, user, args, DRIVE_TOOL_PROVIDERS, label="Google Drive")
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
    row = await _resolve_connection(db, user, args, DRIVE_TOOL_PROVIDERS, label="Google Drive")
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

    client = await _telegram_client(db, row)
    result = await client.send_message(cid, text[:4096])
    return {"ok": True, "result": result}

@staticmethod

