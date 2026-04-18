"""Thin async client for the Microsoft Graph REST API (v1.0).

Only implements the endpoints needed for mail / calendar / onedrive mirroring. All methods
accept a raw bearer token (fetched via TokenManager.get_valid_access_token) so the client
itself is stateless. Delta pagination is exposed via the generic `follow` helper — a sync
service pages through nextLinks until it receives a deltaLink, which we store as a cursor.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
_MAX_RETRIES = 4


class GraphAPIError(Exception):
    def __init__(self, status_code: int, detail: str, payload: Any = None) -> None:
        self.status_code = status_code
        self.detail = detail
        self.payload = payload
        super().__init__(f"Microsoft Graph API {status_code}: {detail}")


class GraphClient:
    def __init__(self, access_token: str) -> None:
        self._token = access_token

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
            "Prefer": 'outlook.body-content-type="text"',
        }

    async def _get(self, url: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        full_url = url if url.startswith("http") else f"{GRAPH_BASE}{url}"
        backoff = 0.8
        for attempt in range(_MAX_RETRIES):
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    r = await client.get(full_url, headers=self._headers, params=params)
            except httpx.RequestError as exc:
                if attempt == _MAX_RETRIES - 1:
                    raise GraphAPIError(0, f"network: {exc}") from exc
                await asyncio.sleep(backoff)
                backoff *= 2
                continue
            if r.status_code in (429, 503):
                retry_after = float(r.headers.get("Retry-After", backoff))
                await asyncio.sleep(min(retry_after, 15.0))
                backoff *= 2
                continue
            if r.status_code >= 500 and attempt < _MAX_RETRIES - 1:
                await asyncio.sleep(backoff)
                backoff *= 2
                continue
            if r.status_code >= 300:
                raise GraphAPIError(r.status_code, r.text[:500])
            try:
                return r.json()
            except Exception as exc:
                raise GraphAPIError(r.status_code, f"invalid_json: {exc}") from exc
        raise GraphAPIError(0, "retries_exhausted")

    async def me(self) -> dict[str, Any]:
        return await self._get("/me")

    # --------------------- Mail ---------------------
    async def messages_delta(self, *, delta_link: str | None = None, top: int = 50) -> dict[str, Any]:
        if delta_link:
            return await self._get(delta_link)
        return await self._get(
            "/me/messages/delta",
            params={
                "$select": "id,conversationId,subject,from,sender,toRecipients,receivedDateTime,"
                "bodyPreview,body,isRead,internetMessageId,parentFolderId",
                "$top": top,
            },
        )

    async def get_message(self, message_id: str) -> dict[str, Any]:
        return await self._get(f"/me/messages/{message_id}")

    # --------------------- Calendar ---------------------
    async def events_delta(
        self,
        *,
        delta_link: str | None = None,
        start: str | None = None,
        end: str | None = None,
        top: int = 50,
    ) -> dict[str, Any]:
        if delta_link:
            return await self._get(delta_link)
        params: dict[str, Any] = {
            "$select": "id,iCalUId,subject,bodyPreview,start,end,location,attendees,organizer,webLink,isAllDay,showAs",
            "$top": top,
        }
        if start and end:
            params["startDateTime"] = start
            params["endDateTime"] = end
        return await self._get("/me/calendarView/delta", params=params)

    # --------------------- OneDrive ---------------------
    async def drive_delta(self, *, delta_link: str | None = None) -> dict[str, Any]:
        if delta_link:
            return await self._get(delta_link)
        return await self._get("/me/drive/root/delta")

    async def get_drive_item(self, item_id: str) -> dict[str, Any]:
        return await self._get(f"/me/drive/items/{item_id}")
