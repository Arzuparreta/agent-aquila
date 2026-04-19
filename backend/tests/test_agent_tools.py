"""Smoke tests for the OpenClaw agent tool catalogue.

The full per-tool fixtures from the CRM era were dropped along with the
legacy services; this file now covers the few high-value invariants that
keep the catalogue honest.
"""
from __future__ import annotations

import pytest

from app.services.agent_service import AgentService
from app.services.agent_tools import (
    _AUTO_APPLY_TOOLS,
    _PROPOSAL_TOOLS,
    AGENT_TOOLS,
)


@pytest.mark.asyncio
async def test_proposal_tool_set_is_email_only() -> None:
    """Only outbound email is gated; everything else auto-applies."""
    assert _PROPOSAL_TOOLS == {"propose_email_send", "propose_email_reply"}


def test_every_tool_in_one_bucket() -> None:
    """Every tool definition is either auto-apply or proposal — never both, never neither."""
    names = {t["function"]["name"] for t in AGENT_TOOLS}
    assert names == _AUTO_APPLY_TOOLS | _PROPOSAL_TOOLS
    assert _AUTO_APPLY_TOOLS.isdisjoint(_PROPOSAL_TOOLS)


def test_dispatch_table_covers_every_tool() -> None:
    """``AgentService._DISPATCH`` must handle every advertised tool."""
    catalog = {t["function"]["name"] for t in AGENT_TOOLS}
    dispatch = set(AgentService._DISPATCH.keys())
    missing = catalog - dispatch
    assert not missing, f"tools missing from dispatch: {sorted(missing)}"
