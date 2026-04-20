"""Live Gmail proxy.

Every endpoint in this router talks straight to the Gmail REST API on
behalf of the authenticated user — there is **no local mirror** any more.
The frontend Inbox, the agent's Gmail tools, and any future Gmail-aware
feature should all go through this router (or the matching ``GmailClient``
called from the agent dispatcher) so we have exactly one code path to
audit when scopes / errors / retries need to change.

Routing convention:
- ``GET /gmail/messages`` — list message ids (free-form ``q`` like the Gmail
  search bar, ``page_token`` pagination).
- ``GET /gmail/messages/{id}`` — full message payload.
- ``POST /gmail/messages/{id}/modify`` — add/remove labels.
- ``POST /gmail/messages/{id}/trash|untrash`` — destructive but reversible.
- ``POST /gmail/threads/{id}/modify`` — same shape, thread-scoped.
- ``GET /gmail/labels`` — list all labels (used by the agent + Settings).
- ``GET|POST|DELETE /gmail/filters`` — manage server-side filters
  (requires the new ``gmail.settings.basic`` scope).

The connection id is passed as a query parameter (``connection_id=...``)
on every endpoint. If it is omitted, the router falls back to the user's
single Gmail connection — convenient because almost every user has only
one. Multi-account users get a clear 400 telling them to disambiguate.

Metadata responses (``format=metadata``) are TTL-cached in
``app.services.gmail_metadata_cache`` and shared with agent Gmail tools.
"""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.connector_connection import ConnectorConnection
from app.models.user import User
from app.services.connectors.gmail_client import (
    GmailAPIError,
    GmailClient,
    GmailRateLimited,
)
from app.services.gmail_metadata_cache import (
    get_message_metadata,
    invalidate_connection,
    invalidate_message,
    put_message_metadata,
    get_thread as cache_get_thread,
    put_thread as cache_put_thread,
)
from app.services.oauth import TokenManager
from app.services.oauth.errors import ConnectorNeedsReauth, OAuthError

router = APIRouter(prefix="/gmail", tags=["gmail"], dependencies=[Depends(get_current_user)])

GMAIL_PROVIDERS = ("google_gmail", "gmail")


async def _resolve_gmail_connection(
    db: AsyncSession, user: User, connection_id: int | None
) -> ConnectorConnection:
    """Pick the Gmail connection to use.

    When ``connection_id`` is supplied we honour it (and validate ownership).
    Otherwise we look up the user's Gmail connections; exactly one is the
    happy path, zero or many is a 400 with a friendly hint.
    """
    if connection_id is not None:
        row = await db.get(ConnectorConnection, connection_id)
        if not row or row.user_id != user.id:
            raise HTTPException(status_code=404, detail="Connection not found")
        if row.provider not in GMAIL_PROVIDERS:
            raise HTTPException(
                status_code=400,
                detail=f"Connection {connection_id} is not a Gmail connection.",
            )
        return row

    stmt = (
        select(ConnectorConnection)
        .where(
            ConnectorConnection.user_id == user.id,
            ConnectorConnection.provider.in_(GMAIL_PROVIDERS),
        )
        .order_by(ConnectorConnection.created_at.desc())
    )
    rows = list((await db.execute(stmt)).scalars().all())
    if not rows:
        raise HTTPException(
            status_code=400,
            detail="No Gmail connection. Connect Gmail in Settings → Connectors.",
        )
    if len(rows) > 1:
        raise HTTPException(
            status_code=400,
            detail=(
                "Multiple Gmail connections — pass ?connection_id=... to choose. "
                f"Available ids: {', '.join(str(r.id) for r in rows)}"
            ),
        )
    return rows[0]


async def _client_for(db: AsyncSession, row: ConnectorConnection) -> GmailClient:
    try:
        token = await TokenManager.get_valid_access_token(db, row)
    except ConnectorNeedsReauth as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"kind": "needs_reauth", "message": str(exc), "connection_id": row.id},
        ) from exc
    except OAuthError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return GmailClient(token)


