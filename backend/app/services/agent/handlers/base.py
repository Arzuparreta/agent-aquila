"""Handler base utilities — @provider_connection decorator and shared types."""

from __future__ import annotations

import logging
from functools import wraps
from typing import Any, Callable, Awaitable

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connector_connection import ConnectorConnection
from app.models.user import User
from app.services.agent.connection import _resolve_connection
from app.services.connector_tool_registry import (
    CALENDAR_TOOL_PROVIDERS,
    DISCORD_TOOL_PROVIDERS,
    DOCS_TOOL_PROVIDERS,
    DRIVE_TOOL_PROVIDERS,
    GITHUB_TOOL_PROVIDERS,
    GMAIL_TOOL_PROVIDERS,
    GRAPH_CALENDAR_TOOL_PROVIDERS,
    ICLOUD_TOOL_PROVIDERS,
    LINEAR_TOOL_PROVIDERS,
    NOTION_TOOL_PROVIDERS,
    OUTLOOK_MAIL_TOOL_PROVIDERS,
    PEOPLE_TOOL_PROVIDERS,
    SHEETS_TOOL_PROVIDERS,
    SLACK_TOOL_PROVIDERS,
    TASKS_TOOL_PROVIDERS,
    TEAMS_TOOL_PROVIDERS,
    TELEGRAM_TOOL_PROVIDERS,
    YOUTUBE_TOOL_PROVIDERS,
)
from app.services.oauth import TokenManager
from app.services.oauth.errors import ConnectorNeedsReauth, OAuthError
from app.services.connectors.gmail_client import GmailAPIError, GmailClient
from app.services.connectors.gcal_client import CalendarAPIError
from app.services.connectors.drive_client import DriveAPIError
from app.services.connectors.google_docs_client import GoogleDocsAPIError
from app.services.connectors.google_sheets_client import GoogleSheetsAPIError
from app.services.connectors.google_tasks_client import GoogleTasksAPIError
from app.services.connectors.google_people_client import GooglePeopleAPIError
from app.services.connectors.graph_client import GraphAPIError, GraphClient
from app.services.connectors.icloud_caldav_client import ICloudCalDAVError, ICloudCalDAVClient
from app.services.connectors.github_client import GitHubAPIError, GitHubClient
from app.services.connectors.slack_client import SlackAPIError, SlackClient
from app.services.connectors.linear_client import LinearAPIError, LinearClient
from app.services.connectors.notion_client import NotionAPIError, NotionClient
from app.services.connectors.telegram_bot_client import TelegramAPIError, TelegramBotClient
from app.services.connectors.discord_bot_client import DiscordAPIError, DiscordBotClient
from app.services.connectors.web_search_client import WebSearchAPIError
from app.services.connectors.whatsapp_client import WhatsAppAPIError

_logger = logging.getLogger(__name__)

UPSTREAM_ERRORS = (
    GmailAPIError,
    CalendarAPIError,
    DriveAPIError,
    GraphAPIError,
    GoogleTasksAPIError,
    GooglePeopleAPIError,
    GoogleSheetsAPIError,
    GoogleDocsAPIError,
    ICloudCalDAVError,
    GitHubAPIError,
    SlackAPIError,
    LinearAPIError,
    NotionAPIError,
    TelegramAPIError,
    DiscordAPIError,
    WebSearchAPIError,
    WhatsAppAPIError,
)

_PROVIDER_CONFIG: dict[str, tuple[tuple[str, ...], str, Callable]] = {}


def _register(
    key: str,
    providers: tuple[str, ...],
    label: str,
    factory: Callable,
) -> None:
    _PROVIDER_CONFIG[key] = (providers, label, factory)


async def _make_gmail_client(db: AsyncSession, row: ConnectorConnection) -> GmailClient:
    token = await TokenManager.get_valid_access_token(db, row)
    return GmailClient(token)


async def _make_calendar_client(db: AsyncSession, row: ConnectorConnection):
    from app.services.connectors.gcal_client import GoogleCalendarClient
    token = await TokenManager.get_valid_access_token(db, row)
    return GoogleCalendarClient(token)


async def _make_drive_client(db: AsyncSession, row: ConnectorConnection):
    from app.services.connectors.drive_client import GoogleDriveClient
    token = await TokenManager.get_valid_access_token(db, row)
    return GoogleDriveClient(token)


async def _make_sheets_client(db: AsyncSession, row: ConnectorConnection):
    from app.services.connectors.google_sheets_client import GoogleSheetsClient
    token = await TokenManager.get_valid_access_token(db, row)
    return GoogleSheetsClient(token)


