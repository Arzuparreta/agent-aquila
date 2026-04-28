"""Connection utilities."""
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.connector_connection import ConnectorConnection
from app.models.user import User
from app.services.ai_providers import provider_kind_requires_api_key
from app.services.connector_tool_registry import (
    CALENDAR_TOOL_PROVIDERS, DISCORD_TOOL_PROVIDERS, DOCS_TOOL_PROVIDERS,
    DRIVE_TOOL_PROVIDERS, GITHUB_TOOL_PROVIDERS, GMAIL_TOOL_PROVIDERS,
    GRAPH_CALENDAR_TOOL_PROVIDERS, ICLOUD_TOOL_PROVIDERS,
    LINEAR_TOOL_PROVIDERS, NOTION_TOOL_PROVIDERS,
    OUTLOOK_MAIL_TOOL_PROVIDERS, PEOPLE_TOOL_PROVIDERS,
    SHEETS_TOOL_PROVIDERS, SLACK_TOOL_PROVIDERS, TASKS_TOOL_PROVIDERS,
    TEAMS_TOOL_PROVIDERS, TELEGRAM_TOOL_PROVIDERS, YOUTUBE_TOOL_PROVIDERS,
)
from app.services.agent.runtime_clients import (
    DiscordBotClient, GmailClient, GoogleCalendarClient,
    GoogleDocsClient, GoogleDriveClient, GooglePeopleClient,
    GoogleSheetsClient, GoogleTasksClient, GraphClient,
    GitHubClient, ICloudCalDAVClient, LinearClient,
    NotionClient, SlackClient, TelegramBotClient, YoutubeClient,
    create_calendar_event, delete_calendar_event, update_calendar_event,
    share_file, upload_file, provider_kind_requires_api_key,
)

async def _resolve_connection(
    db: AsyncSession, user: User, args: dict[str, Any],
    providers: tuple[str, ...], *, label: str,
) -> ConnectorConnection:
    """Pick connector connection for a tool call."""
    from app.services.connector_service import get_connection_for_user
    cid = args.get("connection_id")
    if cid is not None:
        row = await db.get(ConnectorConnection, int(cid))
        if not row or row.user_id != user.id:
            raise RuntimeError(f"connection {cid} not found")
        if row.provider not in providers:
            raise RuntimeError(f"connection {cid} is not a {label} connection")
        return row
    row = await get_connection_for_user(db, user.id, providers)
    if row is None:
        raise RuntimeError(f"no {label} connection — connect one in Settings → Connectors")
    return row
