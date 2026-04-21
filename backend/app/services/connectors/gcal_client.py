"""Thin Google Calendar REST client with retry/backoff. Mirror path only; writes use
`calendar_adapters.create_calendar_event`.
"""
from __future__ import annotations

import asyncio
import random
from typing import Any

import httpx

BASE = "https://www.googleapis.com/calendar/v3"


class CalendarAPIError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Calendar API {status_code}: {detail[:500]}")


class GoogleCalendarClient:
    def __init__(self, access_token: str, *, timeout: float = 60.0) -> None:
        self._token = access_token
        self._timeout = timeout

    async def _request(
        self, method: str, path: str, *, params: dict[str, Any] | None = None, json: Any | None = None
    ) -> dict[str, Any]:
        url = f"{BASE}{path}"
        backoff = 1.0
        for _ in range(5):
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.request(
                    method,
                    url,
                    params=params,
                    json=json,
                    headers={"Authorization": f"Bearer {self._token}"},
                )
            if resp.status_code == 429 or resp.status_code >= 500:
                wait = float(resp.headers.get("Retry-After") or 0) or backoff + random.uniform(0, 0.5)
                await asyncio.sleep(min(wait, 30.0))
                backoff = min(backoff * 2, 30.0)
                continue
            if resp.status_code >= 400:
                raise CalendarAPIError(resp.status_code, resp.text)
            if not resp.content:
                return {}
            return resp.json()
        raise CalendarAPIError(503, "Calendar API retries exhausted")

    async def list_events(
        self,
        calendar_id: str = "primary",
        *,
        page_token: str | None = None,
        sync_token: str | None = None,
        max_results: int = 250,
        show_deleted: bool = True,
        time_min: str | None = None,
        time_max: str | None = None,
        order_by: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"maxResults": max_results, "showDeleted": "true" if show_deleted else "false"}
        if page_token:
            params["pageToken"] = page_token
        if sync_token:
            params["syncToken"] = sync_token
        else:
            # First full sync: singleEvents=true expands recurrences, much easier to mirror.
            params["singleEvents"] = "true"
        if time_min:
            params["timeMin"] = time_min
        if time_max:
            params["timeMax"] = time_max
        # Google requires orderBy=startTime when filtering by time window for single events.
        if order_by:
            params["orderBy"] = order_by
        return await self._request("GET", f"/calendars/{calendar_id}/events", params=params)

    async def get_event(self, event_id: str, calendar_id: str = "primary") -> dict[str, Any]:
        return await self._request("GET", f"/calendars/{calendar_id}/events/{event_id}")
