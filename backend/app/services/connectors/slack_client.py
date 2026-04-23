"""Slack Web API — bot token (xoxb-) for conversations + chat.postMessage."""

from __future__ import annotations

import asyncio
import random
from typing import Any

import httpx

BASE = "https://slack.com/api"


class SlackAPIError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Slack API {status_code}: {detail[:500]}")


class SlackClient:
    def __init__(self, bot_token: str, *, timeout: float = 45.0) -> None:
        self._token = (bot_token or "").strip()
        self._timeout = timeout

    async def _request(self, method: str, path: str, *, json_body: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{BASE}/{path.lstrip('/')}"
        backoff = 1.0
        for attempt in range(5):
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.request(
                    method,
                    url,
                    headers={
                        "Authorization": f"Bearer {self._token}",
                        "Content-Type": "application/json; charset=utf-8",
                    },
                    json=json_body or {},
                )
            if resp.status_code == 429 or resp.status_code >= 500:
                wait = float(resp.headers.get("Retry-After") or 0) or backoff + random.uniform(0, 0.5)
                await asyncio.sleep(min(wait, 30.0))
                backoff = min(backoff * 2, 30.0)
                continue
            try:
                data = resp.json()
            except Exception as exc:  # noqa: BLE001
                raise SlackAPIError(resp.status_code, resp.text[:300]) from exc
            if not data.get("ok"):
                err = str(data.get("error") or resp.text)[:400]
                raise SlackAPIError(resp.status_code, err)
            return data
        raise SlackAPIError(503, "Slack API retries exhausted")

    async def auth_test(self) -> dict[str, Any]:
        return await self._request("POST", "auth.test", json_body={})

    async def conversations_list(
        self,
        *,
        types: str = "public_channel,private_channel",
        cursor: str | None = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "types": types,
            "limit": max(1, min(limit, 1000)),
        }
        if cursor:
            body["cursor"] = cursor
        return await self._request("POST", "conversations.list", json_body=body)

    async def conversations_history(
        self,
        channel: str,
        *,
        limit: int = 50,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "channel": channel.strip(),
            "limit": max(1, min(limit, 200)),
        }
        if cursor:
            body["cursor"] = cursor
        return await self._request("POST", "conversations.history", json_body=body)

    async def chat_post_message(
        self,
        channel: str,
        text: str,
        *,
        thread_ts: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "channel": channel.strip(),
            "text": text,
        }
        if thread_ts:
            body["thread_ts"] = thread_ts
        return await self._request("POST", "chat.postMessage", json_body=body)
