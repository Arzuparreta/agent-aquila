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
        for it in raw.get("value") or []:
            if isinstance(it, dict):
                items.append(
                    {
                        "summary": it.get("name"),
                        "calendar_id": it.get("id"),
                        "calendar_url": None,
                    }
                )
        return {"provider": prov, "items": items}
    return {"error": f"list_calendars not implemented for provider {prov}"}


@staticmethod
async def _tool_calendar_list_events(
    db: AsyncSession, user: User, args: dict[str, Any]
) -> dict[str, Any]:
    row = await _resolve_connection(db, user, args, CALENDAR_TOOL_PROVIDERS, label="calendar")
    prov = row.provider
    time_min = args.get("time_min")
    if time_min is None:
        time_min = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    time_max = args.get("time_max")
    max_results = int(args.get("max_results") or 50)

    if prov in ("google_calendar", "gcal"):
        client = await _calendar_client(db, row)
        return await client.list_events(
            str(args.get("calendar_id") or "primary"),
            page_token=args.get("page_token"),

            max_results=min(max(max_results, 1), 250),
            time_min=str(time_min),
            time_max=str(time_max) if time_max else None,
            order_by="startTime",
        )

    if prov == "icloud_caldav":
        client = _icloud_caldav_client(row)

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

