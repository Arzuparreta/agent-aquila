"""Meta WhatsApp Cloud API — outbound messages."""

from __future__ import annotations

import asyncio
import random
from typing import Any

import httpx

DEFAULT_GRAPH_VERSION = "v21.0"


class WhatsAppAPIError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"WhatsApp API {status_code}: {detail[:500]}")


class WhatsAppClient:
    """Send session messages (24h window) or template messages via Cloud API."""

    def __init__(
        self,
        access_token: str,
        phone_number_id: str,
        *,
        api_version: str = DEFAULT_GRAPH_VERSION,
        timeout: float = 30.0,
    ) -> None:
        self._token = access_token
        self._phone_number_id = phone_number_id
        self._api_version = api_version
        self._timeout = timeout

    def _url(self) -> str:
        return f"https://graph.facebook.com/{self._api_version}/{self._phone_number_id}/messages"

    async def send_text(self, to_e164: str, body: str) -> dict[str, Any]:
        payload = {
            "messaging_product": "whatsapp",
            "to": to_e164.lstrip("+"),
            "type": "text",
            "text": {"preview_url": False, "body": body[:4096]},
        }
        return await self._post(payload)

    async def send_template(
        self,
        to_e164: str,
        *,
        template_name: str,
        language_code: str = "en",
        components: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        tmpl: dict[str, Any] = {
            "name": template_name,
            "language": {"code": language_code},
        }
        if components:
            tmpl["components"] = components
        payload: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "to": to_e164.lstrip("+"),
            "type": "template",
            "template": tmpl,
        }
        return await self._post(payload)

    async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        backoff = 1.0
        for _ in range(4):
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    self._url(),
                    json=payload,
                    headers={"Authorization": f"Bearer {self._token}"},
                )
            if resp.status_code == 429 or resp.status_code >= 500:
                wait = float(resp.headers.get("Retry-After") or 0) or backoff + random.uniform(0, 0.5)
                await asyncio.sleep(min(wait, 30.0))
                backoff = min(backoff * 2, 30.0)
                continue
            if resp.status_code >= 400:
                raise WhatsAppAPIError(resp.status_code, resp.text)
            if not resp.content:
                return {}
            return resp.json()
        raise WhatsAppAPIError(503, "WhatsApp API retries exhausted")
