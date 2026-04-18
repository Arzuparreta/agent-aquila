"""Load and update instance-level OAuth application settings (Google client ID/secret in DB)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.crypto import decrypt_secret, encrypt_secret
from app.models.instance_oauth_settings import InstanceOAuthSettings
from app.services.oauth.google_oauth import GoogleOAuthRuntimeConfig, is_runtime_ready

_SINGLETON_ID = 1


async def _get_or_create_row(db: AsyncSession) -> InstanceOAuthSettings:
    result = await db.execute(select(InstanceOAuthSettings).where(InstanceOAuthSettings.id == _SINGLETON_ID))
    row = result.scalar_one_or_none()
    if row is None:
        row = InstanceOAuthSettings(id=_SINGLETON_ID)
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return row


async def get_redirect_base(db: AsyncSession) -> str:
    """Public API origin for OAuth callbacks (Google + Microsoft share this base path prefix)."""
    row = await _get_or_create_row(db)
    from_ui = (row.google_oauth_redirect_base or "").strip()
    return from_ui or settings.google_oauth_redirect_base


async def get_google_runtime_config(db: AsyncSession) -> GoogleOAuthRuntimeConfig:
    row = await _get_or_create_row(db)
    cid = (row.google_oauth_client_id or "").strip() or settings.google_oauth_client_id
    if row.google_oauth_client_secret_encrypted:
        secret = decrypt_secret(row.google_oauth_client_secret_encrypted) or ""
    else:
        secret = settings.google_oauth_client_secret
    base = (row.google_oauth_redirect_base or "").strip() or settings.google_oauth_redirect_base
    return GoogleOAuthRuntimeConfig(client_id=cid, client_secret=secret, redirect_base=base)


async def get_google_app_credentials_form(db: AsyncSession) -> dict[str, str | bool]:
    """Values for the in-app setup form (no secrets)."""
    row = await _get_or_create_row(db)
    cfg = await get_google_runtime_config(db)
    return {
        "client_id": row.google_oauth_client_id or "",
        "redirect_base": row.google_oauth_redirect_base or "",
        "redirect_uri": f"{cfg.redirect_base.rstrip('/')}/api/v1/oauth/google/callback",
        "configured": is_runtime_ready(cfg),
        "has_saved_secret": bool(row.google_oauth_client_secret_encrypted),
    }


async def save_google_app_credentials(
    db: AsyncSession,
    *,
    client_id: str,
    client_secret: str | None,
    redirect_base: str,
) -> None:
    row = await _get_or_create_row(db)
    row.google_oauth_client_id = (client_id or "").strip()
    row.google_oauth_redirect_base = (redirect_base or "").strip()

    if client_secret is not None and client_secret.strip():
        row.google_oauth_client_secret_encrypted = encrypt_secret(client_secret.strip())
    elif not row.google_oauth_client_secret_encrypted and not settings.google_oauth_client_secret.strip():
        if row.google_oauth_client_id:
            raise ValueError(
                "Client secret is required the first time you save Google sign-in settings. "
                "Leave the secret field blank only when one is already stored."
            )

    await db.commit()
    await db.refresh(row)
