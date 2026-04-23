"""Google Sheets API v4 — read range and append rows (httpx)."""
from __future__ import annotations

import asyncio
import random
from typing import Any
from urllib.parse import quote

import httpx

BASE = "https://sheets.googleapis.com/v4/spreadsheets"


class GoogleSheetsAPIError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Sheets API {status_code}: {detail[:500]}")


class GoogleSheetsClient:
    def __init__(self, access_token: str, *, timeout: float = 60.0) -> None:
        self._token = access_token
        self._timeout = timeout

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any | None = None,
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
                raise GoogleSheetsAPIError(resp.status_code, resp.text)
            if not resp.content:
                return {}
            return resp.json()
        raise GoogleSheetsAPIError(503, "Sheets API retries exhausted")

    async def get_values(self, spreadsheet_id: str, range_a1: str) -> dict[str, Any]:
        sid = spreadsheet_id.strip()
        rng = range_a1.strip()
        if not sid or not rng:
            raise GoogleSheetsAPIError(400, "spreadsheet_id and range are required")
        enc = quote(rng, safe="")
        return await self._request("GET", f"/{sid}/values/{enc}")

    async def append_row(
        self,
        spreadsheet_id: str,
        range_a1: str,
        values_row: list[Any],
        *,
        value_input_option: str = "USER_ENTERED",
    ) -> dict[str, Any]:
        sid = spreadsheet_id.strip()
        rng = range_a1.strip()
        if not sid or not rng:
            raise GoogleSheetsAPIError(400, "spreadsheet_id and range are required")
        enc = quote(rng, safe="")
        params = {"valueInputOption": value_input_option}
        body = {"values": [values_row]}
        return await self._request(
            "POST",
            f"/{sid}/values/{enc}:append",
            params=params,
            json=body,
        )
