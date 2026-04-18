from __future__ import annotations

from typing import Any

import httpx

GRAPH_EVENTS = "https://graph.microsoft.com/v1.0/me/events"
GOOGLE_EVENTS = "https://www.googleapis.com/calendar/v3/calendars/primary/events"


async def create_calendar_event(
    provider: str, creds: dict[str, Any], payload: dict[str, Any], *, dry_run: bool = False
) -> dict[str, Any]:
    token = creds.get("access_token") or creds.get("token")
    if not token and provider != "mock_calendar":
        return {"ok": False, "error": "missing access_token in connection credentials"}

    summary = str(payload.get("summary") or payload.get("title") or "Event")
    start = str(payload.get("start_iso") or payload.get("start") or "")
    end = str(payload.get("end_iso") or payload.get("end") or "")
    description = str(payload.get("description") or "")

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "provider": provider,
            "summary": summary,
            "start": start,
            "end": end,
        }

    if provider in ("graph_calendar", "microsoft_calendar", "outlook_calendar"):
        body = {
            "subject": summary,
            "body": {"contentType": "text", "content": description},
            "start": {"dateTime": start, "timeZone": str(payload.get("timezone") or "UTC")},
            "end": {"dateTime": end, "timeZone": str(payload.get("timezone") or "UTC")},
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(GRAPH_EVENTS, json=body, headers={"Authorization": f"Bearer {token}"})
        if r.status_code >= 300:
            return {"ok": False, "status": r.status_code, "detail": r.text[:500]}
        return {"ok": True, "event": r.json()}

    if provider in ("google_calendar", "gcal"):
        body = {
            "summary": summary,
            "description": description,
            "start": {"dateTime": start, "timeZone": str(payload.get("timezone") or "UTC")},
            "end": {"dateTime": end, "timeZone": str(payload.get("timezone") or "UTC")},
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(GOOGLE_EVENTS, json=body, headers={"Authorization": f"Bearer {token}"})
        if r.status_code >= 300:
            return {"ok": False, "status": r.status_code, "detail": r.text[:500]}
        return {"ok": True, "event": r.json()}

    if provider == "mock_calendar":
        return {"ok": True, "mock": True, "summary": summary, "start": start, "end": end}

    return {"ok": False, "error": f"unsupported calendar provider: {provider}"}
