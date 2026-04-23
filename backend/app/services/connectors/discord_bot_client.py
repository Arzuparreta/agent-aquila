"""Discord Bot API (REST v10)."""

from __future__ import annotations

import asyncio
import random
from typing import Any

import httpx

BASE = "https://discord.com/api/v10"


class DiscordAPIError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Discord API {status_code}: {detail[:500]}")


class DiscordBotClient:
    def __init__(self, bot_token: str, *, timeout: float = 45.0) -> None:
        self._token = (bot_token or "").strip()
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bot {self._token}"}

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        url = path if path.startswith("http") else f"{BASE}{path}"
        backoff = 1.0
        for _ in range(4):
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.request(
                    method,
                    url,
                    headers=self._headers(),
                    json=json_body,
                    params=params,
                )
            if resp.status_code == 429 or resp.status_code >= 500:
                wait = float(resp.headers.get("Retry-After") or 0) or backoff + random.uniform(0, 0.5)
                await asyncio.sleep(min(wait, 20.0))
                backoff = min(backoff * 2, 20.0)
                continue
            if resp.status_code >= 400:
                raise DiscordAPIError(resp.status_code, resp.text)
            if resp.status_code == 204 or not resp.content:
                return {}
            return resp.json()
        raise DiscordAPIError(503, "Discord retries exhausted")

    async def get_me(self) -> dict[str, Any]:
        return await self._request("GET", "/users/@me")

    async def list_guilds(self) -> list[Any]:
        return await self._request("GET", "/users/@me/guilds")

    async def list_guild_channels(self, guild_id: str) -> list[Any]:
        gid = (guild_id or "").strip()
        if not gid:
            raise DiscordAPIError(400, "guild_id is required")
        return await self._request("GET", f"/guilds/{gid}/channels")

    async def list_messages(self, channel_id: str, *, limit: int = 25) -> list[Any]:
        cid = (channel_id or "").strip()
        if not cid:
            raise DiscordAPIError(400, "channel_id is required")
        lim = max(1, min(limit, 100))
        return await self._request("GET", f"/channels/{cid}/messages", params={"limit": lim})

    async def create_message(self, channel_id: str, content: str) -> dict[str, Any]:
        cid = (channel_id or "").strip()
        if not cid:
            raise DiscordAPIError(400, "channel_id is required")
        return await self._request(
            "POST",
            f"/channels/{cid}/messages",
            json_body={"content": content[:2000]},
        )
