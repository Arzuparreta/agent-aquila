from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.chat import StartChatResponse
from app.schemas.deal import DealCreate, DealRead, DealUpdate
from app.services.chat_service import start_entity_chat
from app.services.contact_service import ContactService
from app.services.deal_service import DealService

router = APIRouter(prefix="/deals", tags=["deals"], dependencies=[Depends(get_current_user)])


@router.get("", response_model=list[DealRead])
async def list_deals(active_only: bool = False, db: AsyncSession = Depends(get_db)) -> list[DealRead]:
    deals = await (DealService.list_active_deals(db) if active_only else DealService.list_deals(db))
    return [DealRead.model_validate(deal) for deal in deals]


@router.post("", response_model=DealRead, status_code=status.HTTP_201_CREATED)
async def create_deal(
    payload: DealCreate, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)
) -> DealRead:
    deal = await DealService.create_deal(db, payload, current_user.id)
    return DealRead.model_validate(deal)


@router.get("/{deal_id}", response_model=DealRead)
async def get_deal(deal_id: int, db: AsyncSession = Depends(get_db)) -> DealRead:
    deal = await DealService.get_deal(db, deal_id)
    return DealRead.model_validate(deal)


@router.patch("/{deal_id}", response_model=DealRead)
async def update_deal(
    deal_id: int, payload: DealUpdate, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)
) -> DealRead:
    deal = await DealService.update_deal(db, deal_id, payload, current_user.id)
    return DealRead.model_validate(deal)


@router.delete("/{deal_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_deal(
    deal_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)
) -> Response:
    await DealService.delete_deal(db, deal_id, current_user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{deal_id}/start-chat", response_model=StartChatResponse)
async def start_chat_from_deal(
    deal_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StartChatResponse:
    """Create (or reuse) an entity-bound chat thread for this deal and seed it with
    a single ``event`` announcement. Mirrors ``POST /emails/{id}/start-chat``.
    """
    deal = await DealService.get_deal(db, deal_id)

    contact_bit: str | None = None
    try:
        contact = await ContactService.get_contact(db, deal.contact_id)
        contact_bit = f"Contacto: {contact.name}"
    except Exception:  # noqa: BLE001 — contact fetch is best-effort for the announcement
        contact_bit = f"Contacto #{deal.contact_id}"

    amount_bit = None
    if deal.amount is not None:
        amount_bit = f"Monto: {deal.amount}{' ' + deal.currency if deal.currency else ''}"

    title = f"Trato · {deal.title}"[:255]
    detail_bits = [
        f"Estado: {deal.status}" if deal.status else None,
        amount_bit,
        contact_bit,
    ]
    details = " · ".join(b for b in detail_bits if b)
    announcement = (
        f"💼 Trato referenciado\n"
        f"Título: {deal.title}\n"
        f"{details}\n\n"
        f"{(deal.notes or '')[:600]}"
    )
    thread = await start_entity_chat(
        db,
        current_user,
        entity_type="deal",
        entity_id=deal.id,
        title=title,
        announcement=announcement,
        event_attachments=[{"event_kind": "deal_referenced", "deal_id": deal.id}],
    )
    await db.commit()
    return StartChatResponse(thread_id=thread.id)
