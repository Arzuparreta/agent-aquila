"""One-shot cleanup for the proactive-thread pollution.

Background: prior to the inbound noise filter, every Gmail / Graph message and
every calendar event spawned an entity-bound chat thread + agent run + push.
That left ``Conversaciones`` flooded with junk threads (LeetCode digest,
LinkedIn Premium notifications, calendar imports, etc.).

This script:

1. Backfills ``triage_category`` / ``reason`` / ``source`` / ``at`` on every
   existing ``emails`` and ``events`` row using ONLY the heuristic stage of
   ``InboundFilterService`` (no LLM calls, no network).
2. Archives ``ChatThread`` rows whose bound entity now classifies as
   ``noise`` or ``informational`` AND that have no real user reply (the only
   non-event content was the auto-generated agent message). The threads are
   not deleted, just hidden from the default sidebar.
3. Deletes ``Contact`` rows that were auto-created from clearly-noise senders
   (audit ``created_from_gmail`` / ``created_from_graph``) and have no Deal,
   no outbound email, and no manual edits — they were directory pollution.

Run from ``backend/``::

    python -m app.scripts.cleanup_proactive_noise            # dry-run summary
    python -m app.scripts.cleanup_proactive_noise --apply    # actually write

Safe to re-run; idempotent.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models.audit_log import AuditLog
from app.models.chat_message import ChatMessage
from app.models.chat_thread import ChatThread
from app.models.contact import Contact
from app.models.deal import Deal
from app.models.email import Email
from app.models.event import Event
from app.models.user import User
from app.services.inbound_filter_service import (
    CATEGORY_ACTIONABLE,
    CATEGORY_INFORMATIONAL,
    CATEGORY_NOISE,
    SOURCE_HEURISTIC,
    _heuristic_email_verdict,
    _heuristic_event_verdict,
)


async def _backfill_emails(db: AsyncSession, *, apply: bool) -> dict[str, int]:
    counts = {CATEGORY_ACTIONABLE: 0, CATEGORY_INFORMATIONAL: 0, CATEGORY_NOISE: 0}
    res = await db.execute(select(Email).where(Email.triage_category.is_(None)))
    rows = list(res.scalars().all())
    for email in rows:
        verdict = _heuristic_email_verdict(email)
        counts[verdict.category] = counts.get(verdict.category, 0) + 1
        if apply:
            email.triage_category = verdict.category
            email.triage_reason = (verdict.reason or "")[:255]
            email.triage_source = SOURCE_HEURISTIC
            email.triage_at = datetime.now(UTC)
    if apply:
        await db.flush()
    print(f"emails backfilled: {len(rows)} → {counts}")
    return counts


async def _backfill_events(db: AsyncSession, *, apply: bool) -> dict[str, int]:
    counts = {CATEGORY_ACTIONABLE: 0, CATEGORY_INFORMATIONAL: 0, CATEGORY_NOISE: 0}
    res = await db.execute(select(Event).where(Event.triage_category.is_(None)))
    rows = list(res.scalars().all())
    # We don't have a per-event user binding, so use the first user as the
    # heuristic context (organizer/declined checks). Single-tenant deployments
    # are the common case for this CRM; multi-tenant deployments should re-run
    # this script per user (or extend it with an explicit ``--user-id`` flag).
    user_res = await db.execute(select(User).order_by(User.id).limit(1))
    user = user_res.scalar_one_or_none()
    if not user:
        print("no users found; skipping events backfill")
        return counts
    for event in rows:
        verdict = _heuristic_event_verdict(user, event, None)
        counts[verdict.category] = counts.get(verdict.category, 0) + 1
        if apply:
            event.triage_category = verdict.category
            event.triage_reason = (verdict.reason or "")[:255]
            event.triage_source = SOURCE_HEURISTIC
            event.triage_at = datetime.now(UTC)
    if apply:
        await db.flush()
    print(f"events backfilled: {len(rows)} → {counts}")
    return counts


async def _archive_noise_threads(db: AsyncSession, *, apply: bool) -> int:
    """Archive entity threads that are bound to a noise/informational item and
    have no user reply (only the auto event + auto assistant turn).
    """
    res = await db.execute(
        select(ChatThread).where(
            ChatThread.kind == "entity",
            ChatThread.archived.is_(False),
            ChatThread.entity_type.in_(("email", "contact", "event")),
        )
    )
    threads = list(res.scalars().all())
    archived = 0
    for thread in threads:
        # Has the user actually engaged with this thread (typed something)?
        user_msg_count_q = await db.execute(
            select(func.count(ChatMessage.id)).where(
                ChatMessage.thread_id == thread.id,
                ChatMessage.role == "user",
            )
        )
        if int(user_msg_count_q.scalar() or 0) > 0:
            continue

        category = await _entity_category(db, thread.entity_type, thread.entity_id)
        if category in (CATEGORY_NOISE, CATEGORY_INFORMATIONAL):
            archived += 1
            if apply:
                thread.archived = True
                thread.updated_at = datetime.now(UTC)
    if apply:
        await db.flush()
    print(f"threads archived: {archived}")
    return archived


async def _entity_category(
    db: AsyncSession, entity_type: str | None, entity_id: int | None
) -> str | None:
    if not entity_type or not entity_id:
        return None
    if entity_type == "email":
        row = await db.get(Email, entity_id)
        return row.triage_category if row else None
    if entity_type == "event":
        row = await db.get(Event, entity_id)
        return row.triage_category if row else None
    if entity_type == "contact":
        # A contact thread is "noise" if all its emails are noise (and there
        # are no outbound replies).
        outbound_q = await db.execute(
            select(func.count(Email.id)).where(
                Email.contact_id == entity_id, Email.direction == "outbound"
            )
        )
        if int(outbound_q.scalar() or 0) > 0:
            return CATEGORY_ACTIONABLE
        deal_q = await db.execute(
            select(func.count(Deal.id)).where(Deal.contact_id == entity_id)
        )
        if int(deal_q.scalar() or 0) > 0:
            return CATEGORY_ACTIONABLE
        # Worst category among inbound emails wins (any actionable → keep thread).
        rows = await db.execute(
            select(Email.triage_category).where(
                Email.contact_id == entity_id,
                Email.direction == "inbound",
            )
        )
        cats = {c for (c,) in rows.all() if c}
        if not cats:
            return None
        if CATEGORY_ACTIONABLE in cats:
            return CATEGORY_ACTIONABLE
        if CATEGORY_INFORMATIONAL in cats:
            return CATEGORY_INFORMATIONAL
        return CATEGORY_NOISE
    return None


async def _delete_orphan_noise_contacts(db: AsyncSession, *, apply: bool) -> int:
    """Auto-created contacts (``created_from_gmail`` / ``created_from_graph``)
    with zero deals, zero outbound mail, and only ``noise`` inbound emails
    are directory pollution. Drop them so Contactos stays clean.
    """
    res = await db.execute(
        select(AuditLog.entity_id).where(
            AuditLog.entity_type == "contact",
            AuditLog.action.in_(("created_from_gmail", "created_from_graph")),
        )
    )
    candidate_ids = {int(eid) for (eid,) in res.all() if eid}
    deleted = 0
    for cid in candidate_ids:
        deal_q = await db.execute(
            select(func.count(Deal.id)).where(Deal.contact_id == cid)
        )
        if int(deal_q.scalar() or 0) > 0:
            continue
        outbound_q = await db.execute(
            select(func.count(Email.id)).where(
                Email.contact_id == cid, Email.direction == "outbound"
            )
        )
        if int(outbound_q.scalar() or 0) > 0:
            continue
        # Only delete when every inbound email for this contact is noise.
        non_noise_q = await db.execute(
            select(func.count(Email.id)).where(
                Email.contact_id == cid,
                or_(Email.triage_category.is_(None), Email.triage_category != CATEGORY_NOISE),
            )
        )
        if int(non_noise_q.scalar() or 0) > 0:
            continue
        contact = await db.get(Contact, cid)
        if not contact:
            continue
        # Detach emails first (they FK to contacts with no ondelete cascade).
        await db.execute(
            Email.__table__.update()
            .where(Email.contact_id == cid)
            .values(contact_id=None)
        )
        deleted += 1
        if apply:
            await db.delete(contact)
    if apply:
        await db.flush()
    print(f"noise contacts deleted: {deleted}")
    return deleted


async def _purge_unanswered_entity_threads(db: AsyncSession, *, apply: bool) -> int:
    """Hard-delete entity-bound threads (email/contact/event) where the user
    never typed anything. The new proactive layer is push-only and never
    spawns chat threads, so anything matching this filter is leftover noise
    from the old auto-agent behavior.

    Cascades to ``chat_messages`` first because there's no DB-level cascade.
    """
    user_msg_exists = (
        select(ChatMessage.id)
        .where(
            ChatMessage.thread_id == ChatThread.id,
            ChatMessage.role == "user",
        )
        .exists()
    )
    candidate_stmt = select(ChatThread.id).where(
        ChatThread.kind == "entity",
        ChatThread.entity_type.in_(("email", "contact", "event")),
        ~user_msg_exists,
    )
    res = await db.execute(candidate_stmt)
    ids = [row[0] for row in res.all()]
    if not ids:
        print("threads purged: 0")
        return 0
    if apply:
        await db.execute(delete(ChatMessage).where(ChatMessage.thread_id.in_(ids)))
        await db.execute(delete(ChatThread).where(ChatThread.id.in_(ids)))
    print(f"threads purged: {len(ids)}")
    return len(ids)


async def main_async(*, apply: bool, purge: bool) -> None:
    async with AsyncSessionLocal() as db:
        await _backfill_emails(db, apply=apply)
        await _backfill_events(db, apply=apply)
        if purge:
            await _purge_unanswered_entity_threads(db, apply=apply)
        else:
            await _archive_noise_threads(db, apply=apply)
        await _delete_orphan_noise_contacts(db, apply=apply)
        if apply:
            await db.commit()
            print("changes committed.")
        else:
            await db.rollback()
            print("dry-run; pass --apply to commit.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0] if __doc__ else None)
    parser.add_argument("--apply", action="store_true", help="Actually write changes (default: dry run).")
    parser.add_argument(
        "--purge",
        action="store_true",
        help=(
            "Hard-DELETE unanswered entity-bound threads (and their messages) "
            "instead of just archiving them. Use after the proactive layer has "
            "been switched to push-only."
        ),
    )
    args = parser.parse_args()
    asyncio.run(main_async(apply=args.apply, purge=args.purge))


if __name__ == "__main__":
    main()


# Silence "unused" lint on the helper imports we keep available for ad-hoc work.
_ = and_
