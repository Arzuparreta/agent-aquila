"""Miscellaneous tool handlers — device, connectors, time, web."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.user import User
from app.services.device_ingest_service import DeviceIngestService
from app.services.connectors.web_search_client import WebSearchClient
from app.services.user_ai_settings_service import UserAISettingsService
from app.services.user_time_context import session_time_result


# ---------------------------------------------------------------------------
# Device files
# ---------------------------------------------------------------------------

async def _tool_device_list_ingested_files(
    db: AsyncSession, user: User, args: dict[str, Any],
) -> dict[str, Any]:
    return {
        "items": await DeviceIngestService.list_recent(
            db, user, limit=int(args.get("limit") or 50),
        )
    }


async def _tool_device_get_ingested_file(
    db: AsyncSession, user: User, args: dict[str, Any],
) -> dict[str, Any]:
    return await DeviceIngestService.get_for_agent(
        db, user, int(args.get("ingest_id") or 0),
    )


# ---------------------------------------------------------------------------
# Connector introspection
# ---------------------------------------------------------------------------

async def _tool_list_connectors(
    db: AsyncSession, user: User, args: dict[str, Any],
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


# ---------------------------------------------------------------------------
# Session time
# ---------------------------------------------------------------------------

async def _tool_get_session_time(
    db: AsyncSession, user: User, args: dict[str, Any],
) -> dict[str, Any]:
    del args
    prefs = await UserAISettingsService.get_or_create(db, user)
    return session_time_result(
        user_timezone=getattr(prefs, "user_timezone", None),
        time_format=getattr(prefs, "time_format", None) or "auto",
    )


# ---------------------------------------------------------------------------
# Web search/fetch
# ---------------------------------------------------------------------------

async def _tool_web_search(
    db: AsyncSession, user: User, args: dict[str, Any],
) -> dict[str, Any]:
    del db, user
    if not bool(settings.web_search_enabled):
        return {"error": "web_search is disabled by server config"}
    query = str(args.get("query") or "").strip()
    if not query:
        return {"error": "query is required"}
    max_results = min(
        max(int(args.get("max_results") or settings.web_search_max_results or 8), 1),
        20,
    )
    client = WebSearchClient()
    return await client.search(query, max_results=max_results)


async def _tool_web_fetch(
    db: AsyncSession, user: User, args: dict[str, Any],
) -> dict[str, Any]:
    del db, user
    if not bool(settings.web_search_enabled):
        return {"error": "web_search/web_fetch is disabled by server config"}
    url = str(args.get("url") or "").strip()
    if not url:
        return {"error": "url is required"}
    max_chars_raw = args.get("max_chars")
    max_chars = int(max_chars_raw) if max_chars_raw is not None else None
    client = WebSearchClient()
    return await client.fetch_url(url, max_chars=max_chars)


# ---------------------------------------------------------------------------
# Connector setup
# ---------------------------------------------------------------------------

async def _tool_start_connector_setup(
    db: AsyncSession, user: User, args: dict[str, Any],
) -> dict[str, Any]:
    from app.services.connector_setup_service import start_setup
    return await start_setup(db, user, str(args.get("provider") or ""))


async def _tool_submit_connector_credentials(
    db: AsyncSession, user: User, args: dict[str, Any],
) -> dict[str, Any]:
    from app.services.connector_setup_service import submit_credentials
    token = str(args.get("setup_token") or "").strip()
    cid = str(args.get("client_id") or "").strip()
    secret = str(args.get("client_secret") or "").strip()
    if not (token and cid and secret):
        return {"error": "setup_token, client_id and client_secret are required"}
    return await submit_credentials(
        db, user,
        setup_token=token,
        client_id=cid,
        client_secret=secret,
        redirect_uri=args.get("redirect_uri"),
        tenant=args.get("tenant"),
    )


async def _tool_start_oauth_flow(
    db: AsyncSession, user: User, args: dict[str, Any],
) -> dict[str, Any]:
    from app.services.connector_setup_service import start_oauth
    from app.services.agent.handlers.loop import _agent_ctx
    ctx = _agent_ctx.get()
    redirect_base = (ctx.get("oauth_redirect_base") or "") if ctx else ""
    return await start_oauth(
        db, user,
        provider=str(args.get("provider") or ""),
        service=str(args.get("service") or "all"),
        redirect_base=redirect_base,
    )
