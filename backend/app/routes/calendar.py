"""Live Google Calendar proxy.

Mirrors the design of ``routes/gmail.py``: thin pass-through to the
upstream API, no local mirror. Reads use ``GoogleCalendarClient``;
writes (create/update/delete event) reuse ``calendar_adapters`` so they
run through the same code path as the agent's calendar tools.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.connector_connection import ConnectorConnection
from app.models.user import User
from app.services.connectors.calendar_adapters import (
    create_calendar_event,
    delete_calendar_event,
    update_calendar_event,
)
from app.services.connectors.gcal_client import CalendarAPIError, GoogleCalendarClient
from app.services.oauth import TokenManager
from app.services.oauth.errors import ConnectorNeedsReauth, OAuthError
from app.services.user_ai_settings_service import merge_calendar_timezone_from_user_prefs

router = APIRouter(prefix="/calendar", tags=["calendar"], dependencies=[Depends(get_current_user)])

CAL_PROVIDERS = ("google_calendar", "gcal")


async def _resolve(db: AsyncSession, user: User, connection_id: int | None) -> ConnectorConnection:
    if connection_id is not None:
        row = await db.get(ConnectorConnection, connection_id)
        if not row or row.user_id != user.id:
            raise HTTPException(status_code=404, detail="Connection not found")
        if row.provider not in CAL_PROVIDERS:
            raise HTTPException(status_code=400, detail="Not a Google Calendar connection.")
        return row
    stmt = select(ConnectorConnection).where(
        ConnectorConnection.user_id == user.id,
        ConnectorConnection.provider.in_(CAL_PROVIDERS),
    )
    rows = list((await db.execute(stmt)).scalars().all())
    if not rows:
        raise HTTPException(status_code=400, detail="No Google Calendar connection.")
    if len(rows) > 1:
        raise HTTPException(
            status_code=400,
            detail=f"Multiple connections — pass ?connection_id=... ({', '.join(str(r.id) for r in rows)})",
        )
    return rows[0]


async def _creds(db: AsyncSession, row: ConnectorConnection) -> tuple[str, dict[str, Any], str]:
    try:
        return await TokenManager.get_valid_creds(db, row)
    except ConnectorNeedsReauth as exc:
        raise HTTPException(
            status_code=401,
            detail={"kind": "needs_reauth", "message": str(exc), "connection_id": row.id},
        ) from exc
    except OAuthError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/events")
async def list_events(
    connection_id: int | None = Query(default=None),
    calendar_id: str = Query(default="primary"),
    page_token: str | None = Query(default=None),
    max_results: int = Query(default=50, ge=1, le=250),
    time_min: str | None = Query(
        default=None,
        description="RFC3339 lower bound; defaults to now (UTC) so results are upcoming-first.",
    ),
    time_max: str | None = Query(default=None, description="RFC3339 upper bound (optional)."),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    row = await _resolve(db, current_user, connection_id)
    token, _creds_dict, _provider = await _creds(db, row)
    client = GoogleCalendarClient(token)
    tmin = time_min or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        return await client.list_events(
            calendar_id,
            page_token=page_token,
            max_results=max_results,
            time_min=tmin,
            time_max=time_max,
            order_by="startTime",
        )
    except CalendarAPIError as exc:
        raise HTTPException(status_code=exc.status_code or 502, detail=exc.detail[:500])


@router.post("/events")
async def create_event(
    payload: dict[str, Any] = Body(...),
    connection_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    row = await _resolve(db, current_user, connection_id)
    _token, creds, provider = await _creds(db, row)
    payload = await merge_calendar_timezone_from_user_prefs(db, current_user, payload)
    return await create_calendar_event(provider, creds, payload)


@router.patch("/events/{event_id}")
async def patch_event(
    event_id: str,
    payload: dict[str, Any] = Body(...),
    connection_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    row = await _resolve(db, current_user, connection_id)
    _token, creds, provider = await _creds(db, row)
    merged = await merge_calendar_timezone_from_user_prefs(db, current_user, payload)
    return await update_calendar_event(provider, creds, {**merged, "event_id": event_id})


@router.delete("/events/{event_id}")
async def delete_event(
    event_id: str,
    connection_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    row = await _resolve(db, current_user, connection_id)
    _token, creds, provider = await _creds(db, row)
    return await delete_calendar_event(provider, creds, event_id)
