"""Gmail tool handlers."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.services.connectors.gmail_client import GmailClient
from app.services.gmail_metadata_cache import (
    get_message_metadata,
    get_thread as gmail_cache_get_thread,
    invalidate_connection as gmail_cache_invalidate_connection,
    invalidate_message as gmail_cache_invalidate_message,
    put_message_metadata,
    put_thread as gmail_cache_put_thread,
)

from .base import provider_connection, _parse_label_ids


# ---------------------------------------------------------------------------
# Simple read handlers (no cache invalidation needed)
# ---------------------------------------------------------------------------

@provider_connection("gmail")
async def _tool_gmail_list_messages(
    db: AsyncSession, user: User, client: GmailClient, args: dict[str, Any],
) -> dict[str, Any]:
    return await client.list_messages(
        page_token=args.get("page_token"),
        q=args.get("q"),
        label_ids=args.get("label_ids"),
        max_results=int(args.get("max_results") or 25),
    )


@provider_connection("gmail", pass_row=True)
async def _tool_gmail_get_message(
    db: AsyncSession, user: User, client: GmailClient, row, args: dict[str, Any],
) -> dict[str, Any]:
    mid = str(args["message_id"])
    fmt = str(args.get("format") or "full")
    if fmt == "metadata":
        cached = get_message_metadata(row.id, mid)
        if cached is not None:
            return cached
    payload = await client.get_message(mid, format=fmt)
    if fmt == "metadata":
        put_message_metadata(row.id, mid, payload)
    return payload


@provider_connection("gmail", pass_row=True)
async def _tool_gmail_get_thread(
    db: AsyncSession, user: User, client: GmailClient, row, args: dict[str, Any],
) -> dict[str, Any]:
    tid = str(args["thread_id"])
    fmt = str(args.get("format") or "metadata")
    if fmt == "metadata":
        cached = gmail_cache_get_thread(row.id, tid, fmt)
        if cached is not None:
            return cached
    payload = await client.get_thread(tid, format=fmt)
    if fmt == "metadata":
        gmail_cache_put_thread(row.id, tid, fmt, payload)
    return payload


@provider_connection("gmail")
async def _tool_gmail_list_labels(
    db: AsyncSession, user: User, client: GmailClient, args: dict[str, Any],
) -> dict[str, Any]:
    return await client.list_labels()


@provider_connection("gmail")
async def _tool_gmail_list_filters(
    db: AsyncSession, user: User, client: GmailClient, args: dict[str, Any],
) -> dict[str, Any]:
    return await client.list_filters()


# ---------------------------------------------------------------------------
# Mutation handlers (need row for cache invalidation)
# ---------------------------------------------------------------------------

@provider_connection("gmail", pass_row=True)
async def _tool_gmail_modify_message(
    db: AsyncSession, user: User, client: GmailClient, row, args: dict[str, Any],
) -> dict[str, Any]:
    mid = str(args["message_id"])
    add_label_ids = _parse_label_ids(args.get("add_label_ids"))
    remove_label_ids = _parse_label_ids(args.get("remove_label_ids"))
    result = await client.modify_message(
        mid,
        add_label_ids=add_label_ids,
        remove_label_ids=remove_label_ids,
    )
    gmail_cache_invalidate_message(row.id, mid)
    return result


@provider_connection("gmail", pass_row=True)
async def _tool_gmail_modify_thread(
    db: AsyncSession, user: User, client: GmailClient, row, args: dict[str, Any],
) -> dict[str, Any]:
    add_label_ids = _parse_label_ids(args.get("add_label_ids"))
    remove_label_ids = _parse_label_ids(args.get("remove_label_ids"))
    result = await client.modify_thread(
        str(args["thread_id"]),
        add_label_ids=add_label_ids,
        remove_label_ids=remove_label_ids,
    )
    gmail_cache_invalidate_connection(row.id)
    return result


@provider_connection("gmail", pass_row=True)
async def _tool_gmail_trash_message(
    db: AsyncSession, user: User, client: GmailClient, row, args: dict[str, Any],
) -> dict[str, Any]:
    mid = str(args["message_id"])
    result = await client.trash_message(mid)
    gmail_cache_invalidate_message(row.id, mid)
    return result


@provider_connection("gmail", pass_row=True)
async def _tool_gmail_untrash_message(
    db: AsyncSession, user: User, client: GmailClient, row, args: dict[str, Any],
) -> dict[str, Any]:
    mid = str(args["message_id"])
    result = await client.untrash_message(mid)
    gmail_cache_invalidate_message(row.id, mid)
    return result


@provider_connection("gmail", pass_row=True)
async def _tool_gmail_trash_thread(
    db: AsyncSession, user: User, client: GmailClient, row, args: dict[str, Any],
) -> dict[str, Any]:
    result = await client.trash_thread(str(args["thread_id"]))
    gmail_cache_invalidate_connection(row.id)
    return result


@provider_connection("gmail", pass_row=True)
async def _tool_gmail_untrash_thread(
    db: AsyncSession, user: User, client: GmailClient, row, args: dict[str, Any],
) -> dict[str, Any]:
    result = await client.untrash_thread(str(args["thread_id"]))
    gmail_cache_invalidate_connection(row.id)
    return result


@provider_connection("gmail", pass_row=True)
async def _tool_gmail_trash_bulk_query(
    db: AsyncSession, user: User, client: GmailClient, row, args: dict[str, Any],
) -> dict[str, Any]:
    q = str(args.get("q") or "in:inbox")
    cap = min(max(int(args.get("max_messages") or 50_000), 1), 250_000)
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


@provider_connection("gmail", pass_row=True)
async def _tool_gmail_mark_read(
    db: AsyncSession, user: User, client: GmailClient, row, args: dict[str, Any],
) -> dict[str, Any]:
    if args.get("thread_id"):
        out = await client.modify_thread(
            str(args["thread_id"]), remove_label_ids=["UNREAD"],
        )
        gmail_cache_invalidate_connection(row.id)
        return out
    if args.get("message_id"):
        mid = str(args["message_id"])
        out = await client.modify_message(mid, remove_label_ids=["UNREAD"])
        gmail_cache_invalidate_message(row.id, mid)
        return out
    return {"error": "either message_id or thread_id is required"}


@provider_connection("gmail", pass_row=True)
async def _tool_gmail_mark_unread(
    db: AsyncSession, user: User, client: GmailClient, row, args: dict[str, Any],
) -> dict[str, Any]:
    if args.get("thread_id"):
        out = await client.modify_thread(
            str(args["thread_id"]), add_label_ids=["UNREAD"],
        )
        gmail_cache_invalidate_connection(row.id)
        return out
    if args.get("message_id"):
        mid = str(args["message_id"])
        out = await client.modify_message(mid, add_label_ids=["UNREAD"])
        gmail_cache_invalidate_message(row.id, mid)
        return out
    return {"error": "either message_id or thread_id is required"}


@provider_connection("gmail", pass_row=True)
async def _tool_gmail_silence_sender(
    db: AsyncSession, user: User, client: GmailClient, row, args: dict[str, Any],
) -> dict[str, Any]:
    """Create a skip-inbox filter; optionally move one thread/msg to Spam."""
    email = str(args.get("email") or "").strip()
    if not email:
        return {"error": "email (sender address) is required"}
    mode = str(args.get("mode") or "mute").lower()
    if mode not in ("mute", "spam"):
        return {"error": "mode must be 'mute' or 'spam'"}
    criteria = {"from": email}
    action: dict[str, Any] = {"removeLabelIds": ["INBOX", "UNREAD"]}
    moved_to_spam = False
    if mode == "spam":
        tid = args.get("thread_id")
        mid = args.get("message_id")
        if tid:
            await client.modify_thread(
                str(tid), add_label_ids=["SPAM"], remove_label_ids=["INBOX"],
            )
            gmail_cache_invalidate_connection(row.id)
            moved_to_spam = True
        elif mid:
            m = str(mid)
            await client.modify_message(
                m, add_label_ids=["SPAM"], remove_label_ids=["INBOX"],
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


@provider_connection("gmail")
async def _tool_gmail_create_filter(
    db: AsyncSession, user: User, client: GmailClient, args: dict[str, Any],
) -> dict[str, Any]:
    criteria = args.get("criteria") or {}
    action = args.get("action") or {}
    if not criteria or not action:
        return {"error": "both criteria and action are required"}
    return await client.create_filter(criteria=criteria, action=action)


@provider_connection("gmail")
async def _tool_gmail_delete_filter(
    db: AsyncSession, user: User, client: GmailClient, args: dict[str, Any],
) -> dict[str, Any]:
    return await client.delete_filter(str(args["filter_id"]))
