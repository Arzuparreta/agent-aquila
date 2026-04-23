"""Lightweight public web search + fetch client with in-process TTL caching."""

from __future__ import annotations

import html
import ipaddress
import re
import socket
import time
from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.config import settings

_CACHE: dict[tuple[Any, ...], tuple[float, dict[str, Any]]] = {}
_CACHE_MAX_ENTRIES = 2_000


class WebSearchAPIError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Web search error {status_code}: {detail[:300]}")


def _cache_get(key: tuple[Any, ...]) -> dict[str, Any] | None:
    entry = _CACHE.get(key)
    if not entry:
        return None
    expires_at, payload = entry
    if expires_at < time.monotonic():
        _CACHE.pop(key, None)
        return None
    return payload


def _cache_put(key: tuple[Any, ...], payload: dict[str, Any], *, ttl_seconds: int) -> None:
    if len(_CACHE) >= _CACHE_MAX_ENTRIES:
        ordered = sorted(_CACHE.items(), key=lambda kv: kv[1][0], reverse=True)
        keep = dict(ordered[: int(_CACHE_MAX_ENTRIES * 0.9)])
        _CACHE.clear()
        _CACHE.update(keep)
    _CACHE[key] = (time.monotonic() + max(1, ttl_seconds), payload)


def _strip_html(raw: str) -> str:
    no_script = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", no_script)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _is_private_host(host: str) -> bool:
    lh = host.lower().strip("[]")
    if not lh:
        return True
    if lh in {"localhost", "localhost.localdomain"}:
        return True
    try:
        ip = ipaddress.ip_address(lh)
        return (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        )
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(lh, None)
    except socket.gaierror:
        return False
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return True
    return False


