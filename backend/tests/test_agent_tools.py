"""Integration tests for agent CRM tools (read + proposal).

Each test asserts concrete evidence in the tool result dict (ids, kinds, payloads).
Requires Postgres with pgvector and ``alembic upgrade head`` (see ``conftest.TEST_DATABASE_URL``).
"""

from __future__ import annotations

from datetime import date, datetime, UTC
from unittest.mock import AsyncMock, patch

import pytest

from app.models.contact import Contact
from app.models.deal import Deal
from app.models.email import Email
from app.models.event import Event
from app.models.user import User
from app.services.agent_service import AgentService
from app.services.embedding_client import EmbeddingClient
from app.services.embedding_vector import pad_embedding
from app.services.user_ai_settings_service import UserAISettingsService


@pytest.mark.asyncio
async def test_agent_proposal_tool_registry_matches_service() -> None:
    """Every proposal tool name in AGENT_SYSTEM must map to a handler (single source: _PROPOSAL_TOOL_METHODS)."""
    expected = {
        "propose_create_deal",
        "propose_update_deal",
        "propose_create_contact",
        "propose_update_contact",
        "propose_create_event",
        "propose_update_event",
        "propose_connector_email_send",
        "propose_connector_calendar_create",
        "propose_connector_file_upload",
        "propose_connector_teams_message",
    }
    assert set(AgentService._PROPOSAL_TOOL_METHODS.keys()) == expected


@pytest.mark.asyncio
async def test_tool_hybrid_rag_search_missing_query(db_session, crm_user: User) -> None:
    out = await AgentService._tool_rag(db_session, crm_user, {})
    assert out == {"hits": [], "error": "missing query"}


@pytest.mark.asyncio
async def test_tool_hybrid_rag_search_ai_disabled(db_session, crm_user: User) -> None:
    settings_row = await UserAISettingsService.get_or_create(db_session, crm_user)
    settings_row.ai_disabled = True
    await db_session.flush()
    out = await AgentService._tool_rag(db_session, crm_user, {"query": "anything"})
    assert out == {"hits": []}


@pytest.mark.asyncio
async def test_tool_hybrid_rag_search_returns_hits_legacy_vector_path(
    db_session, crm_user: User
) -> None:
    """Legacy entity embeddings path: no rag_chunks rows, contact with embedding matches mocked query vector."""
    query_vec = pad_embedding([1.0])
    contact = Contact(
        name="Pepe Festival Booker",
        email="pepe-booker@example.com",
        notes="books summer festivals",
        embedding=query_vec,
        embedding_model="test",
        embedding_updated_at=datetime.now(UTC),
    )
    db_session.add(contact)
    await db_session.flush()

    async def _fake_embed(_api_key: str, _settings, texts: list[str]) -> list[list[float]]:
        assert texts and "festival" in texts[0].lower()
        return [query_vec]

    with patch.object(EmbeddingClient, "embed_texts", new=AsyncMock(side_effect=_fake_embed)):
        out = await AgentService._tool_rag(db_session, crm_user, {"query": "summer festival", "limit_per_type": 5})

    assert "hits" in out and "error" not in out
    assert len(out["hits"]) >= 1
    hit = next(h for h in out["hits"] if h["entity_type"] == "contact" and h["entity_id"] == contact.id)
    assert hit["citation"] == f"contact:{contact.id}"
    assert "vector_legacy" in hit["match_sources"]
    assert hit["title"] == "Pepe Festival Booker"
    assert "festival" in (hit.get("snippet") or "").lower() or "book" in (hit.get("snippet") or "").lower()


@pytest.mark.asyncio
async def test_tool_get_entity_contact_found(db_session) -> None:
    contact = Contact(name="Entity Test", email="entity-test@example.com")
    db_session.add(contact)
    await db_session.flush()

    out = await AgentService._tool_get_entity(
        db_session, {"entity_type": "contact", "entity_id": contact.id}
    )
    assert out["found"] is True
    assert out["entity"]["id"] == contact.id
    assert out["entity"]["name"] == "Entity Test"
    assert out["entity"]["email"] == "entity-test@example.com"


