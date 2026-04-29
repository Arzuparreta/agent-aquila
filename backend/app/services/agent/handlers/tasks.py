"""Google Tasks tool handlers."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.services.connectors.google_tasks_client import GoogleTasksClient

from .base import provider_connection


@provider_connection("tasks")
async def _tool_tasks_list_tasklists(
    db: AsyncSession, user: User, client: GoogleTasksClient, args: dict[str, Any],
) -> dict[str, Any]:
    return await client.list_tasklists(page_token=args.get("page_token"))


@provider_connection("tasks")
async def _tool_tasks_list_tasks(
    db: AsyncSession, user: User, client: GoogleTasksClient, args: dict[str, Any],
) -> dict[str, Any]:
    sc = args.get("show_completed")
    return await client.list_tasks(
        str(args["tasklist_id"]),
        page_token=args.get("page_token"),
        show_completed=bool(sc) if sc is not None else None,
        due_min=args.get("due_min"),
        due_max=args.get("due_max"),
        max_results=int(args.get("max_results") or 100),
    )


@provider_connection("tasks")
async def _tool_tasks_create_task(
    db: AsyncSession, user: User, client: GoogleTasksClient, args: dict[str, Any],
) -> dict[str, Any]:
    body: dict[str, Any] = {"title": str(args["title"])}
    if args.get("notes") is not None:
        body["notes"] = str(args["notes"])
    if args.get("due"):
        body["due"] = str(args["due"])
    return await client.insert_task(str(args["tasklist_id"]), body)


@provider_connection("tasks")
async def _tool_tasks_update_task(
    db: AsyncSession, user: User, client: GoogleTasksClient, args: dict[str, Any],
) -> dict[str, Any]:
    body: dict[str, Any] = {}
    if args.get("title") is not None:
        body["title"] = str(args["title"])
    if args.get("notes") is not None:
        body["notes"] = str(args["notes"])
    if args.get("status"):
        body["status"] = str(args["status"])
    if args.get("due"):
        body["due"] = str(args["due"])
    return await client.patch_task(str(args["tasklist_id"]), str(args["task_id"]), body)


@provider_connection("tasks")
async def _tool_tasks_delete_task(
    db: AsyncSession, user: User, client: GoogleTasksClient, args: dict[str, Any],
) -> dict[str, Any]:
    return await client.delete_task(str(args["tasklist_id"]), str(args["task_id"]))
