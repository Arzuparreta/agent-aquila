"""Smoke tests for the OpenClaw agent tool catalogue.

The full per-tool fixtures from the CRM era were dropped along with the
legacy services; this file now covers the few high-value invariants that
keep the catalogue honest.
"""
from __future__ import annotations

import pytest

from app.services.agent import AgentService
from app.services.agent_tools import (
    _AUTO_APPLY_TOOLS,
    _PROPOSAL_TOOLS,
    _READ_ONLY_TOOLS,
    _TERMINATOR_TOOLS,
    AGENT_TOOLS,
)


def _names(tools: list[dict]) -> set[str]:
    return {t["function"]["name"] for t in tools}


def test_proposal_tool_set_covers_outbound_kinds() -> None:
    """Human approval for outbound email, WhatsApp, Slack, Linear, and Telegram."""
    assert _names(_PROPOSAL_TOOLS) == {
        "propose_email_send",
        "propose_email_reply",
        "propose_whatsapp_send",
        "propose_slack_post_message",
        "propose_linear_create_comment",
        "propose_telegram_send_message",
    }


def test_every_tool_in_one_bucket() -> None:
    """Every tool definition lives in exactly one bucket — read-only,
    auto-apply, proposal, or terminator.
    The buckets must be disjoint and together cover the full ``AGENT_TOOLS`` palette."""
    read = _names(_READ_ONLY_TOOLS)
    auto = _names(_AUTO_APPLY_TOOLS)
    proposals = _names(_PROPOSAL_TOOLS)
    terminators = _names(_TERMINATOR_TOOLS)
    buckets = [read, auto, proposals, terminators]
    union: set[str] = set().union(*buckets)
    assert _names(AGENT_TOOLS) == union
    # Pairwise disjoint.
    for i, a in enumerate(buckets):
        for b in buckets[i + 1 :]:
            assert a.isdisjoint(b), f"overlap: {sorted(a & b)}"


def test_dispatch_table_covers_every_tool() -> None:
    """``TOOL_DISPATCH`` must handle every advertised tool except
    the terminators (``final_answer``), which the ReAct loop interprets in
    place rather than dispatching."""
    from app.services.agent import TOOL_DISPATCH
    catalog = {t["function"]["name"] for t in AGENT_TOOLS}
    terminator = _names(_TERMINATOR_TOOLS)
    dispatch = set(TOOL_DISPATCH.keys())
    missing = (catalog - terminator) - dispatch
    assert not missing, f"tools missing from dispatch: {sorted(missing)}"
