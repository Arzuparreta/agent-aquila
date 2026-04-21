"""WebSocket endpoint for agent run events (Redis-fan-out from :mod:`app.services.ws_broker`)."""

from __future__ import annotations

import contextlib
import logging

from fastapi import APIRouter, Query, WebSocket
from starlette.websockets import WebSocketDisconnect
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import decode_token
from app.models.user import User
from app.services.ws_broker import ws_manager

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws")
async def agent_events_websocket(
    websocket: WebSocket,
    token: str | None = Query(default=None),
) -> None:
    """Browser WebSocket; authenticate with ``?token=<JWT>`` (no header on WS in browsers).

    Messages are JSON strings pushed from the server; clients may send ``ping`` text to
    keep proxies from closing idle connections.
    """
    if not token or not (payload := decode_token(token)) or "sub" not in payload:
        await websocket.close(code=1008, reason="Unauthorized")
        return

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.email == payload["sub"]))
        user = result.scalar_one_or_none()
    if not user:
        await websocket.close(code=1008, reason="User not found")
        return

    await websocket.accept()
    await ws_manager.connect(int(user.id), websocket)
    try:
        while True:
            try:
                msg = await websocket.receive_text()
            except WebSocketDisconnect:
                break
            if msg.strip().lower() == "ping":
                with contextlib.suppress(Exception):
                    await websocket.send_text("pong")
    finally:
        await ws_manager.disconnect(int(user.id), websocket)
