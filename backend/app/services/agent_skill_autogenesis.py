"""Skill autogenesis policy: if a run completes successfully without ``load_skill``, record a candidate.

The agent should prefer ``list_skills`` / ``load_skill`` before long workflows. When it solves a
multi-step task **without** loading an existing recipe, we append a structured note (digest-only in V1)
under the user's memory workspace for future promotion into ``backend/skills/``.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_run import AgentRun, AgentRunStep
from app.services.canonical_memory import ensure_user_memory_layout, memory_workspace_dir

logger = logging.getLogger(__name__)

_MAX_STEPS_FOR_AUTOGEN = 2  # at least 3 tool steps (heuristic: multi-step)
_LINE_FILE = "skill_autogenesis_candidates.jsonl"


def _candidates_path(user_id: int) -> Path:
    ensure_user_memory_layout(user_id)
    d = memory_workspace_dir(user_id) / "autogenesis"
    d.mkdir(parents=True, exist_ok=True)
    return d / _LINE_FILE


def _run_used_load_skill(steps: list[AgentRunStep]) -> bool:
    for s in steps:
        if s.kind == "tool" and (s.name or "") == "load_skill":
            return True
    return False


def _count_tool_steps(steps: list[AgentRunStep]) -> int:
    return sum(1 for s in steps if s.kind == "tool" and (s.name or "") != "final_answer")


async def maybe_record_skill_autogenesis_candidate(
    db: AsyncSession,
    run: AgentRun,
) -> bool:
    """If policy matches, append one JSON line. Returns whether a line was written."""
    if (run.status or "") != "completed" or not run.assistant_reply:
        return False
    steps = list(
        (
            await db.execute(
                select(AgentRunStep)
                .where(AgentRunStep.run_id == run.id)
                .order_by(AgentRunStep.step_index)
            )
        )
        .scalars()
        .all()
    )
    if _run_used_load_skill(steps):
        return False
    if _count_tool_steps(steps) < _MAX_STEPS_FOR_AUTOGEN + 1:
        return False
    rec: dict[str, Any] = {
        "ts": datetime.now(UTC).isoformat(),
        "run_id": run.id,
        "user_id": run.user_id,
        "user_message": (run.user_message or "")[:2000],
        "assistant_excerpt": (run.assistant_reply or "")[:2000],
        "step_count": len(steps),
        "note": "Candidate for skill extraction — not generated automatically in V1.",
    }
    path = _candidates_path(int(run.user_id))
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        logger.exception("skill_autogenesis: append failed run_id=%s", run.id)
        return False
    return True
