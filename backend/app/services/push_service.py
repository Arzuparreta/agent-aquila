"""Web Push (VAPID) delivery + subscription helpers.

We use ``pywebpush`` lazily (only when actually sending) so the dependency stays
optional in dev. If VAPID keys are not configured, ``send_to_user`` becomes a no-op
and logs a one-line warning. The frontend can poll subscription status via
``GET /push/public-key`` to know whether push is enabled.
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.push_subscription import PushSubscription
from app.models.user import User

logger = logging.getLogger(__name__)


def push_enabled() -> bool:
    return bool((settings.vapid_public_key or "").strip() and (settings.vapid_private_key or "").strip())


async def upsert_subscription(
    db: AsyncSession,
    user: User,
    *,
    endpoint: str,
    p256dh: str,
    auth: str,
    user_agent: str | None,
) -> PushSubscription:
    r = await db.execute(
        select(PushSubscription).where(
            PushSubscription.user_id == user.id, PushSubscription.endpoint == endpoint
        )
    )
    row = r.scalar_one_or_none()
    if row:
        row.p256dh = p256dh
        row.auth = auth
        if user_agent:
            row.user_agent = user_agent[:255]
        row.last_seen_at = datetime.now(UTC)
        await db.flush()
        return row
    row = PushSubscription(
        user_id=user.id,
        endpoint=endpoint,
        p256dh=p256dh,
        auth=auth,
        user_agent=(user_agent or "")[:255] or None,
        last_seen_at=datetime.now(UTC),
    )
    db.add(row)
    await db.flush()
    return row


async def remove_subscription(db: AsyncSession, user: User, endpoint: str) -> int:
    r = await db.execute(
        select(PushSubscription).where(
            PushSubscription.user_id == user.id, PushSubscription.endpoint == endpoint
        )
    )
    rows = r.scalars().all()
    deleted = 0
    for row in rows:
        await db.delete(row)
        deleted += 1
    return deleted


async def list_subscriptions(db: AsyncSession, user: User) -> list[PushSubscription]:
    r = await db.execute(
        select(PushSubscription).where(PushSubscription.user_id == user.id)
    )
    return list(r.scalars().all())


async def send_to_user(
    db: AsyncSession,
    user: User,
    *,
    title: str,
    body: str,
    url: str | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Deliver a push notification to every active subscription belonging to ``user``.

    Returns a small summary dict (``{"sent": N, "failed": M}``); never raises.
    Stale subscriptions (HTTP 404 / 410 from the push service) are auto-cleaned.
    """
    if not push_enabled():
        logger.warning("push_enabled is False — skipping notification %r", title)
        return {"sent": 0, "failed": 0, "disabled": True}

    try:
        from pywebpush import WebPushException, webpush  # type: ignore[import-untyped]
    except Exception:  # noqa: BLE001
        logger.warning("pywebpush not installed — `pip install pywebpush` to enable Web Push")
        return {"sent": 0, "failed": 0, "missing_dep": True}

    subs = await list_subscriptions(db, user)
    payload = json.dumps(
        {"title": title, "body": body, "url": url, "data": data or {}}, ensure_ascii=False
    )
    sent = 0
    failed = 0
    stale: list[PushSubscription] = []
    for s in subs:
        try:
            webpush(
                subscription_info={
                    "endpoint": s.endpoint,
                    "keys": {"p256dh": s.p256dh, "auth": s.auth},
                },
                data=payload,
                vapid_private_key=settings.vapid_private_key,
                vapid_claims={"sub": settings.vapid_contact_email},
            )
            sent += 1
        except WebPushException as exc:
            code = getattr(exc.response, "status_code", None) if hasattr(exc, "response") else None
            if code in (404, 410):
                stale.append(s)
            else:
                logger.warning("web push failed for sub %s (status=%s): %s", s.id, code, exc)
            failed += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("web push unexpected error: %s", exc)
            failed += 1

    for s in stale:
        await db.delete(s)
    if stale:
        await db.flush()

    return {"sent": sent, "failed": failed}
