"""Auto-apply path: execute internal CRM writes immediately and record an UNDO trail.

The artist-first plan distinguishes two tiers of agent actions:

- ``auto_apply``: internal CRM writes (contacts/deals/events). They run instantly so the
  conversation feels live; the chat shows a 10-second UNDO countdown. Implemented here.
- ``approval``: external connector actions (send email, calendar invite, file share,
  Teams message, deletes). Continue to use ``ProposalService`` + ``PendingExecutionService``.

This service:
1. Captures a pre-image of the entity for updates (used as ``reversal_payload``).
2. Calls the existing ``PendingExecutionService.execute`` to apply the write.
3. Persists an ``ExecutedAction`` row with the data needed to UNDO.

Undo is implemented in :func:`undo_action`, which inverses the change using the recorded
``reversal_payload``. After ``reversible_until`` passes, undo refuses with HTTP 410.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact import Contact
from app.models.deal import Deal
from app.models.event import Event
from app.models.executed_action import ExecutedAction
from app.models.user import User
from app.schemas.contact import ContactUpdate
from app.schemas.deal import DealUpdate
from app.schemas.event import EventUpdate
from app.services.contact_service import ContactService
from app.services.deal_service import DealService
from app.services.event_service import EventService
from app.services.pending_execution_service import PendingExecutionService

# Default window during which the UNDO endpoint will reverse an auto-applied action.
UNDO_WINDOW_SECONDS = 10

AUTO_APPLY_KINDS: frozenset[str] = frozenset(
    {
        "create_contact",
        "update_contact",
        "create_deal",
        "update_deal",
        "create_event",
        "update_event",
    }
)


def kind_is_auto_apply(kind: str) -> bool:
    return kind in AUTO_APPLY_KINDS


def _serialize_contact(c: Contact) -> dict[str, Any]:
    return {
        "name": c.name,
        "email": c.email,
        "phone": c.phone,
        "role": c.role,
        "notes": c.notes,
    }


def _serialize_deal(d: Deal) -> dict[str, Any]:
    return {
        "title": d.title,
        "status": d.status,
        "amount": float(d.amount) if d.amount is not None else None,
        "currency": d.currency,
        "notes": d.notes,
    }


def _serialize_event(e: Event) -> dict[str, Any]:
    return {
        "venue_name": e.venue_name,
        "event_date": e.event_date.isoformat() if e.event_date else None,
        "deal_id": e.deal_id,
        "city": e.city,
        "status": e.status,
        "notes": e.notes,
    }


async def _capture_pre_image(db: AsyncSession, user: User, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Returns a dict the UNDO logic can replay to revert the action.

    Schema:
      - For creates: ``{"op":"created","entity_type":..., "entity_id":...}`` (filled after exec).
      - For updates: ``{"op":"updated","entity_type":..., "entity_id":..., "before":{...}}``.
    """
    if kind == "update_contact":
        cid = int(payload["contact_id"])
        row = await db.get(Contact, cid)
        if not row:
            raise HTTPException(status_code=404, detail="Contact not found")
        return {"op": "updated", "entity_type": "contact", "entity_id": cid, "before": _serialize_contact(row)}
    if kind == "update_deal":
        did = int(payload["deal_id"])
        row = await db.get(Deal, did)
        if not row:
            raise HTTPException(status_code=404, detail="Deal not found")
        return {"op": "updated", "entity_type": "deal", "entity_id": did, "before": _serialize_deal(row)}
    if kind == "update_event":
        eid = int(payload["event_id"])
        row = await db.get(Event, eid)
        if not row:
            raise HTTPException(status_code=404, detail="Event not found")
        return {"op": "updated", "entity_type": "event", "entity_id": eid, "before": _serialize_event(row)}
    if kind == "create_contact":
        return {"op": "created", "entity_type": "contact", "entity_id": None}
    if kind == "create_deal":
        return {"op": "created", "entity_type": "deal", "entity_id": None}
    if kind == "create_event":
        return {"op": "created", "entity_type": "event", "entity_id": None}
    raise HTTPException(status_code=400, detail=f"Unsupported auto-apply kind: {kind}")


