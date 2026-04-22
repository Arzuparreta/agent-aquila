"""Conversational connector setup, driven by the agent in chat.

Flow (user-driven connector setup):

1. Agent calls ``start_connector_setup({"provider": "google"|"microsoft"})``.
   Returns a structured "setup card" with the steps the user must follow:
   - which page to open in their browser to register an OAuth app,
   - which fields to copy/paste back,
   - a short-lived ``setup_token`` they don't need to see (we just embed it in the card).
   The chat view renders this as a step-by-step ``ConnectorSetupCard``.

2. User pastes the client ID/secret back. The agent calls
   ``submit_connector_credentials(setup_token, client_id, client_secret, ...)``.
   We persist them via ``instance_oauth_service.save_*_app_credentials``.

3. Agent calls ``start_oauth_flow({"provider": ..., "service": ...})`` to get a URL the
   user opens to grant access. After Google/Microsoft redirects back to the callback,
   ``ConnectorConnection`` rows land in the DB; the proactive worker can then post a
   chat message (e.g. "Connected to Gmail (user@example.com).").

The ``setup_token`` is stored briefly in Redis (or in-process if Redis is unavailable),
mostly to keep the chat card stateful across turns; security still comes from the
authenticated user behind the request.
"""
from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.schemas.connector import ConnectorConnectionCreate
from app.services.connector_service import ConnectorService
from app.services.instance_oauth_service import (
    get_google_app_credentials_form,
    get_google_runtime_config,
    get_microsoft_app_credentials_form,
    get_microsoft_runtime_config,
    get_redirect_base,
    save_google_app_credentials,
    save_microsoft_app_credentials,
)
from app.services.oauth import google_oauth, microsoft_oauth, state_store

# Setup tokens live ~30 minutes; the artist takes their time copy/pasting from another tab.
SETUP_TOKEN_TTL_SECONDS = 60 * 30


@dataclass
class _SetupSession:
    user_id: int
    provider: str
    created_at: float


# Single-process fallback registry. For production with multiple workers we'd swap to Redis.
_SESSIONS: dict[str, _SetupSession] = {}


def _create_setup_token(user: User, provider: str) -> str:
    token = secrets.token_urlsafe(24)
    _SESSIONS[token] = _SetupSession(user_id=user.id, provider=provider, created_at=time.time())
    # Lazy GC — tokens older than the TTL are evicted on each new write.
    cutoff = time.time() - SETUP_TOKEN_TTL_SECONDS
    for k, v in list(_SESSIONS.items()):
        if v.created_at < cutoff:
            _SESSIONS.pop(k, None)
    return token


def _consume_setup_token(token: str, *, expected_user_id: int) -> _SetupSession | None:
    sess = _SESSIONS.get(token)
    if not sess:
        return None
    if sess.user_id != expected_user_id:
        return None
    if time.time() - sess.created_at > SETUP_TOKEN_TTL_SECONDS:
        _SESSIONS.pop(token, None)
        return None
    return sess


# Maps the agent's "service" string to the OAuth intent value the existing route accepts.
_GOOGLE_SERVICE_TO_INTENT: dict[str, str] = {
    "gmail": "gmail",
    "calendar": "calendar",
    "drive": "drive",
    "youtube": "youtube",
    "tasks": "tasks",
    "people": "people",
    "all": "all",
}
_MICROSOFT_SERVICE_TO_INTENT: dict[str, str] = {
    "outlook": "graph_mail",
    "mail": "graph_mail",
    "graph_mail": "graph_mail",
    "calendar": "graph_calendar",
    "graph_calendar": "graph_calendar",
    "drive": "graph_onedrive",
    "onedrive": "graph_onedrive",
    "graph_onedrive": "graph_onedrive",
    "teams": "graph_mail",  # Teams uses the same Graph token as mail
    "all": "graph_all",
}


