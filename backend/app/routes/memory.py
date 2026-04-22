"""Read/write API for the agent's persistent memory.

Mostly used by the Settings → Memory viewer (so the user can see what
the agent has learned and prune it). The agent itself manipulates
memory through ``upsert_memory`` / ``recall_memory`` / ``delete_memory``
tools, not via these HTTP endpoints — we expose them anyway so the UI
can render and curate the table without going through chat.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.agent_memory import AgentMemory
from app.models.user import User
from app.services.agent_memory_service import AgentMemoryService
from app.services.canonical_memory import build_markdown_memory_prompt_section, reset_user_memory_workspace

router = APIRouter(prefix="/memory", tags=["memory"], dependencies=[Depends(get_current_user)])


class MemoryRead(BaseModel):
    id: int
    key: str
    content: str
    importance: int
    tags: list[str] | None = None
    updated_at: str | None = None


class MemoryWrite(BaseModel):
    key: str = Field(..., min_length=1, max_length=200)
    content: str = Field(..., min_length=1)
    importance: int = 0
    tags: list[str] | None = None
    meta: dict[str, Any] | None = None


@router.get("", response_model=list[MemoryRead])
async def list_memory(
    limit: int = Query(default=200, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[MemoryRead]:
    rows = await AgentMemoryService.list_for_user(db, current_user, limit=limit)
    return [
        MemoryRead(
            id=r.id,
            key=r.key,
            content=r.content,
            importance=r.importance or 0,
            tags=r.tags,
            updated_at=r.updated_at.isoformat() if r.updated_at else None,
        )
        for r in rows
    ]


@router.post("", response_model=MemoryRead)
async def upsert_memory(
    payload: MemoryWrite,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MemoryRead:
    row = await AgentMemoryService.upsert(
        db,
        current_user,
        key=payload.key,
        content=payload.content,
        importance=payload.importance,
        tags=payload.tags,
        meta=payload.meta,
    )
    return MemoryRead(
        id=row.id,
        key=row.key,
        content=row.content,
        importance=row.importance or 0,
        tags=row.tags,
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
    )


@router.delete("/{key}")
async def delete_memory(
    key: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, bool]:
    ok = await AgentMemoryService.delete(db, current_user, key=key)
    if not ok:
        raise HTTPException(status_code=404, detail="Memory key not found")
    return {"ok": True}


@router.post("/recall")
async def recall_memory(
    payload: dict[str, Any] = Body(default_factory=dict),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    query = (payload.get("query") or "").strip() or None
    tags = payload.get("tags") or None
    limit = int(payload.get("limit") or 6)
    hits = await AgentMemoryService.recall(
        db, current_user, query=query, tags=tags, limit=limit
    )
    return {"hits": hits}


@router.get("/digest")
async def get_memory_digest(
    current_user: User = Depends(get_current_user),
) -> dict[str, str | None]:
    """Return the prompt-oriented canonical block (incl. DREAMS tail) for transparency digests."""
    return {"canonical_excerpt": build_markdown_memory_prompt_section(current_user) or None}


@router.post("/reset")
async def reset_all_memory(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Hard reset: TRUNCATE DB index and delete per-user markdown workspace. Irreversible."""
    await db.execute(delete(AgentMemory).where(AgentMemory.user_id == current_user.id))
    await db.commit()
    rep = reset_user_memory_workspace(current_user)
    return {
        "ok": True,
        "deleted_index_rows": True,
        "report": {
            "deleted_files": rep.deleted_files,
            "hint": rep.deleted_db_hint,
        },
    }