def _wrap_api_error(exc: GmailAPIError) -> HTTPException:
    # Re-raise as a clean HTTP error preserving the upstream code so the
    # frontend can branch on 401/403 (reauth) vs 404 (deleted message) vs
    # 429 (rate-limited, render countdown) vs 5xx (transient). We strip the
    # upstream HTML to keep responses small.
    headers: dict[str, str] | None = None
    detail: Any = exc.detail[:500]
    if isinstance(exc, GmailRateLimited):
        retry_after = int(round(exc.retry_after or 30.0))
        headers = {"Retry-After": str(retry_after)}
        raw = (exc.detail or "").strip()
        detail = {
            "kind": "gmail_rate_limited",
            "retry_after_seconds": retry_after,
            "message": (
                "Gmail está limitando tus peticiones. Vuelve a intentar en "
                f"{retry_after}s."
            ),
            # Truncated Gmail error JSON/text — use DevTools → Network → this
            # response to confirm the 429 really came from Google, not a proxy.
            "upstream": raw[:800] if raw else None,
        }
    return HTTPException(
        status_code=exc.status_code or 502, detail=detail, headers=headers
    )


# Metadata TTL cache: ``app.services.gmail_metadata_cache`` (shared with agent tools).
# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------
def _decode_header(headers: list[dict[str, Any]], name: str) -> str:
    """Return the first header value matching ``name`` (case-insensitive)."""
    target = name.lower()
    for h in headers or []:
        if str(h.get("name", "")).lower() == target:
            return str(h.get("value") or "")
    return ""


def _split_sender(raw: str) -> tuple[str, str]:
    """Split ``"Alice <a@b>"`` into ``("Alice", "a@b")``. Either side may be empty."""
    raw = (raw or "").strip()
    if "<" in raw and ">" in raw:
        name, _, rest = raw.partition("<")
        email, _, _ = rest.partition(">")
        return name.strip(' "'), email.strip()
    return ("", raw)


def _summarize_message(msg: dict[str, Any]) -> dict[str, Any]:
    """Flatten a Gmail message JSON into the row shape the inbox renders."""
    payload = msg.get("payload") or {}
    headers = payload.get("headers") or []
    sender_name, sender_email = _split_sender(_decode_header(headers, "From"))
    label_ids = msg.get("labelIds") or []
    return {
        "id": msg.get("id"),
        "thread_id": msg.get("threadId"),
        "snippet": msg.get("snippet") or "",
        "subject": _decode_header(headers, "Subject"),
        "sender_name": sender_name or None,
        "sender_email": sender_email,
        "to": _decode_header(headers, "To"),
        "internal_date": msg.get("internalDate"),
        "label_ids": label_ids,
        "is_unread": "UNREAD" in label_ids,
    }


