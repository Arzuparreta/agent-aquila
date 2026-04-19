"""Read-only HTTP API for the agent's skills folder.

Powers the Settings → Skills viewer; the agent reads skills via the
``list_skills`` / ``load_skill`` tools (not these endpoints).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.deps import get_current_user
from app.services.skills_service import list_skills as _list_skills
from app.services.skills_service import load_skill as _load_skill

router = APIRouter(prefix="/skills", tags=["skills"], dependencies=[Depends(get_current_user)])


class SkillSummary(BaseModel):
    slug: str
    title: str
    summary: str


class SkillFull(SkillSummary):
    body: str


@router.get("", response_model=list[SkillSummary])
async def list_skills() -> list[SkillSummary]:
    return [SkillSummary(slug=s.slug, title=s.title, summary=s.summary) for s in _list_skills()]


@router.get("/{slug}", response_model=SkillFull)
async def get_skill(slug: str) -> SkillFull:
    skill = _load_skill(slug)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    return SkillFull(slug=skill.slug, title=skill.title, summary=skill.summary, body=skill.body)
