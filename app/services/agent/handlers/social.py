from __future__ import annotations
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.connector_connection import ConnectorConnection
from app.models.user import User
from app.services.agent.runtime_clients import SlackClient, TelegramBotClient, DiscordBotClient

# From agent_service.py (Phase 5 refactor)

            if isinstance(parsed, list):
                return [str(x) for x in parsed if x]
        except (json.JSONDecodeError, ValueError):
            pass
        return [value.strip()]
    return None

@staticmethod
async def _tool_gmail_modify_message(
    db: AsyncSession, user: User, args: dict[str, Any]
) -> dict[str, Any]:
    row = await _resolve_connection(db, user, args, GMAIL_TOOL_PROVIDERS, label="Gmail")

    client = await _gmail_client(db, row)
    mid = str(args["message_id"])
    add_label_ids = AgentService._parse_label_ids(args.get("add_label_ids"))
    remove_label_ids = AgentService._parse_label_ids(args.get("remove_label_ids"))
    result = await client.modify_message(
        mid,
        add_label_ids=add_label_ids,
        remove_label_ids=remove_label_ids,
    )
    gmail_cache_invalidate_message(row.id, mid)
    return result


    return result

@staticmethod
async def _tool_gmail_trash_thread(
    db: AsyncSession, user: User, args: dict[str, Any]
) -> dict[str, Any]:
    row = await _resolve_connection(db, user, args, GMAIL_TOOL_PROVIDERS, label="Gmail")
    client = await _gmail_client(db, row)

    result = await client.trash_thread(str(args["thread_id"]))
    gmail_cache_invalidate_connection(row.id)
    return result

@staticmethod
async def _tool_gmail_untrash_thread(
    db: AsyncSession, user: User, args: dict[str, Any]
) -> dict[str, Any]:
    row = await _resolve_connection(db, user, args, GMAIL_TOOL_PROVIDERS, label="Gmail")
    client = await _gmail_client(db, row)
    result = await client.untrash_thread(str(args["thread_id"]))
    gmail_cache_invalidate_connection(row.id)

    return result

@staticmethod
async def _tool_gmail_trash_bulk_query(
    db: AsyncSession, user: User, args: dict[str, Any]
) -> dict[str, Any]:
    row = await _resolve_connection(db, user, args, GMAIL_TOOL_PROVIDERS, label="Gmail")
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


@staticmethod
async def _tool_gmail_mark_unread(
    db: AsyncSession, user: User, args: dict[str, Any]
) -> dict[str, Any]:
    row = await _resolve_connection(db, user, args, GMAIL_TOOL_PROVIDERS, label="Gmail")
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

