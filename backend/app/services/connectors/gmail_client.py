"""Thin Gmail REST client with retry + backoff.

After the OpenClaw-style refactor this file is the *only* place that
talks to Gmail — both reads (list/get message, list labels) and writes
(modify labels, trash, untrash, filters). Sending email goes through
``email_adapters.send_email`` which builds the MIME envelope.

Docs: https://developers.google.com/gmail/api/reference/rest
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import re
from datetime import datetime, timezone
from typing import Any

import httpx

BASE = "https://gmail.googleapis.com/gmail/v1/users/me"
logger = logging.getLogger(__name__)

# Gmail user-rate 429 bodies look like:
# "User-rate limit exceeded.  Retry after 2026-04-19T23:39:25.148Z"
_GMAIL_RETRY_AFTER_ISO = re.compile(
    r"Retry\s+after\s+(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z)",
    re.IGNORECASE,
)


class GmailAPIError(Exception):
    def __init__(self, status_code: int, detail: str, *, retry_after: float | None = None) -> None:
        self.status_code = status_code
        self.detail = detail
        # Seconds the upstream told us to wait. Surfaced upstream so the
        # router can put it on a ``Retry-After`` HTTP header and the UI can
        # render an honest countdown.
        self.retry_after = retry_after
        super().__init__(f"Gmail API {status_code}: {detail[:500]}")


class GmailRateLimited(GmailAPIError):
    """Convenience subclass for 429s so callers can branch on `isinstance`."""

    def __init__(self, detail: str, retry_after: float | None) -> None:
        super().__init__(429, detail, retry_after=retry_after)


class GmailClient:
    """Lightweight async client around the Gmail REST API.

    The access token is passed at construction time; refresh is the caller's responsibility
    (via `TokenManager.get_valid_access_token`) — the client itself is stateless on auth.

    Retry policy: we **never** sit on the request socket waiting for Gmail to
    forgive us. The previous policy (5 retries, 30 s max wait per attempt)
    routinely held requests for 30–150 s, which Next.js' dev proxy would
    cut as ECONNRESET and surface as an opaque 500. Now:

    - 5xx: one quick retry with jittered ~0.7 s backoff.
    - 429: surface **immediately** as :class:`GmailRateLimited` carrying a
      retry hint: prefer the ISO deadline in the JSON body (``Retry after …Z``)
      when present, else the ``Retry-After`` header, else 30 s. The route
      returns a clean 429 so the UI can render a countdown. Sitting on the socket
      doesn't help — Gmail's per-user quota refills in wall-clock time
      regardless of whether we're blocking on it.
    """

    def __init__(self, access_token: str, *, timeout: float = 30.0) -> None:
        self._token = access_token
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    @staticmethod
    def _parse_retry_after(value: str | None) -> float | None:
        if not value:
            return None
        try:
            return max(0.0, float(value))
        except ValueError:
            return None

    @staticmethod
    def _seconds_until_gmail_retry_deadline(body: str) -> float | None:
        """Parse ``Retry after <ISO8601>Z`` from Gmail's JSON error body.

        Returns seconds from *now* (UTC) until that instant, or ``None`` if
        no deadline was found. Minimum 1 s so the UI never shows ``0s``.
        """
        texts: list[str] = []
        raw = (body or "").strip()
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            texts.append(raw)
        else:
            if isinstance(data, dict):
                err = data.get("error")
                if isinstance(err, dict):
                    m = err.get("message")
                    if isinstance(m, str):
                        texts.append(m)
                    for item in err.get("errors") or []:
                        if isinstance(item, dict):
                            em = item.get("message")
                            if isinstance(em, str):
                                texts.append(em)
            if not texts:
                texts.append(raw)

        deadline_iso: str | None = None
        for t in texts:
            match = _GMAIL_RETRY_AFTER_ISO.search(t)
            if match:
                deadline_iso = match.group(1)
                break
        if not deadline_iso:
            return None

        s = deadline_iso.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            deadline = datetime.fromisoformat(s)
        except ValueError:
            return None
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        delta = (deadline - now).total_seconds()
        # Slight clock skew or same-second retry → still show a short wait.
        return max(1.0, delta)

    async def _request(
        self, method: str, path: str, *, params: dict[str, Any] | None = None, json: Any | None = None
    ) -> dict[str, Any]:
        url = f"{BASE}{path}"
        # Two attempts total for 5xx (one retry); 429 is never retried — we
        # surface it so the caller can decide.
        for attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.request(
                        method, url, params=params, json=json, headers=self._headers()
                    )
            except httpx.TimeoutException as exc:
                if attempt == 0:
                    await asyncio.sleep(0.5 + random.uniform(0, 0.3))
                    continue
                raise GmailAPIError(504, f"Gmail timeout: {exc}") from exc

            if resp.status_code == 429:
                text = resp.text or ""
                retry_from_body = self._seconds_until_gmail_retry_deadline(text)
                retry_header = self._parse_retry_after(resp.headers.get("Retry-After"))
                if retry_from_body is not None:
                    retry_after = retry_from_body
                elif retry_header is not None:
                    retry_after = retry_header
                else:
                    retry_after = 30.0
                # Log the upstream body so operators can confirm this really is
                # Google's quota/rate response (vs a mistaken 429 from a proxy).
                logger.warning(
                    "Gmail API returned HTTP 429 (Retry-After=%r, computed_s=%s): %s",
                    resp.headers.get("Retry-After"),
                    retry_after,
                    text[:800],
                )
                raise GmailRateLimited(text, retry_after)
            if resp.status_code >= 500:
                if attempt == 0:
                    await asyncio.sleep(0.5 + random.uniform(0, 0.3))
                    continue
                raise GmailAPIError(resp.status_code, resp.text)
            if resp.status_code >= 400:
                raise GmailAPIError(resp.status_code, resp.text)
            if not resp.content:
                return {}
            return resp.json()
        raise GmailAPIError(502, "Gmail API retries exhausted")

    async def get_profile(self) -> dict[str, Any]:
        return await self._request("GET", "/profile")

    async def list_messages(
        self,
        *,
        page_token: str | None = None,
        q: str | None = None,
        label_ids: list[str] | None = None,
        max_results: int = 100,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"maxResults": max_results}
        if page_token:
            params["pageToken"] = page_token
        if q:
            params["q"] = q
        if label_ids:
            params["labelIds"] = label_ids
        return await self._request("GET", "/messages", params=params)

    async def get_message(self, message_id: str, *, format: str = "full") -> dict[str, Any]:
        return await self._request("GET", f"/messages/{message_id}", params={"format": format})

    async def list_history(
        self,
        *,
        start_history_id: str,
        page_token: str | None = None,
        history_types: list[str] | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"startHistoryId": start_history_id}
        if page_token:
            params["pageToken"] = page_token
        if history_types:
            params["historyTypes"] = history_types
        return await self._request("GET", "/history", params=params)

    async def get_attachment(self, message_id: str, attachment_id: str) -> dict[str, Any]:
        return await self._request(
            "GET", f"/messages/{message_id}/attachments/{attachment_id}"
        )

    async def list_labels(self) -> dict[str, Any]:
        return await self._request("GET", "/labels")

    # ------------------------------------------------------------------
    # Threads
    # ------------------------------------------------------------------
    async def list_threads(
        self,
        *,
        page_token: str | None = None,
        q: str | None = None,
        label_ids: list[str] | None = None,
        max_results: int = 50,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"maxResults": max_results}
        if page_token:
            params["pageToken"] = page_token
        if q:
            params["q"] = q
        if label_ids:
            params["labelIds"] = label_ids
        return await self._request("GET", "/threads", params=params)

    async def get_thread(self, thread_id: str, *, format: str = "metadata") -> dict[str, Any]:
        return await self._request("GET", f"/threads/{thread_id}", params={"format": format})

    # ------------------------------------------------------------------
    # Mutations: label add/remove, trash, untrash, modify thread
    # ------------------------------------------------------------------
    async def modify_message(
        self,
        message_id: str,
        *,
        add_label_ids: list[str] | None = None,
        remove_label_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if add_label_ids:
            body["addLabelIds"] = list(add_label_ids)
        if remove_label_ids:
            body["removeLabelIds"] = list(remove_label_ids)
        return await self._request("POST", f"/messages/{message_id}/modify", json=body)

    async def modify_thread(
        self,
        thread_id: str,
        *,
        add_label_ids: list[str] | None = None,
        remove_label_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if add_label_ids:
            body["addLabelIds"] = list(add_label_ids)
        if remove_label_ids:
            body["removeLabelIds"] = list(remove_label_ids)
        return await self._request("POST", f"/threads/{thread_id}/modify", json=body)

    async def trash_message(self, message_id: str) -> dict[str, Any]:
        return await self._request("POST", f"/messages/{message_id}/trash")

    async def untrash_message(self, message_id: str) -> dict[str, Any]:
        return await self._request("POST", f"/messages/{message_id}/untrash")

    async def trash_thread(self, thread_id: str) -> dict[str, Any]:
        return await self._request("POST", f"/threads/{thread_id}/trash")

    async def untrash_thread(self, thread_id: str) -> dict[str, Any]:
        return await self._request("POST", f"/threads/{thread_id}/untrash")

    async def batch_modify_messages(
        self,
        *,
        ids: list[str],
        add_label_ids: list[str] | None = None,
        remove_label_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """``messages.batchModify`` — up to 1000 ids per request (caller must chunk)."""
        if not ids:
            return {}
        body: dict[str, Any] = {"ids": list(ids)}
        if add_label_ids:
            body["addLabelIds"] = list(add_label_ids)
        if remove_label_ids:
            body["removeLabelIds"] = list(remove_label_ids)
        return await self._request("POST", "/messages/batchModify", json=body)

    # ------------------------------------------------------------------
    # Filters (requires gmail.settings.basic scope)
    # ------------------------------------------------------------------
    async def list_filters(self) -> dict[str, Any]:
        return await self._request("GET", "/settings/filters")

    async def create_filter(self, *, criteria: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
        body = {"criteria": criteria, "action": action}
        return await self._request("POST", "/settings/filters", json=body)

    async def delete_filter(self, filter_id: str) -> dict[str, Any]:
        return await self._request("DELETE", f"/settings/filters/{filter_id}")
