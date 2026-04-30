"""OAuth 2.0 routes. Start a consent flow, receive the provider callback, persist per-product
`ConnectorConnection` rows that share the same refresh token across Gmail/Calendar/Drive.
"""
from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.connector_connection import ConnectorConnection
from app.models.user import User
from app.schemas.oauth import (
    GoogleOAuthAppCredentialsResponse,
    GoogleOAuthAppCredentialsUpdate,
    MicrosoftOAuthAppCredentialsResponse,
    MicrosoftOAuthAppCredentialsUpdate,
    OAuthStartRequest,
    OAuthStartResponse,
    OAuthStatusResponse,
)
from app.services.connector_service import ConnectorService
from app.services.instance_oauth_service import (
    get_google_app_credentials_form,
    get_google_runtime_config,
    get_microsoft_app_credentials_form,
    get_microsoft_runtime_config,
    get_redirect_base as get_instance_redirect_base,
    resolve_oauth_redirect_base_for_request,
    save_google_app_credentials,
    save_microsoft_app_credentials,
)
from app.services.oauth import google_oauth, microsoft_oauth, state_store
from app.services.oauth.errors import OAuthError

router = APIRouter(prefix="/oauth", tags=["oauth"])


@router.get("/google/status", response_model=OAuthStatusResponse)
async def google_status(db: AsyncSession = Depends(get_db)) -> OAuthStatusResponse:
    cfg = await get_google_runtime_config(db)
    return OAuthStatusResponse(
        configured=google_oauth.is_runtime_ready(cfg),
        redirect_uri=google_oauth.redirect_uri_for(cfg),
        providers=[
            "google_gmail",
            "google_calendar",
            "google_drive",
            "google_youtube",
            "google_tasks",
            "google_people",
            "google_sheets",
            "google_docs",
        ],
    )


@router.get("/google/app-credentials", response_model=GoogleOAuthAppCredentialsResponse)
async def get_google_app_credentials(
    db: AsyncSession = Depends(get_db), _user: User = Depends(get_current_user)
) -> GoogleOAuthAppCredentialsResponse:
    data = await get_google_app_credentials_form(db)
    return GoogleOAuthAppCredentialsResponse(**data)


