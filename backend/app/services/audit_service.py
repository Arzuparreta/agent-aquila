from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog


async def create_audit_log(
    db: AsyncSession,
    entity_type: str,
    entity_id: int,
    action: str,
    changes: dict[str, Any] | None = None,
    user_id: int | None = None,
) -> AuditLog:
    log = AuditLog(
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        changes=changes,
        user_id=user_id,
    )
    db.add(log)
    await db.flush()
    return log
