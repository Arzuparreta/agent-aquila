"""Linear GraphQL API (personal API key)."""

from __future__ import annotations

import asyncio
import random
from typing import Any

import httpx

GRAPHQL_URL = "https://api.linear.app/graphql"


class LinearAPIError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Linear API {status_code}: {detail[:500]}")


class LinearClient:
    def __init__(self, api_key: str, *, timeout: float = 45.0) -> None:
        self._key = (api_key or "").strip()
        self._timeout = timeout

    async def _post(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        backoff = 1.0
        for _ in range(4):
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    GRAPHQL_URL,
                    headers={
                        "Authorization": self._key,
                        "Content-Type": "application/json",
                    },
                    json={"query": query, "variables": variables or {}},
                )
            if resp.status_code == 429 or resp.status_code >= 500:
                wait = float(resp.headers.get("Retry-After") or 0) or backoff + random.uniform(0, 0.5)
                await asyncio.sleep(min(wait, 20.0))
                backoff = min(backoff * 2, 20.0)
                continue
            if resp.status_code >= 400:
                raise LinearAPIError(resp.status_code, resp.text)
            data = resp.json()
            if data.get("errors"):
                err = str(data["errors"][0].get("message") if data["errors"] else data)[:400]
                raise LinearAPIError(400, err)
            return data.get("data") or {}
        raise LinearAPIError(503, "Linear retries exhausted")

    async def list_issues(self, *, first: int = 25) -> dict[str, Any]:
        first = max(1, min(first, 100))
        q = """
        query Issues($first: Int!) {
          issues(first: $first) {
            nodes {
              id
              identifier
              title
              url
              state { name }
              team { name key }
            }
          }
        }
        """
        return await self._post(q, {"first": first})

    async def get_issue(self, issue_id: str) -> dict[str, Any]:
        iid = (issue_id or "").strip()
        if not iid:
            raise LinearAPIError(400, "issue_id is required")
        q = """
        query Issue($id: String!) {
          issue(id: $id) {
            id
            identifier
            title
            description
            url
            state { name }
            team { name key }
            assignee { name email }
          }
        }
        """
        return await self._post(q, {"id": iid})

    async def create_comment(self, issue_id: str, body: str) -> dict[str, Any]:
        iid = (issue_id or "").strip()
        text = (body or "").strip()
        if not iid or not text:
            raise LinearAPIError(400, "issue_id and body are required")
        q = """
        mutation CommentCreate($issueId: String!, $body: String!) {
          commentCreate(input: { issueId: $issueId, body: $body }) {
            success
            comment { id url }
          }
        }
        """
        return await self._post(q, {"issueId": iid, "body": text[:20000]})

    async def create_comment(self, issue_id: str, body: str) -> dict[str, Any]:
        iid = (issue_id or "").strip()
        text = (body or "").strip()
        if not iid or not text:
            raise LinearAPIError(400, "issue_id and body are required")
        q = """
        mutation CommentCreate($issueId: String!, $body: String!) {
          commentCreate(input: { issueId: $issueId, body: $body }) {
            success
            comment { id url }
          }
        }
        """
        return await self._post(q, {"issueId": iid, "body": text[:10000]})
