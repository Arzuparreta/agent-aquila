"""Skills and workspace tool handlers."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.services.agent_workspace import list_allowed_workspace_files
from app.services.skills_service import _skills_dir
from app.services.skills_service import list_skills as _list_skills
from app.services.skills_service import load_skill as _load_skill


async def _tool_list_skills(
    db: AsyncSession, user: User, args: dict[str, Any],
) -> dict[str, Any]:
    items = await _list_skills()
    return {"skills": items}


async def _tool_load_skill(
    db: AsyncSession, user: User, args: dict[str, Any],
) -> dict[str, Any]:
    name = str(args.get("name") or "").strip()
    if not name:
        return {"error": "skill name is required"}
    result = await _load_skill(name)
    if result is None:
        return {"error": f"skill '{name}' not found"}
    return result


async def _tool_list_workspace_files(
    db: AsyncSession, user: User, args: dict[str, Any],
) -> dict[str, Any]:
    files = list_allowed_workspace_files()
    return {"files": files}


async def _tool_read_workspace_file(
    db: AsyncSession, user: User, args: dict[str, Any],
) -> dict[str, Any]:
    from app.services.agent_workspace import read_workspace_file
    name = str(args.get("name") or "").strip()
    if not name:
        return {"error": "file name is required"}
    content = await read_workspace_file(name)
    if content is None:
        return {"error": f"file '{name}' not found or not allowed"}
    return {"name": name, "content": content}
