"""Google Tasks API — thin REST client."""

from __future__ import annotations

import asyncio
import random
from typing import Any

import httpx

BASE = "https://tasks.googleapis.com/tasks/v1"


class GoogleTasksAPIError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Google Tasks API {status_code}: {detail[:500]}")


class GoogleTasksClient:
    def __init__(self, access_token: str, *, timeout: float = 30.0) -> None:
        self._token = access_token
        self._timeout = timeout

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any | None = None,
    ) -> Any:
        url = path if path.startswith("http") else f"{BASE}{path}"
        backoff = 1.0
        for _ in range(5):
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.request(
                    method,
                    url,
                    params=params,
                    json=json_body,
                    headers={"Authorization": f"Bearer {self._token}"},
                )
            if resp.status_code == 429 or resp.status_code >= 500:
                wait = float(resp.headers.get("Retry-After") or 0) or backoff + random.uniform(0, 0.5)
                await asyncio.sleep(min(wait, 30.0))
                backoff = min(backoff * 2, 30.0)
                continue
            if resp.status_code >= 400:
                raise GoogleTasksAPIError(resp.status_code, resp.text)
            if method == "DELETE" or not resp.content:
                return {}
            return resp.json()
        raise GoogleTasksAPIError(503, "Google Tasks API retries exhausted")

    async def list_tasklists(self, *, page_token: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if page_token:
            params["pageToken"] = page_token
        return await self._request("GET", "/users/@me/lists", params=params)

    async def list_tasks(
        self,
        tasklist_id: str,
        *,
        page_token: str | None = None,
        show_completed: bool | None = None,
        due_min: str | None = None,
        due_max: str | None = None,
        max_results: int = 100,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"maxResults": min(max(1, max_results), 100)}
        if page_token:
            params["pageToken"] = page_token
        if show_completed is not None:
            params["showCompleted"] = str(show_completed).lower()
        if due_min:
            params["dueMin"] = due_min
        if due_max:
            params["dueMax"] = due_max
        return await self._request("GET", f"/lists/{tasklist_id}/tasks", params=params)

    async def get_task(self, tasklist_id: str, task_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/lists/{tasklist_id}/tasks/{task_id}")

    async def insert_task(self, tasklist_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", f"/lists/{tasklist_id}/tasks", json_body=body)

    async def patch_task(self, tasklist_id: str, task_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return await self._request("PATCH", f"/lists/{tasklist_id}/tasks/{task_id}", json_body=body)

    async def delete_task(self, tasklist_id: str, task_id: str) -> dict[str, Any]:
        return await self._request("DELETE", f"/lists/{tasklist_id}/tasks/{task_id}")
