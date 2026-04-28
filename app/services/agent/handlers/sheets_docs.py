from __future__ import annotations
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.connector_connection import ConnectorConnection
from app.models.user import User
from app.services.agent.runtime_clients import GoogleSheetsClient, GoogleDocsClient

# From agent_service.py (Phase 5 refactor)

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

