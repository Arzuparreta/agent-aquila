"""Thin Google Drive v3 REST client (metadata + content download). Writes still live in
`file_adapters`."""
from __future__ import annotations

import asyncio
import random
from typing import Any

import httpx

BASE = "https://www.googleapis.com/drive/v3"
FIELDS_FILE = (
    "id,name,mimeType,size,parents,owners,webViewLink,modifiedTime,trashed,iconLink,shortcutDetails"
)
FIELDS_LIST = f"nextPageToken,files({FIELDS_FILE})"
FIELDS_CHANGES = f"nextPageToken,newStartPageToken,changes(fileId,removed,time,file({FIELDS_FILE}))"


class DriveAPIError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Drive API {status_code}: {detail[:500]}")


class GoogleDriveClient:
    def __init__(self, access_token: str, *, timeout: float = 120.0) -> None:
        self._token = access_token
        self._timeout = timeout

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any | None = None,
        expect_bytes: bool = False,
    ) -> Any:
        url = path if path.startswith("http") else f"{BASE}{path}"
        backoff = 1.0
        for _ in range(5):
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.request(
                    method,
                    url,
                    params=params,
                    json=json,
                    headers={"Authorization": f"Bearer {self._token}"},
                )
            if resp.status_code == 429 or resp.status_code >= 500:
                wait = float(resp.headers.get("Retry-After") or 0) or backoff + random.uniform(0, 0.5)
                await asyncio.sleep(min(wait, 30.0))
                backoff = min(backoff * 2, 30.0)
                continue
            if resp.status_code >= 400:
                raise DriveAPIError(resp.status_code, resp.text)
            if expect_bytes:
                return resp.content
            if not resp.content:
                return {}
            return resp.json()
        raise DriveAPIError(503, "Drive API retries exhausted")

    async def list_files(
        self, *, page_token: str | None = None, q: str | None = None, page_size: int = 200
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"pageSize": page_size, "fields": FIELDS_LIST}
        if page_token:
            params["pageToken"] = page_token
        if q:
            params["q"] = q
        return await self._request("GET", "/files", params=params)

    async def get_start_page_token(self) -> dict[str, Any]:
        return await self._request("GET", "/changes/startPageToken")

    async def list_changes(self, *, page_token: str, page_size: int = 200) -> dict[str, Any]:
        params = {
            "pageToken": page_token,
            "pageSize": page_size,
            "fields": FIELDS_CHANGES,
            "includeRemoved": "true",
        }
        return await self._request("GET", "/changes", params=params)

    async def export(self, file_id: str, mime_type: str) -> bytes:
        return await self._request(
            "GET",
            f"/files/{file_id}/export",
            params={"mimeType": mime_type},
            expect_bytes=True,
        )

    async def download(self, file_id: str) -> bytes:
        return await self._request(
            "GET", f"/files/{file_id}", params={"alt": "media"}, expect_bytes=True
        )