async def _resolve_created_entity_id(db: AsyncSession, user: User, kind: str) -> int | None:
    """For creates, fetch the most-recently-created entity of the right type.

    Single-tenant (one artist per instance), so no per-user filter is needed.
    """
    from sqlalchemy import desc, select

    if kind == "create_contact":
        r = await db.execute(select(Contact).order_by(desc(Contact.id)).limit(1))
        c = r.scalar_one_or_none()
        return c.id if c else None
    if kind == "create_deal":
        r = await db.execute(select(Deal).order_by(desc(Deal.id)).limit(1))
        d = r.scalar_one_or_none()
        return d.id if d else None
    if kind == "create_event":
        r = await db.execute(select(Event).order_by(desc(Event.id)).limit(1))
        e = r.scalar_one_or_none()
        return e.id if e else None
    return None


async def auto_apply(
    db: AsyncSession,
    user: User,
    *,
    kind: str,
    payload: dict[str, Any],
    summary: str | None,
    run_id: int | None,
    thread_id: int | None,
    undo_window_seconds: int = UNDO_WINDOW_SECONDS,
) -> ExecutedAction:
    """Run an auto-apply action and persist the executed-action row.

    Raises HTTPException on validation/auth errors; the agent layer should catch and surface.
    """
    if not kind_is_auto_apply(kind):
        raise HTTPException(status_code=400, detail=f"kind {kind} is not auto-apply")

    pre = await _capture_pre_image(db, user, kind, payload)

    # Execute via the existing dispatcher (commit=False; we commit once at the agent layer).
    await PendingExecutionService.execute(db, user, kind, payload, commit=False)
    await db.flush()

    if pre.get("op") == "created" and pre.get("entity_id") is None:
        new_id = await _resolve_created_entity_id(db, user, kind)
        pre["entity_id"] = new_id

    action = ExecutedAction(
        user_id=user.id,
        run_id=run_id,
        thread_id=thread_id,
        kind=kind,
        summary=summary,
        status="executed",
        payload=payload,
        result={"entity_id": pre.get("entity_id")},
        reversal_payload=pre,
        reversible_until=datetime.now(UTC) + timedelta(seconds=undo_window_seconds),
    )
    db.add(action)
    await db.flush()
    return action


async def undo_action(db: AsyncSession, user: User, action_id: int) -> ExecutedAction:
    """Reverse a previously auto-applied action.

    Refuses if:
      - the action belongs to a different user (404),
      - the action was already reversed (400),
      - the reversibility window has passed (410).
    """
    row = await db.get(ExecutedAction, action_id)
    if not row or row.user_id != user.id:
        raise HTTPException(status_code=404, detail="Action not found")
    if row.reversed_at is not None:
        raise HTTPException(status_code=400, detail="Action already undone")
    now = datetime.now(UTC)
    if row.reversible_until and row.reversible_until < now:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Undo window expired")

    rev = dict(row.reversal_payload or {})
    op = rev.get("op")
    et = rev.get("entity_type")
    eid = rev.get("entity_id")
    if not op or not et:
        raise HTTPException(status_code=400, detail="Missing reversal payload")

    if op == "created":
        # Reverse a creation by deleting the entity.
        if eid is None:
            raise HTTPException(status_code=400, detail="Created entity id was not captured")
        if et == "contact":
            await ContactService.delete_contact(db, int(eid), user.id, commit=False)
        elif et == "deal":
            await DealService.delete_deal(db, int(eid), user.id, commit=False)
        elif et == "event":
            await EventService.delete_event(db, int(eid), user.id, commit=False)
        else:
            raise HTTPException(status_code=400, detail=f"Cannot undo create of {et}")
    elif op == "updated":
        before = dict(rev.get("before") or {})
        if et == "contact":
            patch = ContactUpdate(**before)
            await ContactService.update_contact(db, int(eid), patch, user.id, commit=False)
        elif et == "deal":
            data = dict(before)
            if data.get("amount") is not None:
                data["amount"] = Decimal(str(data["amount"]))
            patch = DealUpdate(**data)
            await DealService.update_deal(db, int(eid), patch, user.id, commit=False)
        elif et == "event":
            patch = EventUpdate(**before)
            await EventService.update_event(db, int(eid), patch, user.id, commit=False)
        else:
            raise HTTPException(status_code=400, detail=f"Cannot undo update of {et}")
    else:
        raise HTTPException(status_code=400, detail=f"Unknown reversal op: {op}")

    row.reversed_at = now
    await db.flush()
    return row
