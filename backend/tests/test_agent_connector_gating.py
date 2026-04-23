"""Connector-gated tool palette."""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.models.connector_connection import ConnectorConnection
from app.services.agent_tools import (
    FINAL_ANSWER_TOOL_NAME,
    filter_tools_for_user_connectors,
    tool_required_connector_providers,
    tools_for_palette_mode,
)
from app.services.connector_tool_registry import CALENDAR_TOOL_PROVIDERS_FROZEN


def test_tool_required_connector_providers() -> None:
    assert tool_required_connector_providers("gmail_list_messages") is not None
    assert tool_required_connector_providers("final_answer") is None
    assert tool_required_connector_providers("describe_harness") is None
    cal = tool_required_connector_providers("calendar_list_events")
    assert cal == CALENDAR_TOOL_PROVIDERS_FROZEN
    assert "icloud_caldav" in cal


@pytest.mark.asyncio
async def test_filter_removes_gmail_without_connection(db_session, aquila_user) -> None:
    full = tools_for_palette_mode("full")
    names_before = {t["function"]["name"] for t in full}
    assert "gmail_list_messages" in names_before
    out = await filter_tools_for_user_connectors(db_session, aquila_user.id, full)
    names_after = {t["function"]["name"] for t in out}
    assert "gmail_list_messages" not in names_after
    assert FINAL_ANSWER_TOOL_NAME in names_after


@pytest.mark.asyncio
async def test_filter_keeps_calendar_tools_for_icloud_only(db_session, aquila_user) -> None:
    db_session.add(
        ConnectorConnection(
            user_id=aquila_user.id,
            provider="icloud_caldav",
            label="iCloud",
            credentials_encrypted="{}",
        )
    )
    await db_session.flush()
    full = tools_for_palette_mode("full")
    out = await filter_tools_for_user_connectors(db_session, aquila_user.id, full)
    names = {t["function"]["name"] for t in out}
    assert "calendar_list_events" in names
    assert "calendar_list_calendars" in names
    assert "calendar_create_event" in names


@pytest.mark.asyncio
async def test_filter_keeps_gmail_when_linked(db_session, aquila_user) -> None:
    db_session.add(
        ConnectorConnection(
            user_id=aquila_user.id,
            provider="google_gmail",
            label="x",
            credentials_encrypted="{}",
        )
    )
    await db_session.flush()
    full = tools_for_palette_mode("full")
    out = await filter_tools_for_user_connectors(db_session, aquila_user.id, full)
    names = {t["function"]["name"] for t in out}
    assert "gmail_list_messages" in names


@pytest.mark.asyncio
async def test_resolve_turn_palette_falls_back_when_too_small(monkeypatch, db_session, aquila_user) -> None:
    from app.services import agent_service as mod

    async def _empty(_db, _uid, tools):
        return [t for t in tools if t["function"]["name"] == FINAL_ANSWER_TOOL_NAME]

    monkeypatch.setattr(mod, "filter_tools_for_user_connectors", _empty)
    monkeypatch.setattr(settings, "agent_connector_gated_tools", True)
    pal = await mod.resolve_turn_tool_palette(db_session, aquila_user)
    assert len(pal) > 10