@router.get("/messages")
async def list_messages(
    connection_id: int | None = Query(default=None),
    q: str | None = Query(
        default=None, description="Gmail search query, e.g. 'from:bob is:unread'"
    ),
    label_ids: list[str] | None = Query(default=None, alias="label_id"),
    page_token: str | None = Query(default=None),
    max_results: int = Query(default=25, ge=1, le=100),
    detail: str = Query(
        default="metadata",
        description="`ids` returns Gmail's bare list response; `metadata` enriches every row with subject/from/snippet (one extra API call per row).",
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    row = await _resolve_gmail_connection(db, current_user, connection_id)
    client = await _client_for(db, row)
    try:
        listing = await client.list_messages(
            page_token=page_token, q=q, label_ids=label_ids, max_results=max_results
        )
    except GmailAPIError as exc:
        raise _wrap_api_error(exc)

    if detail != "metadata":
        return listing

    # Hydrate each row with header + snippet metadata. We fan-out in parallel
    # because Gmail's `list` call only returns ids; the inbox needs subject,
    # sender, snippet and label_ids to render. Concurrency is intentionally
    # low (3) because Gmail's per-user QPS cap is tight, and an in-process
    # cache absorbs StrictMode double-fires + back-button reloads — the
    # second view of the same inbox does zero upstream calls.
    msg_refs = listing.get("messages") or []
    sem = asyncio.Semaphore(3)
    rate_limit_hit: GmailRateLimited | None = None

    async def _fetch(mid: str) -> dict[str, Any] | None:
        nonlocal rate_limit_hit
        cached = get_message_metadata(row.id, mid)
        if cached is not None:
            return cached
        async with sem:
            try:
                payload = await client.get_message(mid, format="metadata")
            except GmailRateLimited as exc:
                # First 429 wins; we'll re-raise after the gather so the
                # frontend can show a real countdown instead of a partial
                # list with mystery gaps.
                if rate_limit_hit is None:
                    rate_limit_hit = exc
                return None
            except GmailAPIError:
                return None
        put_message_metadata(row.id, mid, payload)
        return payload

    fetched = await asyncio.gather(*(_fetch(str(m["id"])) for m in msg_refs if m.get("id")))
    if rate_limit_hit is not None:
        raise _wrap_api_error(rate_limit_hit)
    rows = [_summarize_message(m) for m in fetched if m]
    return {
        "messages": rows,
        "next_page_token": listing.get("nextPageToken"),
        "result_size_estimate": listing.get("resultSizeEstimate"),
    }


@router.get("/messages/{message_id}")
async def get_message(
    message_id: str,
    connection_id: int | None = Query(default=None),
    format: str = Query(default="full"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    row = await _resolve_gmail_connection(db, current_user, connection_id)
    if format == "metadata":
        cached = get_message_metadata(row.id, message_id)
        if cached is not None:
            return cached
    client = await _client_for(db, row)
    try:
        payload = await client.get_message(message_id, format=format)
    except GmailAPIError as exc:
        raise _wrap_api_error(exc)
    if format == "metadata":
        put_message_metadata(row.id, message_id, payload)
    return payload


@router.post("/messages/{message_id}/modify")
async def modify_message(
    message_id: str,
    connection_id: int | None = Query(default=None),
    payload: dict[str, Any] = Body(default_factory=dict),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    row = await _resolve_gmail_connection(db, current_user, connection_id)
    client = await _client_for(db, row)
    try:
        result = await client.modify_message(
            message_id,
            add_label_ids=payload.get("add_label_ids"),
            remove_label_ids=payload.get("remove_label_ids"),
        )
    except GmailAPIError as exc:
        raise _wrap_api_error(exc)
    invalidate_message(row.id, message_id)
    return result


@router.post("/messages/{message_id}/trash")
async def trash_message(
    message_id: str,
    connection_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    row = await _resolve_gmail_connection(db, current_user, connection_id)
    client = await _client_for(db, row)
    try:
        result = await client.trash_message(message_id)
    except GmailAPIError as exc:
        raise _wrap_api_error(exc)
    invalidate_message(row.id, message_id)
    return result


@router.post("/messages/{message_id}/untrash")
async def untrash_message(
    message_id: str,
    connection_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    row = await _resolve_gmail_connection(db, current_user, connection_id)
    client = await _client_for(db, row)
    try:
        result = await client.untrash_message(message_id)
    except GmailAPIError as exc:
        raise _wrap_api_error(exc)
    invalidate_message(row.id, message_id)
    return result


# ---------------------------------------------------------------------------
# Threads
# ---------------------------------------------------------------------------
@router.get("/threads")
async def list_threads(
    connection_id: int | None = Query(default=None),
    q: str | None = Query(default=None),
    label_ids: list[str] | None = Query(default=None, alias="label_id"),
    page_token: str | None = Query(default=None),
    max_results: int = Query(default=25, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    row = await _resolve_gmail_connection(db, current_user, connection_id)
    client = await _client_for(db, row)
    try:
        return await client.list_threads(
            page_token=page_token, q=q, label_ids=label_ids, max_results=max_results
        )
    except GmailAPIError as exc:
        raise _wrap_api_error(exc)


@router.get("/threads/{thread_id}")
async def get_thread(
    thread_id: str,
    connection_id: int | None = Query(default=None),
    format: str = Query(default="metadata"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    row = await _resolve_gmail_connection(db, current_user, connection_id)
    if format == "metadata":
        cached = cache_get_thread(row.id, thread_id, format)
        if cached is not None:
            return cached
    client = await _client_for(db, row)
    try:
        payload = await client.get_thread(thread_id, format=format)
    except GmailAPIError as exc:
        raise _wrap_api_error(exc)
    if format == "metadata":
        cache_put_thread(row.id, thread_id, format, payload)
    return payload


@router.post("/threads/{thread_id}/modify")
async def modify_thread(
    thread_id: str,
    connection_id: int | None = Query(default=None),
    payload: dict[str, Any] = Body(default_factory=dict),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    row = await _resolve_gmail_connection(db, current_user, connection_id)
    client = await _client_for(db, row)
    try:
        result = await client.modify_thread(
            thread_id,
            add_label_ids=payload.get("add_label_ids"),
            remove_label_ids=payload.get("remove_label_ids"),
        )
    except GmailAPIError as exc:
        raise _wrap_api_error(exc)
    invalidate_connection(row.id)
    return result


@router.post("/threads/{thread_id}/trash")
async def trash_thread(
    thread_id: str,
    connection_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    row = await _resolve_gmail_connection(db, current_user, connection_id)
    client = await _client_for(db, row)
    try:
        result = await client.trash_thread(thread_id)
    except GmailAPIError as exc:
        raise _wrap_api_error(exc)
    invalidate_connection(row.id)
    return result


@router.post("/threads/{thread_id}/untrash")
async def untrash_thread(
    thread_id: str,
    connection_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    row = await _resolve_gmail_connection(db, current_user, connection_id)
    client = await _client_for(db, row)
    try:
        result = await client.untrash_thread(thread_id)
    except GmailAPIError as exc:
        raise _wrap_api_error(exc)
    invalidate_connection(row.id)
    return result


# ---------------------------------------------------------------------------
# Labels & filters
# ---------------------------------------------------------------------------
@router.get("/labels")
async def list_labels(
    connection_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    row = await _resolve_gmail_connection(db, current_user, connection_id)
    client = await _client_for(db, row)
    try:
        return await client.list_labels()
    except GmailAPIError as exc:
        raise _wrap_api_error(exc)


@router.get("/filters")
async def list_filters(
    connection_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    row = await _resolve_gmail_connection(db, current_user, connection_id)
    client = await _client_for(db, row)
    try:
        return await client.list_filters()
    except GmailAPIError as exc:
        raise _wrap_api_error(exc)


@router.post("/filters")
async def create_filter(
    payload: dict[str, Any] = Body(...),
    connection_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    criteria = payload.get("criteria") or {}
    action = payload.get("action") or {}
    if not criteria or not action:
        raise HTTPException(status_code=400, detail="payload requires both 'criteria' and 'action'")
    row = await _resolve_gmail_connection(db, current_user, connection_id)
    client = await _client_for(db, row)
    try:
        return await client.create_filter(criteria=criteria, action=action)
    except GmailAPIError as exc:
        raise _wrap_api_error(exc)


@router.delete("/filters/{filter_id}")
async def delete_filter(
    filter_id: str,
    connection_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    row = await _resolve_gmail_connection(db, current_user, connection_id)
    client = await _client_for(db, row)
    try:
        return await client.delete_filter(filter_id)
    except GmailAPIError as exc:
        raise _wrap_api_error(exc)