async def start_setup(db: AsyncSession, user: User, provider: str) -> dict[str, Any]:
    """Returns the structured setup card the agent emits to chat."""
    provider = (provider or "").lower().strip()
    if provider not in ("google", "microsoft", "whatsapp", "icloud_caldav", "github"):
        return {
            "error": "provider must be 'google', 'microsoft', 'whatsapp', 'icloud_caldav', or 'github'",
        }

    redirect_base = await get_redirect_base(db)
    setup_token = _create_setup_token(user, provider)

    if provider == "github":
        return {
            "card_kind": "connector_setup",
            "provider": "github",
            "setup_token": setup_token,
            "console_url": "https://github.com/settings/tokens",
            "steps": [
                {
                    "title": "Create a personal access token",
                    "action_url": "https://github.com/settings/tokens",
                    "instruction": (
                        "Create a **classic** or fine-grained token with at least `repo` (private repos) "
                        "or public-repo scope for issues. Store it like a password — it grants API access to your account."
                    ),
                },
                {
                    "title": "Paste the token",
                    "instruction": "Send the **access_token** (PAT) when ready. It is stored encrypted.",
                    "expects": ["access_token"],
                },
            ],
        }

    if provider == "whatsapp":
        return {
            "card_kind": "connector_setup",
            "provider": "whatsapp",
            "setup_token": setup_token,
            "console_url": "https://developers.facebook.com/",
            "steps": [
                {
                    "title": "Meta for Developers — WhatsApp product",
                    "action_url": "https://developers.facebook.com/apps/",
                    "instruction": (
                        "Create or open an app, add the **WhatsApp** product, and open **WhatsApp → API "
                        "Setup**. Copy the **Temporary or System User** access token (with whatsapp_business_messaging) "
                        "and the **Phone number ID** for your test/production number."
                    ),
                },
                {
                    "title": "Paste token + Phone number ID",
                    "instruction": (
                        "Send me the **access token** and **phone_number_id** when ready. "
                        "Session messages require the user to have messaged you within 24h; "
                        "otherwise use approved **template** messages (Meta policy)."
                    ),
                    "expects": ["access_token", "phone_number_id"],
                },
            ],
        }

    if provider == "icloud_caldav":
        return {
            "card_kind": "connector_setup",
            "provider": "icloud_caldav",
            "setup_token": setup_token,
            "console_url": "https://appleid.apple.com/",
            "steps": [
                {
                    "title": "App-specific password",
                    "action_url": "https://appleid.apple.com/sign-in",
                    "instruction": (
                        "Under **Sign-In and Security**, create an **app-specific password** for this app. "
                        "You cannot use your normal Apple ID password with CalDAV."
                    ),
                },
                {
                    "title": "Paste Apple ID + app password",
                    "instruction": "Send me your **Apple ID email** and the **app-specific password**.",
                    "expects": ["apple_id", "app_password"],
                },
            ],
        }

    if provider == "google":
        existing = await get_google_app_credentials_form(db)
        callback = f"{(redirect_base or '').rstrip('/')}/api/v1/oauth/google/callback"
        return {
            "card_kind": "connector_setup",
            "provider": "google",
            "setup_token": setup_token,
            "configured": bool(existing.get("configured")),
            "redirect_uri_to_register": callback,
            "console_url": "https://console.cloud.google.com/apis/credentials",
            "steps": [
                {
                    "title": "Abre Google Cloud Console",
                    "action_url": "https://console.cloud.google.com/apis/credentials",
                    "instruction": (
                        "Inicia sesión con la misma cuenta de Google que usarás para Gmail. Crea un "
                        "proyecto si no tienes uno y abre 'APIs y servicios → Credenciales'."
                    ),
                },
                {
                    "title": "Crea un ID de cliente OAuth (tipo Aplicación web)",
                    "instruction": (
                        "Pulsa 'Crear credenciales → ID de cliente OAuth → Aplicación web'. En "
                        f"'URIs de redireccionamiento autorizados' añade exactamente:\n\n{callback}"
                    ),
                },
                {
                    "title": "Pega aquí el Client ID y Client Secret",
                    "instruction": "Cuando los tengas, escríbeme: Client ID y Client Secret. Los guardo cifrados.",
                    "expects": ["client_id", "client_secret"],
                },
                {
                    "title": "Conectar",
                    "instruction": (
                        "Te daré un enlace para autorizar Gmail, Calendar, Drive, YouTube, Tasks y "
                        "People (según el servicio que elijas). Solo tienes que aceptar."
                    ),
                },
            ],
        }

    # microsoft
    existing = await get_microsoft_app_credentials_form(db)
    callback = f"{(redirect_base or '').rstrip('/')}/api/v1/oauth/microsoft/callback"
    return {
        "card_kind": "connector_setup",
        "provider": "microsoft",
        "setup_token": setup_token,
        "configured": bool(existing.get("configured")),
        "redirect_uri_to_register": callback,
        "console_url": "https://portal.azure.com/#blade/Microsoft_AAD_RegisteredApps/ApplicationsListBlade",
        "steps": [
            {
                "title": "Abre Azure → Registros de aplicaciones",
                "action_url": "https://portal.azure.com/#blade/Microsoft_AAD_RegisteredApps/ApplicationsListBlade",
                "instruction": "Crea un nuevo registro de aplicación (puedes llamarlo como quieras).",
            },
            {
                "title": "Configura el URI de redirección (tipo Web)",
                "instruction": f"En el registro, añade este URI de redirección de tipo 'Web':\n\n{callback}",
            },
            {
                "title": "Crea un client secret",
                "instruction": "En 'Certificados y secretos → Nuevo secreto de cliente'. Copia el valor (no el ID).",
            },
            {
                "title": "Pega aquí Client ID, Client Secret y Tenant",
                "instruction": (
                    "Escríbeme: Client ID, Client Secret y Tenant (el dominio de tu organización o 'common')."
                ),
                "expects": ["client_id", "client_secret", "tenant"],
            },
            {
                "title": "Conectar",
                "instruction": "Te paso un enlace para autorizar Outlook / Calendar / OneDrive / Teams.",
            },
        ],
    }


