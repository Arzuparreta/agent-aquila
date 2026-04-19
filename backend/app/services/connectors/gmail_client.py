"""Thin Gmail REST client with retry + backoff.

After the OpenClaw-style refactor this file is the *only* place that
talks to Gmail — both reads (list/get message, list labels) and writes
(modify labels, trash, untrash, filters). Sending email goes through
``email_adapters.send_email`` which builds the MIME envelope.

Docs: https://developers.google.com/gmail/api/reference/rest
"""
from __future__ import annotations

import asyncio
import random
from typing import Any

import httpx

BASE = "https://gmail.googleapis.com/gmail/v1/users/me"


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
    - 429: surface **immediately** as :class:`GmailRateLimited` carrying the
      ``Retry-After`` Gmail gave us, so the route can return a clean 429 to
      the frontend and the UI can render a countdown. Sitting on the socket
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
                retry_after = self._parse_retry_after(resp.headers.get("Retry-After"))
                # Gmail's body sometimes carries a wall-clock retry hint; we
                # don't try to parse it because Retry-After (when present) is
                # canonical, and otherwise we just suggest a short pause.
                raise GmailRateLimited(resp.text, retry_after or 30.0)
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
