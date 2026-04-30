"""Run attention helpers."""
from typing import Any
from app.models.agent_run import AgentRun
from app.schemas.agent import AgentRunAttentionRead

async def build_attention_snapshot(db, run: AgentRun):
    """Build attention snapshot for a run."""
    from app.services.agent_run_attention import build_attention_snapshot as _inner
    return await _inner(db, run)
