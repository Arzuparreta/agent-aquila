"""Automations CRUD + manual test-run. Mounted at /api/v1/automations."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.automation import Automation
from app.models.user import User
from app.schemas.automation import AutomationCreate, AutomationPatch, AutomationRead

router = APIRouter(prefix="/automations", tags=["automations"], dependencies=[Depends(get_current_user)])


def _to_read(row: Automation) -> AutomationRead:
    return AutomationRead.model_validate(row)


@router.get("", response_model=list[AutomationRead])
async def list_automations(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[AutomationRead]:
    r = await db.execute(
        select(Automation).where(Automation.user_id == current_user.id).order_by(Automation.id.desc())
    )
    return [_to_read(row) for row in r.scalars().all()]


@router.post("", response_model=AutomationRead, status_code=status.HTTP_201_CREATED)
async def create_automation(
    payload: AutomationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AutomationRead:
    row = Automation(
        user_id=current_user.id,
        name=payload.name.strip(),
        trigger=payload.trigger,
        conditions=payload.conditions or {},
        prompt_template=payload.prompt_template.strip(),
        default_connection_id=payload.default_connection_id,
        auto_approve=bool(payload.auto_approve),
        enabled=bool(payload.enabled),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _to_read(row)


async def _require(db: AsyncSession, user: User, automation_id: int) -> Automation:
    row = await db.get(Automation, automation_id)
    if not row or row.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Automation not found")
    return row


@router.get("/{automation_id}", response_model=AutomationRead)
async def get_automation(
    automation_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AutomationRead:
    row = await _require(db, current_user, automation_id)
    return _to_read(row)


@router.patch("/{automation_id}", response_model=AutomationRead)
async def patch_automation(
    automation_id: int,
    payload: AutomationPatch,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AutomationRead:
    row = await _require(db, current_user, automation_id)
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(row, field, value)
    await db.commit()
    await db.refresh(row)
    return _to_read(row)


@router.delete("/{automation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_automation(
    automation_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    row = await _require(db, current_user, automation_id)
    await db.delete(row)
    await db.commit()


@router.post("/{automation_id}/run")
async def run_automation_now(
    automation_id: int,
    payload: dict | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Invoke the automation synchronously with a supplied payload (for testing)."""
    from app.services.automation_service import execute_automation

    row = await _require(db, current_user, automation_id)
    result = await execute_automation(db, row.id, dict(payload or {"subject": "test", "body": "manual run"}))
    return result
