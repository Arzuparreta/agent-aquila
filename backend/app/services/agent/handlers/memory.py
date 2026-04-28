from __future__ import annotations
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.connector_connection import ConnectorConnection
from app.models.user import User
from app.services.agent.runtime_clients import (
    GmailClient, GoogleCalendarClient, GoogleDriveClient,
    GoogleSheetsClient, GoogleDocsClient, GoogleTasksClient,
    GooglePeopleClient, GitHubClient, SlackClient,
    TelegramBotClient, DiscordBotClient, LinearClient,
    NotionClient, ICloudCalDAVClient, YoutubeClient,
    share_file, upload_file,
)
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
    row = await _resolve_connection(db, user, args, GMAIL_TOOL_PROVIDERS, label="Gmail")
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
    row = await _resolve_connection(db, user, args, GMAIL_TOOL_PROVIDERS, label="Gmail")
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
    row = await _resolve_connection(db, user, args, GMAIL_TOOL_PROVIDERS, label="Gmail")
    client = await _gmail_client(db, row)

    return await client.delete_filter(str(args["filter_id"]))

# ------------------------------------------------------------------
# Calendar tools (Google Calendar, Microsoft Graph, iCloud CalDAV)
# ------------------------------------------------------------------
@staticmethod
async def _tool_calendar_list_calendars(
    db: AsyncSession, user: User, args: dict[str, Any]
) -> dict[str, Any]:
    row = await _resolve_connection(db, user, args, CALENDAR_TOOL_PROVIDERS, label="calendar")
    prov = row.provider
    if prov in ("google_calendar", "gcal"):
        client = await _calendar_client(db, row)

        return await client.list_calendar_list(
            page_token=args.get("page_token"),
            max_results=int(args.get("max_results") or 250),
        )
    if prov == "icloud_caldav":
        client = _icloud_caldav_client(row)
        cals = await client.list_calendars()
        return {
            "provider": prov,
            "items": [
                {"summary": c.get("name"), "calendar_id": None, "calendar_url": c.get("url")}
                for c in cals
            ],
        }
    if prov in GRAPH_CALENDAR_TOOL_PROVIDERS:
        token = await TokenManager.get_valid_access_token(db, row)
        g = GraphClient(token)
        raw = await g.list_calendars(top=int(args.get("max_results") or 50))
        items = []

