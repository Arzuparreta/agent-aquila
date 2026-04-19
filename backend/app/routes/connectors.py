from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.connector import (
    ConnectorConnectionCreate,
    ConnectorConnectionPatch,
    ConnectorConnectionRead,
    ConnectorDryRunResponse,
    ConnectorHealthResponse,
    ConnectorPreviewRequest,
    ConnectorPreviewResponse,
)
from app.services.capability_policy import risk_tier_for_kind
from app.services.connector_dry_run_service import ACTION_TO_KIND as _ACTION_TO_KIND
from app.services.connector_dry_run_service import ConnectorDryRunService
from app.services.connector_service import ConnectorService
from app.services.oauth import google_oauth, microsoft_oauth, TokenManager
from app.services.oauth.errors import ConnectorNeedsReauth, OAuthError
from app.services.pending_execution_service import preview_for_proposal_kind

router = APIRouter(
    prefix="/connectors", tags=["connectors"], dependencies=[Depends(get_current_user)]
)


@router.get("", response_model=list[ConnectorConnectionRead])
async def list_connections(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ConnectorConnectionRead]:
    rows = await ConnectorService.list_connections(db, current_user)
    return [ConnectorService.to_read(r) for r in rows]


@router.get("/{connection_id}", response_model=ConnectorConnectionRead)
async def get_connection(
    connection_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ConnectorConnectionRead:
    row = await ConnectorService.get_connection(db, current_user, connection_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found")
    return ConnectorService.to_read(row)


@router.patch("/{connection_id}", response_model=ConnectorConnectionRead)
async def patch_connection(
    connection_id: int,
    payload: ConnectorConnectionPatch,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ConnectorConnectionRead:
    row = await ConnectorService.patch_connection(db, current_user, connection_id, payload)
    return ConnectorService.to_read(row)


@router.post("", response_model=ConnectorConnectionRead, status_code=status.HTTP_201_CREATED)
async def create_connection(
    payload: ConnectorConnectionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ConnectorConnectionRead:
    row = await ConnectorService.create_connection(db, current_user, payload)
    return ConnectorService.to_read(row)


@router.delete("/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connection(
    connection_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    await ConnectorService.delete_connection(db, current_user, connection_id)


@router.post("/preview", response_model=ConnectorPreviewResponse)
async def preview_connector_action(
    payload: ConnectorPreviewRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ConnectorPreviewResponse:
    kind = _ACTION_TO_KIND.get(payload.action)
    if not kind:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown action. Use one of: {', '.join(sorted(_ACTION_TO_KIND))}",
        )
    row = await ConnectorService.require_connection(db, current_user, payload.connection_id)
    merged = {**payload.payload, "connection_id": payload.connection_id}
    preview = preview_for_proposal_kind(kind, merged)
    return ConnectorPreviewResponse(
        provider=row.provider,
        action=payload.action,
        risk_tier=risk_tier_for_kind(kind),
        preview=preview,
    )


@router.post("/dry-run", response_model=ConnectorDryRunResponse)
async def dry_run_connector_action(
    payload: ConnectorPreviewRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ConnectorDryRunResponse:
    kind = _ACTION_TO_KIND.get(payload.action)
    if not kind:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown action. Use one of: {', '.join(sorted(_ACTION_TO_KIND))}",
        )
    row = await ConnectorService.require_connection(db, current_user, payload.connection_id)
    _, creds, provider = await TokenManager.get_valid_creds(db, row)
    merged = {**payload.payload, "connection_id": payload.connection_id}
    result = await ConnectorDryRunService.run(provider, creds, payload.action, merged)
    ok = bool(result.get("ok"))
    return ConnectorDryRunResponse(
        ok=ok,
        provider=provider,
        action=payload.action,
        risk_tier=risk_tier_for_kind(kind),
        result=result,
    )


@router.get("/{connection_id}/health", response_model=ConnectorHealthResponse)
async def connector_health(
    connection_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ConnectorHealthResponse:
    """Refresh token if needed, then verify access with the provider (userinfo / profile)."""
    row = await ConnectorService.get_connection(db, current_user, connection_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found")
    try:
        access_token, _creds, _provider = await TokenManager.get_valid_creds(db, row)
    except ConnectorNeedsReauth as exc:
        return ConnectorHealthResponse(ok=False, provider=row.provider, error=str(exc))
    except OAuthError as exc:
        return ConnectorHealthResponse(ok=False, provider=row.provider, error=str(exc))

    if TokenManager.is_google(row.provider):
        info = await google_oauth.fetch_userinfo(access_token)
        if not info:
            return ConnectorHealthResponse(
                ok=False,
                provider=row.provider,
                error="Could not reach Google userinfo with this token.",
            )
        account = str(info.get("email") or "")
        return ConnectorHealthResponse(ok=True, provider=row.provider, account=account or None)

    if TokenManager.is_microsoft(row.provider):
        info = await microsoft_oauth.fetch_userinfo(access_token)
        if not info:
            return ConnectorHealthResponse(
                ok=False,
                provider=row.provider,
                error="Could not reach Microsoft profile with this token.",
            )
        account = str(info.get("mail") or info.get("userPrincipalName") or "")
        return ConnectorHealthResponse(ok=True, provider=row.provider, account=account or None)

    if not (access_token or "").strip():
        return ConnectorHealthResponse(
            ok=False,
            provider=row.provider,
            error="No access token stored for this connection.",
        )
    return ConnectorHealthResponse(ok=True, provider=row.provider, account=None)