class WebSearchClient:
    def __init__(self, *, timeout: float = 20.0) -> None:
        self._timeout = timeout

    async def search(
        self,
        query: str,
        *,
        max_results: int = 8,
    ) -> dict[str, Any]:
        q = (query or "").strip()
        if not q:
            raise WebSearchAPIError(400, "query is required")
        limit = min(max(int(max_results), 1), 20)
        provider = (settings.web_search_provider or "duckduckgo").strip().lower()
        ttl = int(settings.web_search_cache_ttl_seconds or 900)
        key = ("web_search", provider, q.lower(), limit)
        cached = _cache_get(key)
        if cached is not None:
            return {**cached, "cache_hit": True}
        if provider == "serper" and (settings.web_search_api_key or "").strip():
            payload = await self._search_serper(q, limit=limit)
        else:
            payload = await self._search_duckduckgo(q, limit=limit)
        _cache_put(key, payload, ttl_seconds=ttl)
        return {**payload, "cache_hit": False}

    async def fetch_url(self, url: str, *, max_chars: int | None = None) -> dict[str, Any]:
        raw = (url or "").strip()
        if not raw:
            raise WebSearchAPIError(400, "url is required")
        parsed = urlparse(raw)
        if parsed.scheme not in ("http", "https"):
            raise WebSearchAPIError(400, "only http/https URLs are allowed")
        host = parsed.hostname or ""
        if _is_private_host(host):
            raise WebSearchAPIError(400, "private or local network URLs are blocked")
        limit = int(max_chars or settings.web_fetch_max_chars or 12000)
        limit = min(max(limit, 500), 100_000)
        ttl = int(settings.web_search_cache_ttl_seconds or 900)
        key = ("web_fetch", raw, limit)
        cached = _cache_get(key)
        if cached is not None:
            return {**cached, "cache_hit": True}
        timeout = float(settings.web_fetch_timeout_seconds or self._timeout)
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "agent-aquila/0.0.2 (+public-web-tools)"},
        ) as client:
            resp = await client.get(raw)
        if resp.status_code >= 400:
            raise WebSearchAPIError(resp.status_code, f"fetch failed: {resp.text[:200]}")
        ctype = (resp.headers.get("content-type") or "").lower()
        body = resp.text if isinstance(resp.text, str) else str(resp.text)
        if "text/html" in ctype:
            content = _strip_html(body)
        elif (
            "text/plain" in ctype
            or "application/json" in ctype
            or "application/xml" in ctype
            or "text/xml" in ctype
            or ctype == ""
        ):
            content = body.strip()
        else:
            raise WebSearchAPIError(415, f"unsupported content-type: {ctype or 'unknown'}")
        if len(content) > limit:
            content = content[:limit].rstrip() + "\n...[truncated]"
        payload = {
            "url": str(resp.url),
            "status_code": resp.status_code,
            "content_type": ctype or None,
            "title": _extract_title(body) if "text/html" in ctype else None,
            "content": content,
        }
        _cache_put(key, payload, ttl_seconds=ttl)
        return {**payload, "cache_hit": False}

    async def _search_duckduckgo(self, query: str, *, limit: int) -> dict[str, Any]:
        params = {
            "q": query,
            "format": "json",
            "no_redirect": "1",
            "no_html": "1",
            "skip_disambig": "1",
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get("https://api.duckduckgo.com/", params=params)
        if resp.status_code >= 400:
            raise WebSearchAPIError(resp.status_code, f"DuckDuckGo error: {resp.text[:200]}")
        data = resp.json() if resp.content else {}
        out: list[dict[str, Any]] = []
        abstract = (data.get("AbstractText") or "").strip() if isinstance(data, dict) else ""
        abstract_url = (data.get("AbstractURL") or "").strip() if isinstance(data, dict) else ""
        heading = (data.get("Heading") or "").strip() if isinstance(data, dict) else ""
        if abstract and abstract_url:
            out.append(
                {
                    "title": heading or abstract_url,
                    "url": abstract_url,
                    "snippet": abstract[:500],
                    "source": "duckduckgo",
                }
            )
        related = data.get("RelatedTopics") if isinstance(data, dict) else []
        for item in _flatten_related_topics(related):
            if len(out) >= limit:
                break
            text = str(item.get("Text") or "").strip()
            url = str(item.get("FirstURL") or "").strip()
            if not text or not url:
                continue
            title = text.split(" - ", 1)[0].strip() or url
            out.append(
                {
                    "title": title[:180],
                    "url": url,
                    "snippet": text[:500],
                    "source": "duckduckgo",
                }
            )
        return {"provider": "duckduckgo", "query": query, "results": out[:limit]}

    async def _search_serper(self, query: str, *, limit: int) -> dict[str, Any]:
        key = (settings.web_search_api_key or "").strip()
        payload = {"q": query, "num": min(max(limit, 1), 20)}
        headers = {
            "X-API-KEY": key,
            "Content-Type": "application/json",
            "User-Agent": "agent-aquila/0.0.2 (+web-search)",
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post("https://google.serper.dev/search", headers=headers, json=payload)
        if resp.status_code >= 400:
            raise WebSearchAPIError(resp.status_code, f"Serper error: {resp.text[:200]}")
        data = resp.json() if resp.content else {}
        organic = data.get("organic") if isinstance(data, dict) else None
        items = organic if isinstance(organic, list) else []
        results: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            link = str(item.get("link") or "").strip()
            if not link:
                continue
            results.append(
                {
                    "title": str(item.get("title") or link)[:180],
                    "url": link,
                    "snippet": str(item.get("snippet") or "")[:500],
                    "source": "serper",
                }
            )
            if len(results) >= limit:
                break
        return {"provider": "serper", "query": query, "results": results}


def _flatten_related_topics(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if "FirstURL" in item and "Text" in item:
            out.append(item)
            continue
        nested = item.get("Topics")
        if isinstance(nested, list):
            out.extend(_flatten_related_topics(nested))
    return out


def _extract_title(raw_html: str) -> str | None:
    m = re.search(r"<title[^>]*>(.*?)</title>", raw_html or "", flags=re.I | re.S)
    if not m:
        return None
    title = html.unescape(re.sub(r"\s+", " ", m.group(1))).strip()
    return title[:300] if title else None


def debug_cache_snapshot() -> dict[str, Any]:
    """Test helper: exposes a stable, serializable cache summary."""
    now = time.monotonic()
    alive = 0
    for exp, _payload in _CACHE.values():
        if exp >= now:
            alive += 1
    return {"entries_total": len(_CACHE), "entries_alive": alive}

