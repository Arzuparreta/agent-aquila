"""Google Docs API v1 — fetch document JSON (httpx)."""
from __future__ import annotations

import asyncio
import random
from typing import Any

import httpx

BASE = "https://docs.googleapis.com/v1/documents"


class GoogleDocsAPIError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Docs API {status_code}: {detail[:500]}")


def _structured_text_from_document(doc: dict[str, Any]) -> str:
    """Flatten paragraph text for agent consumption (no full layout fidelity)."""
    body = doc.get("body") or {}
    content = body.get("content") or []
    lines: list[str] = []

    def para_text(elem: dict[str, Any]) -> str:
        p = elem.get("paragraph") or {}
        parts: list[str] = []
        for el in p.get("elements") or []:
            tr = (el.get("textRun") or {}).get("content") or ""
            if tr:
                parts.append(str(tr))
        return "".join(parts).rstrip("\n")

    for elem in content:
        if "paragraph" in elem:
            t = para_text(elem)
            if t.strip():
                lines.append(t)
        elif "table" in elem:
            lines.append("[table]")
    return "\n".join(lines)


class GoogleDocsClient:
    def __init__(self, access_token: str, *, timeout: float = 60.0) -> None:
        self._token = access_token
        self._timeout = timeout

    async def _request(self, method: str, path: str, *, params: dict[str, Any] | None = None) -> Any:
        url = path if path.startswith("http") else f"{BASE}{path}"
        backoff = 1.0
        for _ in range(5):
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.request(
                    method,
                    url,
                    params=params,
                    headers={"Authorization": f"Bearer {self._token}"},
                )
            if resp.status_code == 429 or resp.status_code >= 500:
                wait = float(resp.headers.get("Retry-After") or 0) or backoff + random.uniform(0, 0.5)
                await asyncio.sleep(min(wait, 30.0))
                backoff = min(backoff * 2, 30.0)
                continue
            if resp.status_code >= 400:
                raise GoogleDocsAPIError(resp.status_code, resp.text)
            if not resp.content:
                return {}
            return resp.json()
        raise GoogleDocsAPIError(503, "Docs API retries exhausted")

    async def get_document(self, document_id: str, *, include_raw: bool = False) -> dict[str, Any]:
        did = document_id.strip()
        if not did:
            raise GoogleDocsAPIError(400, "document_id is required")
        raw = await self._request("GET", f"/{did}")
        structured = _structured_text_from_document(raw) if isinstance(raw, dict) else ""
        out: dict[str, Any] = {
            "document_id": did,
            "title": (raw.get("title") if isinstance(raw, dict) else None),
            "structured_text": structured,
        }
        if include_raw:
            out["raw"] = raw
        return out