async def _make_docs_client(db: AsyncSession, row: ConnectorConnection):
    from app.services.connectors.google_docs_client import GoogleDocsClient
    token = await TokenManager.get_valid_access_token(db, row)
    return GoogleDocsClient(token)


async def _make_tasks_client(db: AsyncSession, row: ConnectorConnection):
    from app.services.connectors.google_tasks_client import GoogleTasksClient
    token = await TokenManager.get_valid_access_token(db, row)
    return GoogleTasksClient(token)


async def _make_people_client(db: AsyncSession, row: ConnectorConnection):
    from app.services.connectors.google_people_client import GooglePeopleClient
    token = await TokenManager.get_valid_access_token(db, row)
    return GooglePeopleClient(token)


async def _make_graph_client(db: AsyncSession, row: ConnectorConnection):
    token = await TokenManager.get_valid_access_token(db, row)
    return GraphClient(token)


async def _make_github_client(db: AsyncSession, row: ConnectorConnection):
    token = await TokenManager.get_valid_access_token(db, row)
    return GitHubClient(token)


async def _make_linear_client(db: AsyncSession, row: ConnectorConnection):
    key = await TokenManager.get_valid_access_token(db, row)
    return LinearClient(key)


async def _make_notion_client(db: AsyncSession, row: ConnectorConnection):
    key = await TokenManager.get_valid_access_token(db, row)
    return NotionClient(key)


async def _make_slack_client(db: AsyncSession, row: ConnectorConnection):
    token, creds, _p = await TokenManager.get_valid_creds(db, row)
    bot = str(creds.get("bot_token") or token or "").strip()
    return SlackClient(bot)


async def _make_telegram_client(db: AsyncSession, row: ConnectorConnection):
    token, creds, _p = await TokenManager.get_valid_creds(db, row)
    bot = str(creds.get("bot_token") or token or "").strip()
    return TelegramBotClient(bot)


async def _make_discord_client(db: AsyncSession, row: ConnectorConnection):
    token, creds, _p = await TokenManager.get_valid_creds(db, row)
    bot = str(creds.get("bot_token") or token or "").strip()
    return DiscordBotClient(bot)


async def _make_icloud_caldav_client(db: AsyncSession, row: ConnectorConnection):
    from app.services.connectors.icloud_caldav_client import ConnectorService
    creds = ConnectorService.decrypt_credentials(row)
    user = str(creds.get("username") or creds.get("apple_id") or "").strip()
    pw = str(creds.get("password") or creds.get("app_password") or "")
    return ICloudCalDAVClient(user, pw)


async def _make_calendar_client_for_row(db: AsyncSession, row: ConnectorConnection):
    """Build the appropriate calendar client based on ``row.provider``."""
    prov = row.provider
    if prov in ("google_calendar", "gcal"):
        from app.services.connectors.gcal_client import GoogleCalendarClient
        token = await TokenManager.get_valid_access_token(db, row)
        return GoogleCalendarClient(token)
    if prov == "icloud_caldav":
        return await _make_icloud_caldav_client(db, row)
    if prov in GRAPH_CALENDAR_TOOL_PROVIDERS:
        token = await TokenManager.get_valid_access_token(db, row)
        return GraphClient(token)
    return await _make_calendar_client(db, row)


_register("gmail", GMAIL_TOOL_PROVIDERS, "Gmail", _make_gmail_client)
_register("calendar", CALENDAR_TOOL_PROVIDERS, "calendar", _make_calendar_client)
_register("drive", DRIVE_TOOL_PROVIDERS, "Google Drive", _make_drive_client)
_register("sheets", SHEETS_TOOL_PROVIDERS, "Google Sheets", _make_sheets_client)
_register("docs", DOCS_TOOL_PROVIDERS, "Google Docs", _make_docs_client)
_register("tasks", TASKS_TOOL_PROVIDERS, "Google Tasks", _make_tasks_client)
_register("people", PEOPLE_TOOL_PROVIDERS, "Google Contacts", _make_people_client)
_register("graph", OUTLOOK_MAIL_TOOL_PROVIDERS, "Outlook", _make_graph_client)
_register("github", GITHUB_TOOL_PROVIDERS, "GitHub", _make_github_client)
_register("slack", SLACK_TOOL_PROVIDERS, "Slack", _make_slack_client)
_register("linear", LINEAR_TOOL_PROVIDERS, "Linear", _make_linear_client)
_register("notion", NOTION_TOOL_PROVIDERS, "Notion", _make_notion_client)
_register("telegram", TELEGRAM_TOOL_PROVIDERS, "Telegram", _make_telegram_client)
_register("discord", DISCORD_TOOL_PROVIDERS, "Discord", _make_discord_client)
_register("icloud_caldav", ICLOUD_TOOL_PROVIDERS, "iCloud", _make_icloud_caldav_client)