async def submit_credentials(
    db: AsyncSession,
    user: User,
    *,
    setup_token: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str | None = None,
    tenant: str | None = None,
) -> dict[str, Any]:
    sess = _consume_setup_token(setup_token, expected_user_id=user.id)
    if not sess:
        return {"error": "setup_token invalid or expired; ask me to start the setup again"}

    redirect_base = await get_redirect_base(db)
    if redirect_uri:
        # Strip the path; we only store the public origin.
        from urllib.parse import urlparse

        parsed = urlparse(redirect_uri)
        if parsed.scheme and parsed.netloc:
            redirect_base = f"{parsed.scheme}://{parsed.netloc}"

    try:
        if sess.provider == "google":
            await save_google_app_credentials(
                db,
                client_id=client_id,
                client_secret=client_secret,
                redirect_base=redirect_base,
            )
        else:
            await save_microsoft_app_credentials(
                db,
                client_id=client_id,
                client_secret=client_secret,
                tenant=(tenant or "common"),
                redirect_base=redirect_base,
            )
    except ValueError as exc:
        return {"error": str(exc)}

    return {"ok": True, "provider": sess.provider, "next": "ask_me_to_connect"}


async def submit_whatsapp_credentials(
    db: AsyncSession,
    user: User,
    *,
    setup_token: str,
    access_token: str,
    phone_number_id: str,
    graph_api_version: str | None = None,
) -> dict[str, Any]:
    sess = _consume_setup_token(setup_token, expected_user_id=user.id)
    if not sess or sess.provider != "whatsapp":
        return {"error": "setup_token invalid or expired; call start_connector_setup for whatsapp again"}
    pnid = str(phone_number_id).strip()
    tok = str(access_token).strip()
    if not pnid or not tok:
        return {"error": "access_token and phone_number_id are required"}
    ver = (graph_api_version or "v21.0").strip()
    if not ver.startswith("v"):
        ver = f"v{ver}"
    await ConnectorService.create_connection(
        db,
        user,
        ConnectorConnectionCreate(
            provider="whatsapp_business",
            label=f"WhatsApp · {pnid}",
            credentials={
                "access_token": tok,
                "phone_number_id": pnid,
                "graph_api_version": ver,
            },
            meta={"source": "chat_setup"},
        ),
    )
    return {"ok": True, "provider": "whatsapp_business", "next": "connected"}