@pytest.mark.asyncio
async def test_tool_get_entity_email_deal_event(db_session) -> None:
    contact = Contact(name="Mail Partner")
    db_session.add(contact)
    await db_session.flush()
    email = Email(
        contact_id=contact.id,
        sender_email="a@b.com",
        subject="Headline",
        body="Body text for snippet",
    )
    deal = Deal(contact_id=contact.id, title="Summer Tour", status="negotiating")
    db_session.add_all([email, deal])
    await db_session.flush()
    ev = Event(deal_id=deal.id, venue_name="Arena", event_date=date(2026, 7, 1), city="Madrid")
    db_session.add(ev)
    await db_session.flush()

    e_out = await AgentService._tool_get_entity(db_session, {"entity_type": "email", "entity_id": email.id})
    assert e_out["found"] and e_out["entity"]["subject"] == "Headline"

    d_out = await AgentService._tool_get_entity(db_session, {"entity_type": "deal", "entity_id": deal.id})
    assert d_out["found"] and d_out["entity"]["title"] == "Summer Tour"

    ev_out = await AgentService._tool_get_entity(db_session, {"entity_type": "event", "entity_id": ev.id})
    assert ev_out["found"] and ev_out["entity"]["venue_name"] == "Arena"


@pytest.mark.asyncio
async def test_tool_get_entity_not_found_and_invalid_type(db_session) -> None:
    missing = await AgentService._tool_get_entity(db_session, {"entity_type": "contact", "entity_id": 999_999_999})
    assert missing["found"] is False
    assert missing["entity"] is None

    bad = await AgentService._tool_get_entity(db_session, {"entity_type": "unknown", "entity_id": 1})
    assert bad == {"error": "invalid entity_type"}


@pytest.mark.asyncio
async def test_propose_create_contact(db_session, crm_user: User, agent_run) -> None:
    out = await AgentService._tool_propose_create_contact(
        db_session,
        crm_user,
        agent_run.id,
        {"name": "Pepe", "email": "pepe@gmail.com"},
    )
    assert out["status"] == "pending"
    assert out["kind"] == "create_contact"
    assert isinstance(out["proposal_id"], int)
    assert "approve" in out["message"].lower() or "human" in out["message"].lower()


@pytest.mark.asyncio
async def test_propose_create_contact_idempotency(db_session, crm_user: User, agent_run) -> None:
    args = {"name": "Pepe", "email": "pepe@gmail.com", "idempotency_key": "idem-pepe-1"}
    first = await AgentService._tool_propose_create_contact(db_session, crm_user, agent_run.id, args)
    second = await AgentService._tool_propose_create_contact(db_session, crm_user, agent_run.id, args)
    assert first["proposal_id"] == second["proposal_id"]
    assert second.get("deduplicated") is True


@pytest.mark.asyncio
async def test_propose_update_contact_and_no_fields_error(db_session, crm_user: User, agent_run) -> None:
    contact = Contact(name="Before", email="before@example.com")
    db_session.add(contact)
    await db_session.flush()

    empty = await AgentService._tool_propose_update_contact(
        db_session, crm_user, agent_run.id, {"contact_id": contact.id}
    )
    assert empty.get("error") == "no fields to update"

    out = await AgentService._tool_propose_update_contact(
        db_session,
        crm_user,
        agent_run.id,
        {"contact_id": contact.id, "name": "After", "email": "after@example.com"},
    )
    assert out["kind"] == "update_contact"
    assert out["proposal_id"]


@pytest.mark.asyncio
async def test_propose_create_deal_and_update_deal(db_session, crm_user: User, agent_run) -> None:
    contact = Contact(name="Promoter")
    db_session.add(contact)
    await db_session.flush()

    c_out = await AgentService._tool_propose_create_deal(
        db_session,
        crm_user,
        agent_run.id,
        {"contact_id": contact.id, "title": "Main stage", "amount": 5000, "currency": "EUR"},
    )
    assert c_out["kind"] == "create_deal"

    deal = Deal(contact_id=contact.id, title="Existing", status="new")
    db_session.add(deal)
    await db_session.flush()

    u_empty = await AgentService._tool_propose_update_deal(
        db_session, crm_user, agent_run.id, {"deal_id": deal.id}
    )
    assert u_empty.get("error") == "no fields to update"

    u_out = await AgentService._tool_propose_update_deal(
        db_session,
        crm_user,
        agent_run.id,
        {"deal_id": deal.id, "status": "won", "notes": "Signed"},
    )
    assert u_out["kind"] == "update_deal"


