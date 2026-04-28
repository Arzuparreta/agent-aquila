from __future__ import annotations
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.connector_connection import ConnectorConnection
from app.models.user import User
from app.services.agent.runtime_clients import GitHubClient, LinearClient, NotionClient

# From agent_service.py (Phase 5 refactor)

    return payload

@staticmethod
async def _tool_gmail_list_labels(
    db: AsyncSession, user: User, args: dict[str, Any]
) -> dict[str, Any]:
    row = await _resolve_connection(db, user, args, GMAIL_TOOL_PROVIDERS, label="Gmail")
    client = await _gmail_client(db, row)
    return await client.list_labels()

@staticmethod
async def _tool_gmail_list_filters(

    db: AsyncSession, user: User, args: dict[str, Any]
) -> dict[str, Any]:
    row = await _resolve_connection(db, user, args, GMAIL_TOOL_PROVIDERS, label="Gmail")
    client = await _gmail_client(db, row)
    return await client.list_filters()

@staticmethod
def _parse_label_ids(value: Any) -> list[str] | None:
    """Parse label_ids from args - handles both array and malformed string input."""
    if value is None:
        return None
    if isinstance(value, list):
        return [str(x) for x in value if x]
    if isinstance(value, str):
        if not value.strip():
            return None
        try:
            parsed = json.loads(value)

@staticmethod
async def _tool_gmail_modify_thread(
    db: AsyncSession, user: User, args: dict[str, Any]
) -> dict[str, Any]:
    row = await _resolve_connection(db, user, args, GMAIL_TOOL_PROVIDERS, label="Gmail")
    client = await _gmail_client(db, row)
    add_label_ids = AgentService._parse_label_ids(args.get("add_label_ids"))
    remove_label_ids = AgentService._parse_label_ids(args.get("remove_label_ids"))
    result = await client.modify_thread(

        str(args["thread_id"]),
        add_label_ids=add_label_ids,
        remove_label_ids=remove_label_ids,
    )
    gmail_cache_invalidate_connection(row.id)
    return result

@staticmethod

async def _tool_gmail_trash_message(
    db: AsyncSession, user: User, args: dict[str, Any]
) -> dict[str, Any]:
    row = await _resolve_connection(db, user, args, GMAIL_TOOL_PROVIDERS, label="Gmail")
    client = await _gmail_client(db, row)
    mid = str(args["message_id"])
    result = await client.trash_message(mid)
    gmail_cache_invalidate_message(row.id, mid)
    return result

@staticmethod

async def _tool_gmail_untrash_message(
    db: AsyncSession, user: User, args: dict[str, Any]
) -> dict[str, Any]:
    row = await _resolve_connection(db, user, args, GMAIL_TOOL_PROVIDERS, label="Gmail")
    client = await _gmail_client(db, row)
    mid = str(args["message_id"])
    result = await client.untrash_message(mid)
    gmail_cache_invalidate_message(row.id, mid)

