"""Calendar tool handlers (Google Calendar, Microsoft Graph, iCloud CalDAV)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connector_connection import ConnectorConnection
from app.models.user import User
from app.services.connector_tool_registry import GRAPH_CALENDAR_TOOL_PROVIDERS
from app.services.connectors.graph_client import GraphClient, GraphAPIError

from .base import (
    provider_connection_multi,
    _make_calendar_client_for_row,
    _make_icloud_caldav_client,
)


def _parse_rfc3339_to_utc_datetime(s: str) -> datetime:
    return datetime.fromisoformat(str(s).strip().replace("Z", "+00:00")).astimezone(UTC)


async def _default_icloud_calendar_url(client) -> str:
    cals = await client.list_calendars()
    if not cals:
        raise RuntimeError("no iCloud calendars found on this connection")
    for cal in cals:
        name = str(cal.get("name") or "").lower()
        if "home" in name or name in ("calendar", "personal"):
            return str(cal["url"])
    return str(cals[0]["url"])


@provider_connection_multi("calendar", pass_row=True, client_factory_override=_make_calendar_client_for_row)
async def _tool_calendar_list_calendars(
    db: AsyncSession, user: User, client, row: ConnectorConnection, args: dict[str, Any],
) -> dict[str, Any]:
    prov = row.provider
    if prov in ("google_calendar", "gcal"):
        return await client.list_calendar_list(
            page_token=args.get("page_token"),
            max_results=int(args.get("max_results") or 250),
        )
    if prov == "icloud_caldav":
        cals = await client.list_calendars()
        return {
            "provider": prov,
            "items": [
                {"summary": c.get("name"), "calendar_id": None, "calendar_url": c.get("url")}
                for c in cals
            ],
        }
    if prov in GRAPH_CALENDAR_TOOL_PROVIDERS:
        raw = await client.list_calendars(top=int(args.get("max_results") or 50))
        items = []
        for it in raw.get("value") or []:
            if isinstance(it, dict):
                items.append({
                    "summary": it.get("name"),
                    "calendar_id": it.get("id"),
                    "calendar_url": None,
                })
        return {"provider": prov, "items": items}
    return {"error": f"list_calendars not implemented for provider {prov}"}


@provider_connection_multi("calendar", pass_row=True, client_factory_override=_make_calendar_client_for_row)
async def _tool_calendar_list_events(
    db: AsyncSession, user: User, client, row: ConnectorConnection, args: dict[str, Any],
) -> dict[str, Any]:
    from app.services.user_ai_settings_service import merge_calendar_timezone_from_user_prefs

    prov = row.provider
    time_min = args.get("time_min")
    if time_min is None:
        time_min = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    time_max = args.get("time_max")
    max_results = int(args.get("max_results") or 50)

    if prov in ("google_calendar", "gcal"):
        return await client.list_events(
            str(args.get("calendar_id") or "primary"),
            page_token=args.get("page_token"),
            max_results=min(max(max_results, 1), 250),
            time_min=str(time_min),
            time_max=str(time_max) if time_max else None,
            order_by="startTime",
        )

    if prov == "icloud_caldav":
        cal_url = str(args.get("calendar_url") or args.get("calendar_id") or "").strip()
        if not cal_url:
            cal_url = await _default_icloud_calendar_url(client)
        try:
            start_d = _parse_rfc3339_to_utc_datetime(str(time_min)).date()
        except ValueError:
            start_d = datetime.now(UTC).date()
        if time_max:
            try:
                end_d = _parse_rfc3339_to_utc_datetime(str(time_max)).date()
            except ValueError:
                end_d = start_d
        else:
            end_d = start_d + timedelta(days=30)
        events = await client.list_events(cal_url, start=start_d, end=end_d)
        return {"provider": prov, "calendar_url": cal_url, "events": events}

    if prov in GRAPH_CALENDAR_TOOL_PROVIDERS:
        end_s = str(time_max) if time_max else None
        if not end_s:
            try:
                start_dt = _parse_rfc3339_to_utc_datetime(str(time_min))
            except ValueError:
                start_dt = datetime.now(UTC)
            end_dt = start_dt + timedelta(days=30)
            end_s = end_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            raw = await client.list_calendar_view(
                start_datetime=str(time_min),
                end_datetime=end_s,
                top=min(max(max_results, 1), 250),
            )
        except GraphAPIError as exc:
            return {"provider": prov, "error": exc.detail, "status": exc.status_code}
        return {"provider": prov, "events": raw.get("value") or [], "@odata": raw.get("@odata.nextLink")}

    return {"error": f"unsupported calendar provider: {prov}"}


@provider_connection_multi("calendar", pass_row=True, client_factory_override=_make_calendar_client_for_row)
async def _tool_calendar_create_event(
    db: AsyncSession, user: User, client, row: ConnectorConnection, args: dict[str, Any],
) -> dict[str, Any]:
    from app.services.user_ai_settings_service import merge_calendar_timezone_from_user_prefs
    from app.services.connectors.calendar_adapters import create_calendar_event
    from app.services.oauth import TokenManager

    prov = row.provider
    if prov == "icloud_caldav":
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


@provider_connection_multi("calendar", pass_row=True, client_factory_override=_make_calendar_client_for_row)
async def _tool_calendar_update_event(
    db: AsyncSession, user: User, client, row: ConnectorConnection, args: dict[str, Any],
) -> dict[str, Any]:
    from app.services.user_ai_settings_service import merge_calendar_timezone_from_user_prefs
    from app.services.connectors.calendar_adapters import update_calendar_event
    from app.services.oauth import TokenManager

    if row.provider == "icloud_caldav":
        return {
            "ok": False,
            "error": "iCloud calendar updates are not supported via this tool yet; delete and recreate, or use another calendar client.",
        }
    _token, creds, provider = await TokenManager.get_valid_creds(db, row)
    payload = await merge_calendar_timezone_from_user_prefs(db, user, args)
    return await update_calendar_event(provider, creds, payload)


@provider_connection_multi("calendar", pass_row=True, client_factory_override=_make_calendar_client_for_row)
async def _tool_calendar_delete_event(
    db: AsyncSession, user: User, client, row: ConnectorConnection, args: dict[str, Any],
) -> dict[str, Any]:
    from app.services.connectors.calendar_adapters import delete_calendar_event
    from app.services.oauth import TokenManager

    if row.provider == "icloud_caldav":
        return {
            "ok": False,
            "error": "iCloud calendar deletes are not supported via this tool yet; remove the event in Apple Calendar or another CalDAV client.",
        }
    _token, creds, provider = await TokenManager.get_valid_creds(db, row)
    return await delete_calendar_event(provider, creds, str(args["event_id"]))
