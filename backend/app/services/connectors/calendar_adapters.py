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


async def update_calendar_event(
    provider: str, creds: dict[str, Any], payload: dict[str, Any], *, dry_run: bool = False
) -> dict[str, Any]:
    """PATCH an existing event. Requires `event_id` in payload; other fields are optional."""
    token = creds.get("access_token") or creds.get("token")
    event_id = str(payload.get("event_id") or payload.get("provider_event_id") or "")
    if not event_id:
        return {"ok": False, "error": "event_id required"}
    if not token and provider != "mock_calendar":
        return {"ok": False, "error": "missing access_token"}
    if dry_run:
        return {"ok": True, "dry_run": True, "provider": provider, "event_id": event_id, "patch": payload}

    if provider in ("google_calendar", "gcal"):
        body: dict[str, Any] = {}
        if payload.get("summary") or payload.get("title"):
            body["summary"] = str(payload.get("summary") or payload.get("title"))
        if payload.get("description") is not None:
            body["description"] = str(payload["description"])
        if payload.get("start_iso"):
            body["start"] = {
                "dateTime": str(payload["start_iso"]),
                "timeZone": str(payload.get("timezone") or "UTC"),
            }
        if payload.get("end_iso"):
            body["end"] = {
                "dateTime": str(payload["end_iso"]),
                "timeZone": str(payload.get("timezone") or "UTC"),
            }
        if not body:
            return {"ok": False, "error": "nothing to patch"}
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.patch(
                f"{GOOGLE_EVENTS}/{event_id}",
                json=body,
                headers={"Authorization": f"Bearer {token}"},
            )
        if r.status_code >= 300:
            return {"ok": False, "status": r.status_code, "detail": r.text[:500]}
        return {"ok": True, "event": r.json()}

    if provider in ("graph_calendar", "microsoft_calendar", "outlook_calendar"):
        body = {}
        if payload.get("summary") or payload.get("title"):
            body["subject"] = str(payload.get("summary") or payload.get("title"))
        if payload.get("description") is not None:
            body["body"] = {"contentType": "text", "content": str(payload["description"])}
        if payload.get("start_iso"):
            body["start"] = {"dateTime": str(payload["start_iso"]), "timeZone": str(payload.get("timezone") or "UTC")}
        if payload.get("end_iso"):
            body["end"] = {"dateTime": str(payload["end_iso"]), "timeZone": str(payload.get("timezone") or "UTC")}
        if not body:
            return {"ok": False, "error": "nothing to patch"}
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.patch(
                f"https://graph.microsoft.com/v1.0/me/events/{event_id}",
                json=body,
                headers={"Authorization": f"Bearer {token}"},
            )
        if r.status_code >= 300:
            return {"ok": False, "status": r.status_code, "detail": r.text[:500]}
        return {"ok": True, "event": r.json()}

    if provider == "mock_calendar":
        return {"ok": True, "mock": True, "event_id": event_id, "patch": payload}
    return {"ok": False, "error": f"unsupported provider: {provider}"}


async def delete_calendar_event(
    provider: str, creds: dict[str, Any], event_id: str, *, dry_run: bool = False
) -> dict[str, Any]:
    token = creds.get("access_token") or creds.get("token")
    if not token and provider != "mock_calendar":
        return {"ok": False, "error": "missing access_token"}
    if dry_run:
        return {"ok": True, "dry_run": True, "event_id": event_id}
    if provider in ("google_calendar", "gcal"):
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.delete(
                f"{GOOGLE_EVENTS}/{event_id}", headers={"Authorization": f"Bearer {token}"}
            )
        if r.status_code >= 300:
            return {"ok": False, "status": r.status_code, "detail": r.text[:500]}
        return {"ok": True}
    if provider in ("graph_calendar", "microsoft_calendar", "outlook_calendar"):
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.delete(
                f"https://graph.microsoft.com/v1.0/me/events/{event_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
        if r.status_code >= 300:
            return {"ok": False, "status": r.status_code, "detail": r.text[:500]}
        return {"ok": True}
    if provider == "mock_calendar":
        return {"ok": True, "mock": True}
    return {"ok": False, "error": f"unsupported provider: {provider}"}
