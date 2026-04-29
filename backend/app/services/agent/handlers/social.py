"""Social/communication tool handlers — Slack, Telegram, Outlook."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.services.connectors.slack_client import SlackClient
from app.services.connectors.telegram_bot_client import TelegramBotClient
from app.services.connectors.graph_client import GraphClient

from .base import provider_connection


# ---------------------------------------------------------------------------
# Slack
# ---------------------------------------------------------------------------

@provider_connection("slack")
async def _tool_slack_list_conversations(
    db: AsyncSession, user: User, client: SlackClient, args: dict[str, Any],
) -> dict[str, Any]:
    return await client.conversations_list(
        types=str(args.get("types") or "public_channel,private_channel"),
        cursor=args.get("cursor"),
        limit=int(args.get("limit") or 200),
    )


@provider_connection("slack")
async def _tool_slack_get_conversation_history(
    db: AsyncSession, user: User, client: SlackClient, args: dict[str, Any],
) -> dict[str, Any]:
    return await client.conversations_history(
        str(args["channel_id"]),
        limit=int(args.get("limit") or 50),
        cursor=args.get("cursor"),
    )


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------

@provider_connection("telegram")
async def _tool_telegram_get_me(
    db: AsyncSession, user: User, client: TelegramBotClient, args: dict[str, Any],
) -> dict[str, Any]:
    return await client.get_me()


@provider_connection("telegram")
async def _tool_telegram_get_updates(
    db: AsyncSession, user: User, client: TelegramBotClient, args: dict[str, Any],
) -> dict[str, Any]:
    return await client.get_updates(
        offset=int(args.get("offset") or 0),
        limit=min(int(args.get("limit") or 20), 100),
    )


@provider_connection("telegram")
async def _tool_telegram_send_message(
    db: AsyncSession, user: User, client: TelegramBotClient, args: dict[str, Any],
) -> dict[str, Any]:
    cid = str(args["chat_id"])
    text = str(args["text"])
    return await client.send_message(cid, text[:4096])


# ---------------------------------------------------------------------------
# Outlook (Graph)
# ---------------------------------------------------------------------------

@provider_connection("graph")
async def _tool_outlook_list_messages(
    db: AsyncSession, user: User, client: GraphClient, args: dict[str, Any],
) -> dict[str, Any]:
    return await client.messages_delta(top=int(args.get("top") or 25))


@provider_connection("graph")
async def _tool_outlook_get_message(
    db: AsyncSession, user: User, client: GraphClient, args: dict[str, Any],
) -> dict[str, Any]:
    return await client.get_message(str(args["message_id"]))
