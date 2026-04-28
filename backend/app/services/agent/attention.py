"""Attention/snapshot helpers."""
from typing import Any
from app.models.agent_run import AgentRun
from app.schemas.agent import AgentRunAttentionRead
from app.services.agent.run_attention import build_attention_snapshot as _build_attention_snapshot

def build_attention_snapshot(db, run: AgentRun):
    """Build attention snapshot for a run."""
    return _build_attention_snapshot(db, run)
