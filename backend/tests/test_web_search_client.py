from __future__ import annotations

import pytest

from app.services.connectors.web_search_client import (
    WebSearchAPIError,
    WebSearchClient,
    _normalize_ddg_result_url,
    _strip_html,
)


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


@pytest.mark.asyncio
async def test_search_duckduckgo_html_parser(monkeypatch: pytest.MonkeyPatch) -> None:
    client = WebSearchClient()

    class _FakeResp:
        status_code = 200
        text = """
        <html><body>
        <a class="result__a" href="/l/?uddg=https%3A%2F%2Fexample.com%2Fnews">Example News</a>
        </body></html>
        """

    class _FakeClient:
        async def __aenter__(self) -> "_FakeClient":
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def get(self, _url: str, params: dict[str, str]) -> _FakeResp:
            assert params["q"] == "ai"
            return _FakeResp()

    monkeypatch.setattr("app.services.connectors.web_search_client.httpx.AsyncClient", lambda **kwargs: _FakeClient())
    out = await client._search_duckduckgo_html("ai", limit=5)
    assert out[0]["url"] == "https://example.com/news"
    assert out[0]["source"] == "duckduckgo_html"


def test_normalize_ddg_result_url_redirect() -> None:
    url = _normalize_ddg_result_url("/l/?uddg=https%3A%2F%2Fexample.com%2Fnews")
    assert url == "https://example.com/news"
    url_full = _normalize_ddg_result_url(
        "https://duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fdeep-news"
    )
    assert url_full == "https://example.com/deep-news"