@pytest.mark.asyncio
async def test_propose_create_event_and_update_event(db_session, crm_user: User, agent_run) -> None:
    c_out = await AgentService._tool_propose_create_event(
        db_session,
        crm_user,
        agent_run.id,
        {"venue_name": "Stadium", "event_date": "2026-08-15", "city": "Barcelona"},
    )
    assert c_out["kind"] == "create_event"

    contact = Contact(name="C")
    db_session.add(contact)
    await db_session.flush()
    deal = Deal(contact_id=contact.id, title="D")
    db_session.add(deal)
    await db_session.flush()
    ev = Event(deal_id=deal.id, venue_name="Old", event_date=date(2026, 1, 1))
    db_session.add(ev)
    await db_session.flush()

    u_empty = await AgentService._tool_propose_update_event(
        db_session, crm_user, agent_run.id, {"event_id": ev.id}
    )
    assert u_empty.get("error") == "no fields to update"

    u_out = await AgentService._tool_propose_update_event(
        db_session,
        crm_user,
        agent_run.id,
        {"event_id": ev.id, "venue_name": "New venue", "status": "cancelled"},
    )
    assert u_out["kind"] == "update_event"


@pytest.mark.asyncio
async def test_propose_connector_email_send(db_session, crm_user: User, agent_run) -> None:
    out = await AgentService._tool_propose_connector_email_send(
        db_session,
        crm_user,
        agent_run.id,
        {"connection_id": 42, "to": "pepe@gmail.com", "subject": "Hello", "body": "Hi Pepe"},
    )
    assert out["kind"] == "connector_email_send"


@pytest.mark.asyncio
async def test_propose_connector_calendar_create_summary_and_title_alias(
    db_session, crm_user: User, agent_run
) -> None:
    with_summary = await AgentService._tool_propose_connector_calendar_create(
        db_session,
        crm_user,
        agent_run.id,
        {
            "connection_id": 1,
            "summary": "Call",
            "start_iso": "2026-04-20T10:00:00+00:00",
            "end_iso": "2026-04-20T10:30:00+00:00",
        },
    )
    assert with_summary["kind"] == "connector_calendar_create"

    with_title = await AgentService._tool_propose_connector_calendar_create(
        db_session,
        crm_user,
        agent_run.id,
        {
            "connection_id": 1,
            "title": "Fallback title",
            "start_iso": "2026-04-21T10:00:00+00:00",
            "end_iso": "2026-04-21T10:30:00+00:00",
        },
    )
    assert with_title["kind"] == "connector_calendar_create"


@pytest.mark.asyncio
async def test_propose_connector_file_upload_and_missing_content_error(
    db_session, crm_user: User, agent_run
) -> None:
    bad = await AgentService._tool_propose_connector_file_upload(
        db_session,
        crm_user,
        agent_run.id,
        {"connection_id": 7, "path": "/tmp/x.txt", "mime_type": "text/plain"},
    )
    assert bad.get("error") == "content_text or content_base64 required"

    ok = await AgentService._tool_propose_connector_file_upload(
        db_session,
        crm_user,
        agent_run.id,
        {"connection_id": 7, "path": "/tmp/x.txt", "content_text": "hello"},
    )
    assert ok["kind"] == "connector_file_upload"


@pytest.mark.asyncio
async def test_propose_connector_teams_message(db_session, crm_user: User, agent_run) -> None:
    out = await AgentService._tool_propose_connector_teams_message(
        db_session,
        crm_user,
        agent_run.id,
        {
            "connection_id": 3,
            "team_id": "team-1",
            "channel_id": "chan-1",
            "body": "Status update",
        },
    )
    assert out["kind"] == "connector_teams_message"