async def submit_github_credentials(
    db: AsyncSession,
    user: User,
    *,
    setup_token: str,
    access_token: str,
) -> dict[str, Any]:
    """Persist a GitHub PAT for REST API access (read issues/repos)."""
    sess = _consume_setup_token(setup_token, expected_user_id=user.id)
    if not sess or sess.provider != "github":
        return {"error": "setup_token invalid or expired; call start_connector_setup for github again"}
    tok = str(access_token or "").strip()
    if not tok:
        return {"error": "access_token is required"}
    await ConnectorService.create_connection(
        db,
        user,
        ConnectorConnectionCreate(
            provider="github",
            label="GitHub",
            credentials={"access_token": tok},
            meta={"source": "chat_setup"},
        ),
    )
    return {"ok": True, "provider": "github", "next": "connected"}


async def submit_icloud_caldav_credentials(
    db: AsyncSession,
    user: User,
    *,
    setup_token: str,
    apple_id: str,
    app_password: str,
) -> dict[str, Any]:
    sess = _consume_setup_token(setup_token, expected_user_id=user.id)
    if not sess or sess.provider != "icloud_caldav":
        return {"error": "setup_token invalid or expired; call start_connector_setup for icloud_caldav again"}
    uid = str(apple_id).strip()
    pw = str(app_password).strip()
    if not uid or not pw:
        return {"error": "apple_id and app_password are required"}
    await ConnectorService.create_connection(
        db,
        user,
        ConnectorConnectionCreate(
            provider="icloud_caldav",
            label=f"iCloud · {uid}",
            credentials={"username": uid, "password": pw},
            meta={"source": "chat_setup"},
        ),
    )
    return {"ok": True, "provider": "icloud_caldav", "next": "connected"}


async def start_oauth(
    db: AsyncSession, user: User, *, provider: str, service: str
) -> dict[str, Any]:
    provider = (provider or "").lower().strip()
    service = (service or "").lower().strip() or "all"

    if provider == "google":
        cfg = await get_google_runtime_config(db)
        if not google_oauth.is_runtime_ready(cfg):
            return {"error": "google not configured yet; call start_connector_setup first"}
        intent = _GOOGLE_SERVICE_TO_INTENT.get(service, "all")
        scopes = google_oauth.scopes_for_intent(intent)
        state = await state_store.create_state(
            state_store.StatePayload(
                user_id=user.id,
                provider="google",
                intent=intent,
                scopes=scopes,
                redirect_after=None,
            )
        )
        url = google_oauth.build_authorize_url(state, scopes, cfg)
        return {
            "card_kind": "oauth_authorize",
            "provider": "google",
            "service": service,
            "authorize_url": url,
            "instruction": "Toca el enlace para autorizar el acceso. Cuando termines, vuelve aquí.",
        }

    if provider == "microsoft":
        cfg = await get_microsoft_runtime_config(db)
        if not microsoft_oauth.is_runtime_ready(cfg):
            return {"error": "microsoft not configured yet; call start_connector_setup first"}
        intent = _MICROSOFT_SERVICE_TO_INTENT.get(service, "graph_all")
        scopes = microsoft_oauth.scopes_for_intent(intent)
        state = await state_store.create_state(
            state_store.StatePayload(
                user_id=user.id,
                provider="microsoft",
                intent=intent,
                scopes=scopes,
                redirect_after=None,
            )
        )
        url = microsoft_oauth.build_authorize_url(state, scopes, cfg)
        return {
            "card_kind": "oauth_authorize",
            "provider": "microsoft",
            "service": service,
            "authorize_url": url,
            "instruction": "Toca el enlace para autorizar el acceso. Cuando termines, vuelve aquí.",
        }

    return {"error": "provider must be 'google' or 'microsoft'"}