@router.put("/google/app-credentials", response_model=GoogleOAuthAppCredentialsResponse)
async def put_google_app_credentials(
    payload: GoogleOAuthAppCredentialsUpdate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> GoogleOAuthAppCredentialsResponse:
    try:
        await save_google_app_credentials(
            db,
            client_id=payload.client_id,
            client_secret=payload.client_secret,
            redirect_base=payload.redirect_base,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    data = await get_google_app_credentials_form(db)
    return GoogleOAuthAppCredentialsResponse(**data)


@router.post(
    "/google/start",
    response_model=OAuthStartResponse,
    dependencies=[Depends(get_current_user)],
)
async def google_start(
    payload: OAuthStartRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OAuthStartResponse:
    cfg = await get_google_runtime_config(db)
    if not google_oauth.is_runtime_ready(cfg):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google sign-in for this app is not set up yet. Open Settings and save your Google Client ID and secret (one-time), then try again.",
        )
    scopes = google_oauth.scopes_for_intent(payload.intent)
    request_origin = str(request.base_url).rstrip("/")
    redirect_base = await resolve_oauth_redirect_base_for_request(db, request_origin)
    state = await state_store.create_state(
        state_store.StatePayload(
            user_id=current_user.id,
            provider="google",
            intent=payload.intent or "all",
            scopes=scopes,
            redirect_after=payload.redirect_after,
            redirect_base=redirect_base,
        )
    )
    try:
        url = google_oauth.build_authorize_url(state, scopes, cfg, redirect_base=redirect_base)
    except OAuthError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return OAuthStartResponse(authorize_url=url, state=state, scopes=scopes, configured=True)


def _frontend_redirect(target: str | None, params: dict[str, str]) -> str:
    base = (target or settings.oauth_post_auth_redirect).rstrip("?&")
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}{urlencode(params)}"


async def _upsert_google_connection(
    db: AsyncSession,
    user: User,
    provider: str,
    refresh_token: str,
    access_token: str,
    token_expires_at,
    scopes: list[str],
    userinfo: dict,
) -> ConnectorConnection:
    """Create or update a per-product Google connection for the user. If one already exists
    for this provider + google account, rotate its credentials instead of creating a duplicate.
    """
    google_sub = str(userinfo.get("sub") or "")
    email_addr = str(userinfo.get("email") or "")

    existing_row: ConnectorConnection | None = None
    result = await db.execute(
        select(ConnectorConnection).where(
            ConnectorConnection.user_id == user.id,
            ConnectorConnection.provider == provider,
        )
    )
    for row in result.scalars().all():
        meta = row.meta or {}
        if google_sub and meta.get("google_sub") == google_sub:
            existing_row = row
            break
        if not google_sub and email_addr and meta.get("google_email") == email_addr:
            existing_row = row
            break
    if existing_row is None and result is not None:
        # If there was exactly one existing row for this provider and we couldn't match by
        # sub/email (older row), reuse it rather than stacking duplicates.
        r2 = await db.execute(
            select(ConnectorConnection).where(
                ConnectorConnection.user_id == user.id, ConnectorConnection.provider == provider
            )
        )
        rows = list(r2.scalars().all())
        if len(rows) == 1:
            existing_row = rows[0]

    creds = {"access_token": access_token, "refresh_token": refresh_token}
    meta = {
        "status": "active",
        "google_sub": google_sub or None,
        "google_email": email_addr or None,
        "source": "oauth",
    }
    if existing_row:
        decrypted = ConnectorService.decrypt_credentials(existing_row)
        decrypted.update(creds)
        existing_row.credentials_encrypted = ConnectorService.encrypt_credentials(decrypted)
        existing_row.token_expires_at = token_expires_at
        existing_row.oauth_scopes = scopes
        existing_row.meta = {**(existing_row.meta or {}), **meta}
        if email_addr and (not existing_row.label or existing_row.label.startswith("google_")):
            existing_row.label = f"{provider} · {email_addr}"
        return existing_row

    label = f"{provider} · {email_addr}" if email_addr else provider
    row = ConnectorConnection(
        user_id=user.id,
        provider=provider,
        label=label,
        credentials_encrypted=ConnectorService.encrypt_credentials(creds),
        meta=meta,
        token_expires_at=token_expires_at,
        oauth_scopes=list(scopes),
    )
    db.add(row)
    return row


@router.get("/google/callback")
async def google_callback(
    request: Request,
    db: AsyncSession = Depends(get_db),
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    error_description: str | None = Query(default=None),
) -> RedirectResponse:
    state_payload = await state_store.consume_state(state or "")
    if not state_payload or state_payload.provider != "google":
        return RedirectResponse(
            _frontend_redirect(None, {"oauth": "error", "error": "invalid_state"}),
            status_code=status.HTTP_302_FOUND,
        )
    if error:
        return RedirectResponse(
            _frontend_redirect(
                state_payload.redirect_after,
                {"oauth": "error", "provider": "google", "error": error, "detail": (error_description or "")[:300]},
            ),
            status_code=status.HTTP_302_FOUND,
        )
    if not code:
        return RedirectResponse(
            _frontend_redirect(
                state_payload.redirect_after, {"oauth": "error", "provider": "google", "error": "missing_code"}
            ),
            status_code=status.HTTP_302_FOUND,
        )

    user = await db.get(User, state_payload.user_id)
    if not user:
        return RedirectResponse(
            _frontend_redirect(state_payload.redirect_after, {"oauth": "error", "error": "unknown_user"}),
            status_code=status.HTTP_302_FOUND,
        )

    cfg = await get_google_runtime_config(db)
    try:
        token_payload = await google_oauth.exchange_code(
            code, cfg, redirect_base=state_payload.redirect_base
        )
    except OAuthError as exc:
        return RedirectResponse(
            _frontend_redirect(
                state_payload.redirect_after,
                {"oauth": "error", "provider": "google", "error": "exchange_failed", "detail": str(exc)[:300]},
            ),
            status_code=status.HTTP_302_FOUND,
        )

    access_token = str(token_payload["access_token"])
    refresh_token = str(token_payload.get("refresh_token") or "")
    granted_scope = str(token_payload.get("scope") or "")
    scopes = granted_scope.split() if granted_scope else state_payload.scopes
    token_expires_at = google_oauth.compute_expires_at(token_payload)

    if not refresh_token:
        return RedirectResponse(
            _frontend_redirect(
                state_payload.redirect_after,
                {
                    "oauth": "error",
                    "provider": "google",
                    "error": "no_refresh_token",
                    "detail": "Google did not return a refresh_token. Revoke access at https://myaccount.google.com/permissions and try again.",
                },
            ),
            status_code=status.HTTP_302_FOUND,
        )

    userinfo = await google_oauth.fetch_userinfo(access_token)

    provider_ids = google_oauth.provider_ids_for_scopes(scopes)
    if not provider_ids:
        return RedirectResponse(
            _frontend_redirect(
                state_payload.redirect_after,
                {"oauth": "error", "provider": "google", "error": "no_scopes_granted"},
            ),
            status_code=status.HTTP_302_FOUND,
        )

    created_ids: list[int] = []
    for provider in provider_ids:
        row = await _upsert_google_connection(
            db,
            user,
            provider,
            refresh_token,
            access_token,
            token_expires_at,
            scopes,
            userinfo,
        )
        await db.flush()
        created_ids.append(row.id)
    await db.commit()
    # No background sync to kick off — every read happens live via the
    # provider proxy routes after the OpenClaw refactor.

    return RedirectResponse(
        _frontend_redirect(
            state_payload.redirect_after,
            {
                "oauth": "success",
                "provider": "google",
                "account": str(userinfo.get("email") or ""),
                "connection_ids": ",".join(str(i) for i in created_ids),
                "scopes": ",".join(scopes),
            },
        ),
        status_code=status.HTTP_302_FOUND,
    )


# ---------------------------------------------------------------------------
# Microsoft Graph OAuth
# ---------------------------------------------------------------------------


async def _upsert_microsoft_connection(
    db: AsyncSession,
    user: User,
    provider: str,
    refresh_token: str,
    access_token: str,
    token_expires_at,
    scopes: list[str],
    userinfo: dict,
) -> ConnectorConnection:
    account_id = str(userinfo.get("id") or "")
    email_addr = str(userinfo.get("mail") or userinfo.get("userPrincipalName") or "")

    existing_row: ConnectorConnection | None = None
    result = await db.execute(
        select(ConnectorConnection).where(
            ConnectorConnection.user_id == user.id,
            ConnectorConnection.provider == provider,
        )
    )
    for row in result.scalars().all():
        meta = row.meta or {}
        if account_id and meta.get("ms_account_id") == account_id:
            existing_row = row
            break
        if not account_id and email_addr and meta.get("ms_email") == email_addr:
            existing_row = row
            break
    if existing_row is None:
        r2 = await db.execute(
            select(ConnectorConnection).where(
                ConnectorConnection.user_id == user.id, ConnectorConnection.provider == provider
            )
        )
        rows = list(r2.scalars().all())
        if len(rows) == 1:
            existing_row = rows[0]

    creds = {"access_token": access_token, "refresh_token": refresh_token}
    meta = {
        "status": "active",
        "ms_account_id": account_id or None,
        "ms_email": email_addr or None,
        "source": "oauth",
    }
    if existing_row:
        decrypted = ConnectorService.decrypt_credentials(existing_row)
        decrypted.update(creds)
        existing_row.credentials_encrypted = ConnectorService.encrypt_credentials(decrypted)
        existing_row.token_expires_at = token_expires_at
        existing_row.oauth_scopes = scopes
        existing_row.meta = {**(existing_row.meta or {}), **meta}
        if email_addr and (not existing_row.label or existing_row.label.startswith("graph_")):
            existing_row.label = f"{provider} · {email_addr}"
        return existing_row

    label = f"{provider} · {email_addr}" if email_addr else provider
    row = ConnectorConnection(
        user_id=user.id,
        provider=provider,
        label=label,
        credentials_encrypted=ConnectorService.encrypt_credentials(creds),
        meta=meta,
        token_expires_at=token_expires_at,
        oauth_scopes=list(scopes),
    )
    db.add(row)
    return row


@router.get("/microsoft/status", response_model=OAuthStatusResponse)
async def microsoft_status(db: AsyncSession = Depends(get_db)) -> OAuthStatusResponse:
    base = await get_instance_redirect_base(db)
    ms_cfg = await get_microsoft_runtime_config(db)
    return OAuthStatusResponse(
        configured=microsoft_oauth.is_runtime_ready(ms_cfg),
        redirect_uri=microsoft_oauth.redirect_uri_for_base(base),
        providers=["graph_mail", "graph_calendar", "graph_onedrive"],
    )


@router.get("/microsoft/app-credentials", response_model=MicrosoftOAuthAppCredentialsResponse)
async def get_microsoft_app_credentials(
    db: AsyncSession = Depends(get_db), _user: User = Depends(get_current_user)
) -> MicrosoftOAuthAppCredentialsResponse:
    data = await get_microsoft_app_credentials_form(db)
    return MicrosoftOAuthAppCredentialsResponse(**data)


@router.put("/microsoft/app-credentials", response_model=MicrosoftOAuthAppCredentialsResponse)
async def put_microsoft_app_credentials(
    payload: MicrosoftOAuthAppCredentialsUpdate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> MicrosoftOAuthAppCredentialsResponse:
    try:
        await save_microsoft_app_credentials(
            db,
            client_id=payload.client_id,
            client_secret=payload.client_secret,
            tenant=payload.tenant,
            redirect_base=payload.redirect_base,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    data = await get_microsoft_app_credentials_form(db)
    return MicrosoftOAuthAppCredentialsResponse(**data)


@router.post(
    "/microsoft/start",
    response_model=OAuthStartResponse,
    dependencies=[Depends(get_current_user)],
)
async def microsoft_start(
    payload: OAuthStartRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OAuthStartResponse:
    ms_cfg = await get_microsoft_runtime_config(db)
    if not microsoft_oauth.is_runtime_ready(ms_cfg):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Microsoft sign-in for this app is not set up yet. Open Settings and save your Azure "
            "Application (client) ID and secret (one-time), then try again.",
        )
    scopes = microsoft_oauth.scopes_for_intent(payload.intent)
    request_origin = str(request.base_url).rstrip("/")
    redirect_base = await resolve_oauth_redirect_base_for_request(db, request_origin)
    state = await state_store.create_state(
        state_store.StatePayload(
            user_id=current_user.id,
            provider="microsoft",
            intent=payload.intent or "all",
            scopes=scopes,
            redirect_after=payload.redirect_after,
            redirect_base=redirect_base,
        )
    )
    try:
        ms_redir = microsoft_oauth.redirect_uri_for_base(redirect_base)
        url = microsoft_oauth.build_authorize_url(
            state, scopes, ms_cfg, redirect_uri_override=ms_redir
        )
    except OAuthError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return OAuthStartResponse(authorize_url=url, state=state, scopes=scopes, configured=True)


@router.get("/microsoft/callback")
async def microsoft_callback(
    request: Request,
    db: AsyncSession = Depends(get_db),
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    error_description: str | None = Query(default=None),
) -> RedirectResponse:
    state_payload = await state_store.consume_state(state or "")
    if not state_payload or state_payload.provider != "microsoft":
        return RedirectResponse(
            _frontend_redirect(None, {"oauth": "error", "error": "invalid_state"}),
            status_code=status.HTTP_302_FOUND,
        )
    if error:
        return RedirectResponse(
            _frontend_redirect(
                state_payload.redirect_after,
                {"oauth": "error", "provider": "microsoft", "error": error, "detail": (error_description or "")[:300]},
            ),
            status_code=status.HTTP_302_FOUND,
        )
    if not code:
        return RedirectResponse(
            _frontend_redirect(
                state_payload.redirect_after, {"oauth": "error", "provider": "microsoft", "error": "missing_code"}
            ),
            status_code=status.HTTP_302_FOUND,
        )

    user = await db.get(User, state_payload.user_id)
    if not user:
        return RedirectResponse(
            _frontend_redirect(state_payload.redirect_after, {"oauth": "error", "error": "unknown_user"}),
            status_code=status.HTTP_302_FOUND,
        )

    ms_cfg = await get_microsoft_runtime_config(db)
    ms_redir = microsoft_oauth.redirect_uri_for_base(
        state_payload.redirect_base or await get_instance_redirect_base(db)
    )
    try:
        token_payload = await microsoft_oauth.exchange_code(
            code, ms_cfg, redirect_uri_override=ms_redir
        )
    except OAuthError as exc:
        return RedirectResponse(
            _frontend_redirect(
                state_payload.redirect_after,
                {"oauth": "error", "provider": "microsoft", "error": "exchange_failed", "detail": str(exc)[:300]},
            ),
            status_code=status.HTTP_302_FOUND,
        )

    access_token = str(token_payload["access_token"])
    refresh_token = str(token_payload.get("refresh_token") or "")
    granted_scope = str(token_payload.get("scope") or "")
    scopes = granted_scope.split() if granted_scope else state_payload.scopes
    token_expires_at = microsoft_oauth.compute_expires_at(token_payload)

    if not refresh_token:
        return RedirectResponse(
            _frontend_redirect(
                state_payload.redirect_after,
                {
                    "oauth": "error",
                    "provider": "microsoft",
                    "error": "no_refresh_token",
                    "detail": "Azure AD did not return a refresh_token. Ensure the 'offline_access' scope is granted.",
                },
            ),
            status_code=status.HTTP_302_FOUND,
        )

    userinfo = await microsoft_oauth.fetch_userinfo(access_token)
    provider_ids = microsoft_oauth.provider_ids_for_scopes(scopes)
    if not provider_ids:
        return RedirectResponse(
            _frontend_redirect(
                state_payload.redirect_after,
                {"oauth": "error", "provider": "microsoft", "error": "no_scopes_granted"},
            ),
            status_code=status.HTTP_302_FOUND,
        )

    created_ids: list[int] = []
    for provider in provider_ids:
        row = await _upsert_microsoft_connection(
            db,
            user,
            provider,
            refresh_token,
            access_token,
            token_expires_at,
            scopes,
            userinfo,
        )
        await db.flush()
        created_ids.append(row.id)
    await db.commit()
    # No background sync to kick off — every read happens live via the
    # provider proxy routes after the OpenClaw refactor.

    return RedirectResponse(
        _frontend_redirect(
            state_payload.redirect_after,
            {
                "oauth": "success",
                "provider": "microsoft",
                "account": str(userinfo.get("mail") or userinfo.get("userPrincipalName") or ""),
                "connection_ids": ",".join(str(i) for i in created_ids),
                "scopes": ",".join(scopes),
            },
        ),
        status_code=status.HTTP_302_FOUND,
    )
