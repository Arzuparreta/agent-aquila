"""Live Microsoft Teams (Graph) proxy.

Today this only exposes the minimum the agent needs: list joined teams,
list channels in a team, and post a message to a channel. Reads/writes
go straight to the Graph API.
"""
from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.connector_connection import ConnectorConnection
from app.models.user import User
from app.services.oauth import TokenManager
from app.services.oauth.errors import ConnectorNeedsReauth, OAuthError

router = APIRouter(prefix="/teams", tags=["teams"], dependencies=[Depends(get_current_user)])

TEAMS_PROVIDERS = ("graph_teams", "ms_teams")
GRAPH_BASE = "https://graph.microsoft.com/v1.0"


async def _resolve(db: AsyncSession, user: User, connection_id: int | None) -> ConnectorConnection:
    if connection_id is not None:
        row = await db.get(ConnectorConnection, connection_id)
        if not row or row.user_id != user.id:
            raise HTTPException(status_code=404, detail="Connection not found")
        if row.provider not in TEAMS_PROVIDERS:
            raise HTTPException(status_code=400, detail="Not a Microsoft Teams connection.")
        return row
    stmt = select(ConnectorConnection).where(
        ConnectorConnection.user_id == user.id,
        ConnectorConnection.provider.in_(TEAMS_PROVIDERS),
    )
    rows = list((await db.execute(stmt)).scalars().all())
    if not rows:
        raise HTTPException(status_code=400, detail="No Microsoft Teams connection.")
    if len(rows) > 1:
        raise HTTPException(
            status_code=400,
            detail=f"Multiple connections — pass ?connection_id=... ({', '.join(str(r.id) for r in rows)})",
        )
    return rows[0]


async def _token(db: AsyncSession, row: ConnectorConnection) -> str:
    try:
        return await TokenManager.get_valid_access_token(db, row)
    except ConnectorNeedsReauth as exc:
        raise HTTPException(
            status_code=401,
            detail={"kind": "needs_reauth", "message": str(exc), "connection_id": row.id},
        ) from exc
    except OAuthError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


async def _request(
    token: str, method: str, path: str, *, json_body: Any | None = None
) -> dict[str, Any]:
    url = path if path.startswith("http") else f"{GRAPH_BASE}{path}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.request(method, url, headers={"Authorization": f"Bearer {token}"}, json=json_body)
    if r.status_code >= 300:
        raise HTTPException(status_code=r.status_code, detail=r.text[:500])
    if not r.content:
        return {}
    return r.json()


@router.get("/teams")
async def list_teams(
    connection_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    row = await _resolve(db, current_user, connection_id)
    token = await _token(db, row)
    return await _request(token, "GET", "/me/joinedTeams")


@router.get("/teams/{team_id}/channels")
async def list_channels(
    team_id: str,
    connection_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    row = await _resolve(db, current_user, connection_id)
    token = await _token(db, row)
    return await _request(token, "GET", f"/teams/{team_id}/channels")


@router.post("/teams/{team_id}/channels/{channel_id}/messages")
async def post_message(
    team_id: str,
    channel_id: str,
    payload: dict[str, Any] = Body(...),
    connection_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    text = str(payload.get("text") or payload.get("body") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="payload.text is required")
    row = await _resolve(db, current_user, connection_id)
    token = await _token(db, row)
    body = {"body": {"contentType": "html", "content": text}}
    return await _request(
        token, "POST", f"/teams/{team_id}/channels/{channel_id}/messages", json_body=body
    )
