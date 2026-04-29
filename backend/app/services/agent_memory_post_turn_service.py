"""Backward-compatible shim — post-turn memory logic lives in app.services.agent.memory.post_turn."""

from app.services.agent.memory.post_turn import (
    PostTurnMemoryResult,
    heuristic_wants_post_turn_extraction,
    maybe_ingest_post_turn_memory,
)

__all__ = [
    "PostTurnMemoryResult",
    "heuristic_wants_post_turn_extraction",
    "maybe_ingest_post_turn_memory",
]
