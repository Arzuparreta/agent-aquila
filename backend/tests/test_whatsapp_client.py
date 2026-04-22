"""WhatsAppClient — mocked HTTP (no real Meta token)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.connectors import whatsapp_client as wa_mod
from app.services.connectors.whatsapp_client import WhatsAppClient


@pytest.mark.asyncio
async def test_verify_phone_number_parses_json() -> None:
    sample = {"id": "123", "display_phone_number": "+1 555 0100", "verified_name": "Acme"}

    async def on_get(url, *, params=None, headers=None):
        assert "graph.facebook.com" in str(url)
        assert params and params.get("fields")
        return httpx.Response(200, json=sample)

    mock_inner = MagicMock()
    mock_inner.get = AsyncMock(side_effect=on_get)

    class _ACM:
        async def __aenter__(self):
            return mock_inner

        async def __aexit__(self, *args):
            return None

    with patch.object(wa_mod.httpx, "AsyncClient", return_value=_ACM()):
        c = WhatsAppClient("tok", "phone-id-1", api_version="v21.0")
        out = await c.verify_phone_number()
    assert out == sample
