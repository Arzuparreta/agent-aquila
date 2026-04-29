"""Third-party tool handlers — GitHub, Linear, Notion."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.services.connectors.github_client import GitHubClient
from app.services.connectors.linear_client import LinearClient
from app.services.connectors.notion_client import NotionClient

from .base import provider_connection


# ---------------------------------------------------------------------------
# GitHub
# ---------------------------------------------------------------------------

@provider_connection("github")
async def _tool_github_list_my_repos(
    db: AsyncSession, user: User, client: GitHubClient, args: dict[str, Any],
) -> dict[str, Any]:
    items = await client.list_user_repos(
        page=int(args.get("page") or 1),
        per_page=int(args.get("per_page") or 30),
    )
    return {"repos": items}


@provider_connection("github")
async def _tool_github_list_repo_issues(
    db: AsyncSession, user: User, client: GitHubClient, args: dict[str, Any],
) -> dict[str, Any]:
    st = str(args.get("state") or "open")
    if st not in ("open", "closed", "all"):
        st = "open"
    items = await client.list_repo_issues(
        str(args["owner"]),
        str(args["repo"]),
        state=st,
        page=int(args.get("page") or 1),
        per_page=int(args.get("per_page") or 30),
    )
    return {"issues": items}


# ---------------------------------------------------------------------------
# Linear
# ---------------------------------------------------------------------------

@provider_connection("linear")
async def _tool_linear_list_issues(
    db: AsyncSession, user: User, client: LinearClient, args: dict[str, Any],
) -> dict[str, Any]:
    return await client.list_issues(first=int(args.get("first") or 25))


@provider_connection("linear")
async def _tool_linear_get_issue(
    db: AsyncSession, user: User, client: LinearClient, args: dict[str, Any],
) -> dict[str, Any]:
    return await client.get_issue(str(args["issue_id"]))


# ---------------------------------------------------------------------------
# Notion
# ---------------------------------------------------------------------------

@provider_connection("notion")
async def _tool_notion_search(
    db: AsyncSession, user: User, client: NotionClient, args: dict[str, Any],
) -> dict[str, Any]:
    return await client.search(
        query=str(args.get("query") or ""),
        page_size=int(args.get("page_size") or 20),
    )


@provider_connection("notion")
async def _tool_notion_get_page(
    db: AsyncSession, user: User, client: NotionClient, args: dict[str, Any],
) -> dict[str, Any]:
    return await client.get_page(str(args["page_id"]))
