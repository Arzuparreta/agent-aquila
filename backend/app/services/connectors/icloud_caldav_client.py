"""iCloud CalDAV — calendar list and events via app-specific password."""

from __future__ import annotations

import asyncio
from datetime import date, datetime
from typing import Any

import caldav

ICLOUD_CALDAV_ROOT = "https://caldav.icloud.com/"


class ICloudCalDAVError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"iCloud CalDAV {status_code}: {detail[:500]}")


def _calendar_to_dict(cal: caldav.Calendar) -> dict[str, Any]:
    return {
        "name": getattr(cal, "name", None) or "",
        "url": str(cal.url),
    }


def _event_brief(obj: caldav.Event) -> dict[str, Any]:
    data = getattr(obj, "data", None) or ""
    return {"ical_preview": (data or "")[:1200], "raw_size": len(data or "")}


class ICloudCalDAVClient:
    def __init__(
        self,
        username: str,
        app_password: str,
        *,
        caldav_url: str = ICLOUD_CALDAV_ROOT,
    ) -> None:
        self._username = username.strip()
        self._password = app_password
        self._caldav_url = caldav_url.rstrip("/") + "/"

    def _client(self) -> caldav.DAVClient:
        return caldav.DAVClient(
            url=self._caldav_url,
            username=self._username,
            password=self._password,
        )

    async def list_calendars(self) -> list[dict[str, Any]]:
        def _run() -> list[dict[str, Any]]:
            try:
                client = self._client()
                principal = client.principal()
                cals = principal.calendars()
                return [_calendar_to_dict(c) for c in cals]
            except Exception as exc:
                raise ICloudCalDAVError(400, str(exc)) from exc

        return await asyncio.to_thread(_run)

    async def list_events(
        self,
        calendar_url: str,
        *,
        start: date | datetime | None = None,
        end: date | datetime | None = None,
    ) -> list[dict[str, Any]]:
        start_d = start or date.today()
        end_d = end or date.today()

        def _run() -> list[dict[str, Any]]:
            try:
                client = self._client()
                cal = caldav.Calendar(client=client.client, url=calendar_url)
                found = cal.date_search(start=start_d, end=end_d, expand=False)
                out: list[dict[str, Any]] = []
                for ev in found:
                    brief = _event_brief(ev)
                    brief["calendar_url"] = calendar_url
                    out.append(brief)
                return out
            except Exception as exc:
                raise ICloudCalDAVError(400, str(exc)) from exc

        return await asyncio.to_thread(_run)

    async def create_event(
        self,
        calendar_url: str,
        *,
        summary: str,
        start: datetime,
        end: datetime,
        description: str | None = None,
    ) -> dict[str, Any]:
        uid = f"aquila-{start.timestamp()}".replace(".", "-")

        def _ical() -> str:
            lines = [
                "BEGIN:VCALENDAR",
                "VERSION:2.0",
                "PRODID:-//Agent Aquila//EN",
                "BEGIN:VEVENT",
                f"UID:{uid}",
                f"DTSTAMP:{datetime.now().strftime('%Y%m%dT%H%M%SZ')}",
                f"DTSTART:{start.strftime('%Y%m%dT%H%M%SZ')}",
                f"DTEND:{end.strftime('%Y%m%dT%H%M%SZ')}",
                f"SUMMARY:{summary.replace(chr(10), ' ')}",
            ]
            if description:
                lines.append(f"DESCRIPTION:{description.replace(chr(10), ' ')}")
            lines.extend(["END:VEVENT", "END:VCALENDAR"])
            return "\r\n".join(lines) + "\r\n"

        ical = _ical()

        def _run() -> dict[str, Any]:
            try:
                client = self._client()
                cal = caldav.Calendar(client=client.client, url=calendar_url)
                cal.save_event(ical)
                return {"ok": True, "uid": uid}
            except Exception as exc:
                raise ICloudCalDAVError(400, str(exc)) from exc

        return await asyncio.to_thread(_run)
