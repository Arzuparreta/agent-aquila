"""Trace schema, compact tool palette, replay context, and channel bindings."""

from __future__ import annotations

import pytest

from app.services.agent_replay import AgentReplayContext
from app.services.agent_tools import AGENT_TOOLS, tools_for_palette_mode
from app.services.channel_binding import get_or_create_thread_for_channel


def test_compact_palette_is_strict_subset() -> None:
    full = tools_for_palette_mode("full")
    compact = tools_for_palette_mode("compact")
    assert len(compact) < len(full)
    full_names = {t["function"]["name"] for t in full}
    compact_names = {t["function"]["name"] for t in compact}
    assert compact_names < full_names
    assert "final_answer" in compact_names


def test_replay_context_consumes_in_order() -> None:
    ctx = AgentReplayContext(tool_results=[{"x": 1}, {"x": 2}])
    assert ctx.next_tool_result() == {"x": 1}
    assert ctx.next_tool_result() == {"x": 2}
    with pytest.raises(RuntimeError, match="exhausted"):
        ctx.next_tool_result()


@pytest.mark.asyncio
async def test_channel_binding_idempotent(db_session, crm_user) -> None:
    t1 = await get_or_create_thread_for_channel(
        db_session, crm_user, channel="gateway_stub", external_key="same-key"
    )
    t2 = await get_or_create_thread_for_channel(
        db_session, crm_user, channel="gateway_stub", external_key="same-key"
    )
    assert t1.id == t2.id


def test_agent_tools_count_unchanged_bucket() -> None:
    """Regression: full palette still aggregates to AGENT_TOOLS export."""
    assert len(tools_for_palette_mode("full")) == len(AGENT_TOOLS)
