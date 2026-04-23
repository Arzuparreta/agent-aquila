from __future__ import annotations

import pytest

from app.services.connectors.web_search_client import WebSearchAPIError, WebSearchClient, _strip_html


def test_strip_html_removes_tags_and_scripts() -> None:
    raw = "<html><head><title>x</title><script>alert(1)</script></head><body><h1>Hello</h1><p>world</p></body></html>"
    out = _strip_html(raw)
    assert "Hello world" in out
    assert "alert(1)" not in out


@pytest.mark.asyncio
async def test_search_uses_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    client = WebSearchClient()
    calls = {"n": 0}

    async def fake_search(_query: str, *, limit: int) -> dict:
        calls["n"] += 1
        return {"provider": "duckduckgo", "query": "cache test", "results": [{"title": "a", "url": "https://example.com"}]}

    monkeypatch.setattr(client, "_search_duckduckgo", fake_search)
    a = await client.search("cache test unique abc", max_results=3)
    b = await client.search("cache test unique abc", max_results=3)
    assert calls["n"] == 1
    assert a["cache_hit"] is False
    assert b["cache_hit"] is True


@pytest.mark.asyncio
async def test_fetch_blocks_private_hosts() -> None:
    client = WebSearchClient()
    with pytest.raises(WebSearchAPIError):
        await client.fetch_url("http://localhost:8000")

