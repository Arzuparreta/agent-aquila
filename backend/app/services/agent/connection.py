"""Connection resolution utility."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connector_connection import ConnectorConnection
from app.models.user import User


async def _resolve_connection(
    db: AsyncSession, user: User, args: dict[str, Any],
    providers: tuple[str, ...], *, label: str,
) -> ConnectorConnection:
    """Pick connector connection for a tool call."""
    from app.services.connector_service import get_connection_for_user

    cid = args.get("connection_id")
    if cid is not None:
        row = await db.get(ConnectorConnection, int(cid))
        if not row or row.user_id != user.id:
            raise RuntimeError(f"connection {cid} not found")
        if row.provider not in providers:
            raise RuntimeError(f"connection {cid} is not a {label} connection")
        return row

    row = await get_connection_for_user(db, user.id, providers)
    if row is None:
        raise RuntimeError(f"no {label} connection — connect one in Settings → Connectors")
    return row
