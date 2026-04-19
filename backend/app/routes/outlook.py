"""Live Microsoft Outlook (Graph mail) proxy.

Read endpoints use ``GraphClient`` directly; sending falls through
``email_adapters.send_email`` to share the agent code path.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.connector_connection import ConnectorConnection
from app.models.user import User
from app.services.connectors.email_adapters import send_email
from app.services.connectors.graph_client import GraphAPIError, GraphClient
from app.services.oauth import TokenManager
from app.services.oauth.errors import ConnectorNeedsReauth, OAuthError

router = APIRouter(prefix="/outlook", tags=["outlook"], dependencies=[Depends(get_current_user)])

OUTLOOK_PROVIDERS = ("graph_mail",)


async def _resolve(db: AsyncSession, user: User, connection_id: int | None) -> ConnectorConnection:
    if connection_id is not None:
        row = await db.get(ConnectorConnection, connection_id)
        if not row or row.user_id != user.id:
            raise HTTPException(status_code=404, detail="Connection not found")
        if row.provider not in OUTLOOK_PROVIDERS:
            raise HTTPException(status_code=400, detail="Not an Outlook connection.")
        return row
    stmt = select(ConnectorConnection).where(
        ConnectorConnection.user_id == user.id,
        ConnectorConnection.provider.in_(OUTLOOK_PROVIDERS),
    )
    rows = list((await db.execute(stmt)).scalars().all())
    if not rows:
        raise HTTPException(status_code=400, detail="No Outlook (Graph mail) connection.")
    if len(rows) > 1:
        raise HTTPException(
            status_code=400,
            detail=f"Multiple connections — pass ?connection_id=... ({', '.join(str(r.id) for r in rows)})",
        )
    return rows[0]


async def _creds(db: AsyncSession, row: ConnectorConnection):
    try:
        return await TokenManager.get_valid_creds(db, row)
    except ConnectorNeedsReauth as exc:
        raise HTTPException(
            status_code=401,
            detail={"kind": "needs_reauth", "message": str(exc), "connection_id": row.id},
        ) from exc
    except OAuthError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/messages")
async def list_messages(
    connection_id: int | None = Query(default=None),
    top: int = Query(default=25, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    row = await _resolve(db, current_user, connection_id)
    token, _creds_dict, _provider = await _creds(db, row)
    client = GraphClient(token)
    try:
        return await client.messages_delta(top=top)
    except GraphAPIError as exc:
        raise HTTPException(status_code=exc.status_code or 502, detail=exc.detail[:500])


@router.get("/messages/{message_id}")
async def get_message(
    message_id: str,
    connection_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    row = await _resolve(db, current_user, connection_id)
    token, _creds_dict, _provider = await _creds(db, row)
    client = GraphClient(token)
    try:
        return await client.get_message(message_id)
    except GraphAPIError as exc:
        raise HTTPException(status_code=exc.status_code or 502, detail=exc.detail[:500])


@router.post("/send")
async def send(
    payload: dict[str, Any] = Body(...),
    connection_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    to = payload.get("to") or []
    subject = str(payload.get("subject") or "")
    body = str(payload.get("body") or "")
    if not to or not subject:
        raise HTTPException(status_code=400, detail="payload requires 'to' and 'subject'")
    row = await _resolve(db, current_user, connection_id)
    _token, creds, provider = await _creds(db, row)
    return await send_email(
        provider,
        creds,
        list(to),
        subject,
        body,
        content_type=str(payload.get("content_type") or "text"),
    )
