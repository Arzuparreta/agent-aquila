"""Google People API — contact search (read-only)."""

from __future__ import annotations

import asyncio
import random
from typing import Any

import httpx

BASE = "https://people.googleapis.com/v1"


class GooglePeopleAPIError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"People API {status_code}: {detail[:500]}")


class GooglePeopleClient:
    def __init__(self, access_token: str, *, timeout: float = 30.0) -> None:
        self._token = access_token
        self._timeout = timeout

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any | None = None,
    ) -> Any:
        url = path if path.startswith("http") else f"{BASE}{path}"
        backoff = 1.0
        for _ in range(5):
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.request(
                    method,
                    url,
                    params=params,
                    json=json_body,
                    headers={"Authorization": f"Bearer {self._token}"},
                )
            if resp.status_code == 429 or resp.status_code >= 500:
                wait = float(resp.headers.get("Retry-After") or 0) or backoff + random.uniform(0, 0.5)
                await asyncio.sleep(min(wait, 30.0))
                backoff = min(backoff * 2, 30.0)
                continue
            if resp.status_code >= 400:
                raise GooglePeopleAPIError(resp.status_code, resp.text)
            if not resp.content:
                return {}
            return resp.json()
        raise GooglePeopleAPIError(503, "People API retries exhausted")

    async def search_contacts(
        self,
        query: str,
        *,
        page_token: str | None = None,
        page_size: int = 30,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "query": query,
            "readMask": "names,emailAddresses,phoneNumbers,organizations",
            "pageSize": min(max(1, page_size), 30),
        }
        if page_token:
            body["pageToken"] = page_token
        return await self._request("POST", "/people:searchContacts", json_body=body)
