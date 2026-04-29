"""Replay short-circuits real tool execution."""

from __future__ import annotations

import pytest

from app.services.agent.replay import AgentReplayContext
from app.services.agent import _dispatch_tool, _replay_ctx
from app.services.llm_client import ChatToolCall


@pytest.mark.asyncio
async def test_dispatch_tool_uses_replay_results(db_session, aquila_user, agent_run) -> None:
    replay = AgentReplayContext(tool_results=[{"from_replay": True}])
    token = _replay_ctx.set(replay)
    try:
        res, prop = await _dispatch_tool(
            db_session,
            aquila_user,
            agent_run.id,
            None,
            ChatToolCall(id="c1", name="gmail_list_messages", arguments={}),
        )
        assert res == {"from_replay": True}
        assert prop is None
    finally:
        _replay_ctx.reset(token)