def provider_connection(
    provider_key: str,
    *,
    pass_row: bool = False,
) -> Callable:
    """Decorator that resolves a connector connection and builds its client.

    Resolves the provider connection, builds the client via the registered
    factory, and calls the handler with ``(db, user, client, args)``
    — or ``(db, user, client, row, args)`` when ``pass_row=True``
    (needed for cache invalidation via ``row.id``).

    Catches upstream API errors and OAuth errors, returning structured
    error dicts for the model to retry.

    Usage::

        @provider_connection("gmail")
        async def _tool_gmail_list_messages(db, user, client, args):
            return await client.list_messages(...)

        @provider_connection("gmail", pass_row=True)
        async def _tool_gmail_trash_message(db, user, client, row, args):
            result = await client.trash_message(str(args["message_id"]))
            gmail_cache_invalidate_message(row.id, str(args["message_id"]))
            return result
    """
    cfg = _PROVIDER_CONFIG.get(provider_key)
    if cfg is None:
        raise ValueError(f"Unknown provider_key {provider_key!r}")

    providers, label, client_factory = cfg

    def decorator(handler: Callable[..., Awaitable[dict[str, Any]]]):
        @wraps(handler)
        async def wrapper(
            db: AsyncSession,
            user: User,
            args: dict[str, Any],
        ) -> dict[str, Any]:
            row = await _resolve_connection(db, user, args, providers, label=label)
            client = await client_factory(db, row)
            try:
                if pass_row:
                    return await handler(db, user, client, row, args)
                return await handler(db, user, client, args)
            except ConnectorNeedsReauth as exc:
                return {
                    "error": "connector_needs_reauth",
                    "connection_id": exc.connection_id,
                    "provider": exc.provider,
                    "message": str(exc),
                }
            except OAuthError as exc:
                return {"error": f"oauth_error: {exc}"}
            except UPSTREAM_ERRORS as exc:
                return {"error": f"upstream {exc.status_code}: {exc.detail[:300]}"}

        wrapper._provider_key = provider_key
        wrapper._original = handler
        return wrapper

    return decorator


def provider_connection_multi(
    provider_key: str,
    *,
    pass_row: bool = False,
    client_factory_override: Callable | None = None,
) -> Callable:
    """Like @provider_connection but with a custom client factory.

    Use this when a tool domain spans multiple provider types (e.g. calendar
    which can be Google, Graph, or iCloud) and the default factory for
    ``provider_key`` only handles one.

    When ``client_factory_override`` is given it replaces the registered
    factory for this handler only.
    """
    cfg = _PROVIDER_CONFIG.get(provider_key)
    if cfg is None:
        raise ValueError(f"Unknown provider_key {provider_key!r}")

    providers, label, _default_factory = cfg
    factory = client_factory_override or _default_factory

    def decorator(handler: Callable[..., Awaitable[dict[str, Any]]]):
        @wraps(handler)
        async def wrapper(
            db: AsyncSession,
            user: User,
            args: dict[str, Any],
        ) -> dict[str, Any]:
            row = await _resolve_connection(db, user, args, providers, label=label)
            client = await factory(db, row)
            try:
                if pass_row:
                    return await handler(db, user, client, row, args)
                return await handler(db, user, client, args)
            except ConnectorNeedsReauth as exc:
                return {
                    "error": "connector_needs_reauth",
                    "connection_id": exc.connection_id,
                    "provider": exc.provider,
                    "message": str(exc),
                }
            except OAuthError as exc:
                return {"error": f"oauth_error: {exc}"}
            except UPSTREAM_ERRORS as exc:
                return {"error": f"upstream {exc.status_code}: {exc.detail[:300]}"}

        wrapper._provider_key = provider_key
        wrapper._original = handler
        return wrapper

    return decorator


def _parse_label_ids(value: Any) -> list[str] | None:
    """Parse label_ids from args — handles both array and malformed string input."""
    import json

    if value is None:
        return None
    if isinstance(value, list):
        return [str(x) for x in value if x]
    if isinstance(value, str):
        if not value.strip():
            return None
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(x) for x in parsed if x]
        except (json.JSONDecodeError, ValueError):
            pass
        return [value.strip()]
    return None
    if isinstance(value, list):
        return [str(x) for x in value if x]
    if isinstance(value, str):
        if not value.strip():
            return None
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(x) for x in parsed if x]
        except (json.JSONDecodeError, ValueError):
            pass
        return [value.strip()]
    return None
