"""Telegram Bot API (HTTPS, bot token)."""

from __future__ import annotations

import asyncio
import random
from typing import Any

import httpx


class TelegramAPIError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Telegram API {status_code}: {detail[:500]}")


class TelegramBotClient:
    def __init__(self, bot_token: str, *, timeout: float = 45.0) -> None:
        tok = (bot_token or "").strip()
        self._base = f"https://api.telegram.org/bot{tok}/"
        self._timeout = timeout

    async def _get(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        request_timeout: float | None = None,
    ) -> dict[str, Any]:
        timeout = self._timeout if request_timeout is None else request_timeout
        backoff = 1.0
        for _ in range(4):
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(self._base + method, params=params or {})
            if resp.status_code == 409:
                try:
                    data = resp.json()
                    desc = str(data.get("description") or resp.text)[:400]
                except Exception:  # noqa: BLE001
                    desc = resp.text[:300]
                raise TelegramAPIError(409, desc)
            if resp.status_code == 429 or resp.status_code >= 500:
                wait = float(resp.headers.get("Retry-After") or 0) or backoff + random.uniform(0, 0.5)
                await asyncio.sleep(min(wait, 20.0))
                backoff = min(backoff * 2, 20.0)
                continue
            try:
                data = resp.json()
            except Exception as exc:  # noqa: BLE001
                raise TelegramAPIError(resp.status_code, resp.text[:300]) from exc
            if not data.get("ok"):
                raise TelegramAPIError(400, str(data.get("description") or data)[:400])
            return data
        raise TelegramAPIError(503, "Telegram retries exhausted")

    async def _post(self, method: str, json_body: dict[str, Any]) -> dict[str, Any]:
        backoff = 1.0
        for _ in range(4):
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(self._base + method, json=json_body)
            if resp.status_code == 429 or resp.status_code >= 500:
                wait = float(resp.headers.get("Retry-After") or 0) or backoff + random.uniform(0, 0.5)
                await asyncio.sleep(min(wait, 20.0))
                backoff = min(backoff * 2, 20.0)
                continue
            try:
                data = resp.json()
            except Exception as exc:  # noqa: BLE001
                raise TelegramAPIError(resp.status_code, resp.text[:300]) from exc
            if not data.get("ok"):
                raise TelegramAPIError(400, str(data.get("description") or data)[:400])
            return data
        raise TelegramAPIError(503, "Telegram retries exhausted")

    async def get_me(self) -> dict[str, Any]:
        return await self._get("getMe")

    async def delete_webhook(self, *, drop_pending_updates: bool = False) -> dict[str, Any]:
        return await self._post("deleteWebhook", {"drop_pending_updates": drop_pending_updates})

    async def get_updates(
        self,
        *,
        offset: int | None = None,
        limit: int = 40,
        long_poll_timeout: int | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": max(1, min(limit, 100))}
        if offset is not None:
            params["offset"] = offset
        req_timeout = self._timeout
        if long_poll_timeout is not None:
            lp = max(0, min(int(long_poll_timeout), 50))
            params["timeout"] = lp
            req_timeout = float(lp) + 10.0
        return await self._get("getUpdates", params, request_timeout=req_timeout)

    async def send_message(self, chat_id: int | str, text: str) -> dict[str, Any]:
        return await self._post(
            "sendMessage",
            {"chat_id": chat_id, "text": text[:4096]},
        )
