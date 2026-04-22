"""GitHub REST API (personal access token)."""

from __future__ import annotations

import asyncio
import random
from typing import Any

import httpx

BASE = "https://api.github.com"


class GitHubAPIError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"GitHub API {status_code}: {detail[:500]}")


class GitHubClient:
    def __init__(self, access_token: str, *, base: str = BASE, timeout: float = 45.0) -> None:
        self._token = access_token.strip()
        self._base = base.rstrip("/")
        self._timeout = timeout

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> Any:
        url = path if path.startswith("http") else f"{self._base}{path}"
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        backoff = 1.0
        for _ in range(4):
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.request(method, url, params=params, headers=headers)
            if resp.status_code == 429 or resp.status_code >= 500:
                wait = float(resp.headers.get("Retry-After") or 0) or backoff + random.uniform(0, 0.5)
                await asyncio.sleep(min(wait, 30.0))
                backoff = min(backoff * 2, 30.0)
                continue
            if resp.status_code >= 400:
                raise GitHubAPIError(resp.status_code, resp.text)
            if not resp.content:
                return [] if method == "GET" else {}
            if resp.headers.get("content-type", "").startswith("application/json"):
                return resp.json()
            return resp.text
        raise GitHubAPIError(503, "GitHub API retries exhausted")

    async def list_user_repos(
        self,
        *,
        page: int = 1,
        per_page: int = 30,
        sort: str = "updated",
    ) -> list[dict[str, Any]]:
        data = await self._request(
            "GET",
            "/user/repos",
            params={"page": max(1, page), "per_page": min(max(1, per_page), 100), "sort": sort},
        )
        return data if isinstance(data, list) else []

    async def list_repo_issues(
        self,
        owner: str,
        repo: str,
        *,
        state: str = "open",
        page: int = 1,
        per_page: int = 30,
    ) -> list[dict[str, Any]]:
        data = await self._request(
            "GET",
            f"/repos/{owner}/{repo}/issues",
            params={"state": state, "page": max(1, page), "per_page": min(max(1, per_page), 100)},
        )
        if not isinstance(data, list):
            return []
        # Pull requests also appear; caller can filter
        return data
