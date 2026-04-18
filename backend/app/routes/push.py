"""Web Push subscription management endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.push import PushPublicKeyResponse, PushSubscriptionCreate, PushSubscriptionRead
from app.services.push_service import push_enabled, remove_subscription, upsert_subscription

router = APIRouter(prefix="/push", tags=["push"])


@router.get("/public-key", response_model=PushPublicKeyResponse)
async def get_public_key() -> PushPublicKeyResponse:
    """Returns the VAPID public key the FE needs to subscribe (open endpoint).

    ``enabled=False`` means the operator hasn't configured VAPID keys yet, so the FE
    should hide the "Activar notificaciones" prompt.
    """
    return PushPublicKeyResponse(public_key=settings.vapid_public_key, enabled=push_enabled())


@router.post("/subscribe", response_model=PushSubscriptionRead, status_code=status.HTTP_201_CREATED)
async def subscribe(
    payload: PushSubscriptionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PushSubscriptionRead:
    row = await upsert_subscription(
        db,
        current_user,
        endpoint=payload.endpoint,
        p256dh=payload.keys.p256dh,
        auth=payload.keys.auth,
        user_agent=payload.user_agent,
    )
    await db.commit()
    await db.refresh(row)
    return PushSubscriptionRead(id=row.id, endpoint=row.endpoint)


@router.delete("/subscribe", status_code=status.HTTP_204_NO_CONTENT)
async def unsubscribe(
    endpoint: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    await remove_subscription(db, current_user, endpoint)
    await db.commit()
