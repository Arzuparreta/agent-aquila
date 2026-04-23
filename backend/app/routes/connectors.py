from __future__ import annotations

import asyncio

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
from app.services.connectors.github_client import GitHubAPIError, GitHubClient
from app.services.connectors.discord_bot_client import DiscordAPIError, DiscordBotClient
from app.services.connectors.linear_client import LinearAPIError, LinearClient
from app.services.connectors.notion_client import NotionAPIError, NotionClient
from app.services.connectors.slack_client import SlackAPIError, SlackClient
from app.services.connectors.telegram_bot_client import TelegramAPIError, TelegramBotClient
from app.services.connectors.icloud_caldav_client import ICloudCalDAVClient, ICloudCalDAVError
from app.services.connectors.icloud_contacts_client import ICloudContactsError, verify_contacts_sync
from app.services.connectors.icloud_drive_client import ICloudDriveError, verify_drive_sync
from app.services.connectors.whatsapp_client import (
    DEFAULT_GRAPH_VERSION,
    WhatsAppAPIError,
    WhatsAppClient,
)
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

    if row.provider == "whatsapp_business":
        creds = ConnectorService.decrypt_credentials(row)
        token = str(creds.get("access_token") or "").strip()
        pnid = str(creds.get("phone_number_id") or "").strip()
        ver = str(creds.get("graph_api_version") or DEFAULT_GRAPH_VERSION).strip()
        if not ver.startswith("v"):
            ver = f"v{ver}"
        if not token or not pnid:
            return ConnectorHealthResponse(
                ok=False,
                provider=row.provider,
                error="Missing access_token or phone_number_id in stored credentials.",
            )
        try:
            client = WhatsAppClient(token, pnid, api_version=ver)
            info = await client.verify_phone_number()
            display = str(info.get("display_phone_number") or info.get("verified_name") or pnid)
            return ConnectorHealthResponse(ok=True, provider=row.provider, account=display or None)
        except WhatsAppAPIError as exc:
            return ConnectorHealthResponse(ok=False, provider=row.provider, error=exc.detail[:500])

    if row.provider == "icloud_caldav":
        creds = ConnectorService.decrypt_credentials(row)
        uid = str(creds.get("username") or creds.get("apple_id") or "").strip()
        pw = str(creds.get("password") or creds.get("app_password") or "").strip()
        china = bool(creds.get("china_mainland"))
        if not uid or not pw:
            return ConnectorHealthResponse(
                ok=False,
                provider=row.provider,
                error="Missing Apple ID (username) or app password in stored credentials.",
            )
        cal_err: str | None = None
        n_cal = 0
        try:
            cal_client = ICloudCalDAVClient(uid, pw)
            calendars = await cal_client.list_calendars()
            n_cal = len(calendars)
        except ICloudCalDAVError as exc:
            cal_err = exc.detail[:500]

        drive_err: str | None = None
        drive_root_n = 0
        try:
            info = await asyncio.to_thread(
                verify_drive_sync,
                uid,
                pw,
                connection_id=row.id,
                china_mainland=china,
            )
            drive_root_n = int(info.get("root_item_count") or 0)
        except ICloudDriveError as exc:
            drive_err = exc.detail[:500]

        contacts_err: str | None = None
        contacts_sample = 0
        try:
            cinfo = await asyncio.to_thread(
                verify_contacts_sync,
                uid,
                pw,
                connection_id=row.id,
                china_mainland=china,
            )
            contacts_sample = int(cinfo.get("sample_contact_count") or 0)
        except ICloudContactsError as exc:
            contacts_err = exc.detail[:500]

        account_bits = [
            uid,
            f"{n_cal} calendars" if not cal_err else "Calendar: error",
            f"Drive: {drive_root_n} items at root" if not drive_err else "Drive: error",
            f"Contacts: sampled {contacts_sample}" if not contacts_err else "Contacts: error",
        ]
        account_summary = " · ".join(account_bits)
        if cal_err or drive_err or contacts_err:
            err_parts = []
            if cal_err:
                err_parts.append(f"CalDAV: {cal_err}")
            if drive_err:
                err_parts.append(f"iCloud Drive (PyiCloud): {drive_err}")
            if contacts_err:
                err_parts.append(f"CardDAV contacts: {contacts_err}")
            return ConnectorHealthResponse(
                ok=False,
                provider=row.provider,
                account=account_summary,
                error="; ".join(err_parts),
            )
        return ConnectorHealthResponse(ok=True, provider=row.provider, account=account_summary)

    if row.provider == "github":
        creds = ConnectorService.decrypt_credentials(row)
        token = str(creds.get("access_token") or "").strip()
        if not token:
            return ConnectorHealthResponse(
                ok=False,
                provider=row.provider,
                error="Missing access_token (PAT) in stored credentials.",
            )
        try:
            client = GitHubClient(token)
            user_payload = await client.get_authenticated_user()
            login = str(user_payload.get("login") or "")
            return ConnectorHealthResponse(ok=True, provider=row.provider, account=login or None)
        except GitHubAPIError as exc:
            return ConnectorHealthResponse(ok=False, provider=row.provider, error=exc.detail[:500])

    if row.provider == "slack_bot":
        creds = ConnectorService.decrypt_credentials(row)
        tok = str(creds.get("bot_token") or creds.get("access_token") or "").strip()
        if not tok:
            return ConnectorHealthResponse(
                ok=False,
                provider=row.provider,
                error="Missing bot_token in stored credentials.",
            )
        try:
            client = SlackClient(tok)
            info = await client.auth_test()
            team = str(info.get("team") or info.get("url") or "")
            who = str(info.get("user") or info.get("user_id") or "")
            label = " · ".join(p for p in (team, who) if p) or "Slack"
            return ConnectorHealthResponse(ok=True, provider=row.provider, account=label)
        except SlackAPIError as exc:
            return ConnectorHealthResponse(ok=False, provider=row.provider, error=exc.detail[:500])

    if row.provider == "linear":
        creds = ConnectorService.decrypt_credentials(row)
        key = str(creds.get("api_key") or creds.get("access_token") or "").strip()
        if not key:
            return ConnectorHealthResponse(
                ok=False,
                provider=row.provider,
                error="Missing api_key in stored credentials.",
            )
        try:
            client = LinearClient(key)
            data = await client._post("query { viewer { id name } }", {})
            viewer = data.get("viewer") or {}
            label = str(viewer.get("name") or viewer.get("id") or "Linear")
            return ConnectorHealthResponse(ok=True, provider=row.provider, account=label)
        except LinearAPIError as exc:
            return ConnectorHealthResponse(ok=False, provider=row.provider, error=exc.detail[:500])

    if row.provider == "notion":
        creds = ConnectorService.decrypt_credentials(row)
        key = str(creds.get("api_key") or "").strip()
        if not key:
            return ConnectorHealthResponse(
                ok=False,
                provider=row.provider,
                error="Missing api_key in stored credentials.",
            )
        try:
            client = NotionClient(key)
            me = await client._request("GET", "/users/me")
            acc = str((me or {}).get("name") or (me or {}).get("id") or "Notion")
            return ConnectorHealthResponse(ok=True, provider=row.provider, account=acc)
        except NotionAPIError as exc:
            return ConnectorHealthResponse(ok=False, provider=row.provider, error=exc.detail[:500])

    if row.provider == "telegram_bot":
        creds = ConnectorService.decrypt_credentials(row)
        tok = str(creds.get("bot_token") or "").strip()
        if not tok:
            return ConnectorHealthResponse(
                ok=False,
                provider=row.provider,
                error="Missing bot_token in stored credentials.",
            )
        try:
            client = TelegramBotClient(tok)
            data = await client.get_me()
            result = data.get("result") if isinstance(data, dict) else None
            uname = ""
            if isinstance(result, dict):
                uname = str(result.get("username") or result.get("first_name") or result.get("id") or "")
            label = f"@{uname}" if uname and not uname.startswith("@") else uname or "Telegram"
            return ConnectorHealthResponse(ok=True, provider=row.provider, account=label)
        except TelegramAPIError as exc:
            return ConnectorHealthResponse(ok=False, provider=row.provider, error=exc.detail[:500])

    if row.provider == "discord_bot":
        creds = ConnectorService.decrypt_credentials(row)
        tok = str(creds.get("bot_token") or "").strip()
        if not tok:
            return ConnectorHealthResponse(
                ok=False,
                provider=row.provider,
                error="Missing bot_token in stored credentials.",
            )
        try:
            client = DiscordBotClient(tok)
            me = await client.get_me()
            if not isinstance(me, dict):
                return ConnectorHealthResponse(ok=True, provider=row.provider, account="Discord")
            handle = str(me.get("username") or me.get("global_name") or me.get("id") or "")
            return ConnectorHealthResponse(ok=True, provider=row.provider, account=handle or None)
        except DiscordAPIError as exc:
            return ConnectorHealthResponse(ok=False, provider=row.provider, error=exc.detail[:500])

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
