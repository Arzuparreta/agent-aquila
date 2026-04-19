"""Integration tests for agent CRM tools (read + proposal).

Each test asserts concrete evidence in the tool result dict (ids, kinds, payloads).
Requires Postgres with pgvector and ``alembic upgrade head`` (see ``conftest.TEST_DATABASE_URL``).
"""

from __future__ import annotations

from datetime import date, datetime, UTC
from unittest.mock import AsyncMock, patch

import pytest

from app.models.connector_connection import ConnectorConnection
from app.models.contact import Contact
from app.models.deal import Deal
from app.models.drive_file import DriveFile
from app.models.email import Email
from app.models.event import Event
from app.models.user import User
from app.services.agent_service import AgentService
from app.services.llm_client import LLMClient
from app.services.user_ai_settings_service import UserAISettingsService


@pytest.mark.asyncio
async def test_agent_proposal_tool_registry_matches_service() -> None:
    """Proposal tool names must match the expected registry (single source: _PROPOSAL_TOOL_METHODS)."""
    expected = {
        "propose_create_deal",
        "propose_update_deal",
        "propose_create_contact",
        "propose_update_contact",
        "propose_create_event",
        "propose_update_event",
        "propose_connector_email_send",
        "propose_connector_email_reply",
        "propose_connector_calendar_create",
        "propose_connector_calendar_update",
        "propose_connector_calendar_delete",
        "propose_connector_file_upload",
        "propose_connector_file_share",
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


# ---------------------------------------------------------------------------
# Drive tools — list & search are scoped to the user's own connector
# connections so one user never sees another user's mirrored Drive metadata.
# ---------------------------------------------------------------------------


async def _make_drive_connection(db_session, user: User, *, provider: str = "google") -> ConnectorConnection:
    conn = ConnectorConnection(
        user_id=user.id,
        provider=provider,
        label=f"{provider} drive",
        credentials_encrypted="x",
        meta={"status": "active"},
    )
    db_session.add(conn)
    await db_session.flush()
    return conn


@pytest.mark.asyncio
async def test_tool_list_drive_files_returns_user_files_only(db_session, crm_user: User) -> None:
    """list_drive_files must return only the calling user's files (newest first)."""
    mine = await _make_drive_connection(db_session, crm_user)
    other_user = User(
        email="someone-else@example.com",
        hashed_password="x",
        full_name="Other",
    )
    db_session.add(other_user)
    await db_session.flush()
    theirs = await _make_drive_connection(db_session, other_user)

    db_session.add_all(
        [
            DriveFile(
                connection_id=mine.id,
                provider_file_id="f1",
                name="My Rider 2026.pdf",
                mime_type="application/pdf",
                modified_time=datetime(2026, 4, 1, tzinfo=UTC),
            ),
            DriveFile(
                connection_id=mine.id,
                provider_file_id="f2",
                name="Tour Notes.docx",
                mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                modified_time=datetime(2026, 4, 17, tzinfo=UTC),
            ),
            DriveFile(
                connection_id=theirs.id,
                provider_file_id="x1",
                name="LEAK should not appear.txt",
                mime_type="text/plain",
                modified_time=datetime(2026, 4, 18, tzinfo=UTC),
            ),
        ]
    )
    await db_session.flush()

    out = await AgentService._tool_list_drive_files(db_session, crm_user, {})
    assert "files" in out, out
    names = [f["name"] for f in out["files"]]
    assert names == ["Tour Notes.docx", "My Rider 2026.pdf"]
    assert out["count"] == 2
    assert all("LEAK" not in n for n in names)


@pytest.mark.asyncio
async def test_tool_list_drive_files_distinguishes_no_connection_from_empty(
    db_session, crm_user: User
) -> None:
    """When the user has no Drive connection, return a hint so the agent can
    suggest connecting Drive instead of pretending it is empty."""
    out = await AgentService._tool_list_drive_files(db_session, crm_user, {})
    assert out["files"] == []
    assert out["has_drive_connection"] is False
    assert "connect" in out["hint"].lower()

    await _make_drive_connection(db_session, crm_user)
    out2 = await AgentService._tool_list_drive_files(db_session, crm_user, {})
    assert out2["files"] == []
    assert out2["has_drive_connection"] is True
    assert "connected" in out2["hint"].lower()


@pytest.mark.asyncio
async def test_tool_search_drive_is_user_scoped(db_session, crm_user: User) -> None:
    """search_drive must not leak files from other users' Drive connections."""
    mine = await _make_drive_connection(db_session, crm_user)
    other_user = User(email="leak@example.com", hashed_password="x", full_name="Other")
    db_session.add(other_user)
    await db_session.flush()
    theirs = await _make_drive_connection(db_session, other_user)
    db_session.add_all(
        [
            DriveFile(
                connection_id=mine.id,
                provider_file_id="m1",
                name="rider final.pdf",
                modified_time=datetime(2026, 4, 1, tzinfo=UTC),
            ),
            DriveFile(
                connection_id=theirs.id,
                provider_file_id="t1",
                name="rider draft.pdf",
                modified_time=datetime(2026, 4, 2, tzinfo=UTC),
            ),
        ]
    )
    await db_session.flush()

    out = await AgentService._tool_search_drive(db_session, crm_user, {"query": "rider"})
    assert [f["name"] for f in out["hits"]] == ["rider final.pdf"]


# ---------------------------------------------------------------------------
# Tool-schema registry — every tool advertised to the model must be wired
# to a concrete dispatcher branch, otherwise the model picks a tool we
# silently can't run.
# ---------------------------------------------------------------------------


def test_agent_tool_schemas_are_dispatchable() -> None:
    """Every entry in ``AGENT_TOOLS`` must be routable by ``_dispatch_tool``.

    This is the single guard that prevents the "model picks a tool we don't
    actually handle" class of bugs that produced the original ``invalid
    phase`` error in chat.
    """
    from app.services.agent_tools import AGENT_TOOL_NAMES, FINAL_ANSWER_TOOL_NAME

    # final_answer is the conversation-terminator tool: handled directly by
    # the run loop (it sets run.assistant_reply), not by ``_dispatch_tool``.
    advertised = AGENT_TOOL_NAMES - {FINAL_ANSWER_TOOL_NAME}

    dispatchable = (
        {
            "hybrid_rag_search",
            "get_entity",
            "search_emails",
            "get_thread",
            "list_calendar_events",
            "search_drive",
            "list_drive_files",
            "get_drive_file_text",
            "list_connectors",
            "list_automations",
            "create_automation",
            "update_automation",
            "delete_automation",
            "start_connector_setup",
            "submit_connector_credentials",
            "start_oauth_flow",
        }
        | set(AgentService._AUTO_APPLY_TOOL_KIND.keys())
        | set(AgentService._PROPOSAL_TOOL_METHODS.keys())
    )

    # Hard guard: every tool advertised to the model MUST have a dispatcher.
    # Otherwise the model will pick a tool we silently can't run.
    missing = advertised - dispatchable
    assert not missing, f"Tools advertised but not dispatched: {sorted(missing)}"

    # Soft guard: dispatchers that aren't advertised are fine ONLY when
    # they're explicitly marked as deprecated/back-compat. The current
    # legacy back-compat list is the six CRM-write proposal methods that
    # have been superseded by the ``apply_*`` auto-apply variants but are
    # kept as no-op-callable for older clients. If you add a new dispatcher
    # without advertising it to the model, add it here intentionally.
    legacy_back_compat = {
        "propose_create_contact",
        "propose_update_contact",
        "propose_create_deal",
        "propose_update_deal",
        "propose_create_event",
        "propose_update_event",
    }
    extra = (dispatchable - AGENT_TOOL_NAMES) - legacy_back_compat
    assert not extra, (
        "Dispatchable tools missing from the advertised AGENT_TOOLS schema: "
        f"{sorted(extra)}"
    )


def test_agent_tool_schemas_are_openai_function_format() -> None:
    """Each schema must be a valid OpenAI function-tool definition."""
    from app.services.agent_tools import AGENT_TOOLS

    seen: set[str] = set()
    for tool in AGENT_TOOLS:
        assert tool["type"] == "function"
        fn = tool["function"]
        assert isinstance(fn["name"], str) and fn["name"]
        assert fn["name"] not in seen, f"Duplicate tool name: {fn['name']}"
        seen.add(fn["name"])
        assert isinstance(fn["description"], str) and fn["description"]
        params = fn["parameters"]
        assert params["type"] == "object"
        assert isinstance(params.get("properties", {}), dict)


# ---------------------------------------------------------------------------
# run_agent loop — uses native function/tool calling. The model picks tools
# from the typed schema; the loop executes them and feeds results back as
# ``role: "tool"`` messages until the model returns a plain answer.
# ---------------------------------------------------------------------------


def _assistant_tool_call_response(*calls: tuple[str, dict]):
    """Build a fake ``ChatResponse`` requesting one or more tool calls."""
    from app.services.llm_client import ChatResponse, ChatToolCall

    import json as _json

    parsed = []
    raw = []
    for idx, (name, arguments) in enumerate(calls):
        raw_args = _json.dumps(arguments)
        parsed.append(
            ChatToolCall(
                id=f"call_test_{idx + 1}",
                name=name,
                arguments=arguments,
                raw_arguments=raw_args,
            )
        )
        raw.append(
            {
                "id": f"call_test_{idx + 1}",
                "type": "function",
                "function": {"name": name, "arguments": raw_args},
            }
        )
    return ChatResponse(
        content="",
        tool_calls=parsed,
        raw_message={"role": "assistant", "content": None, "tool_calls": raw},
    )


def _final_answer(text: str, citations: list[str] | None = None):
    """Shortcut: a single ``final_answer`` tool call (the terminator)."""
    args: dict = {"text": text}
    if citations is not None:
        args["citations"] = citations
    return _assistant_tool_call_response(("final_answer", args))


def _assistant_text_response(text: str):  # noqa: D401 — kept for the rare lazy-text path
    from app.services.llm_client import ChatResponse

    return ChatResponse(content=text, tool_calls=[], raw_message={"role": "assistant", "content": text})


@pytest.mark.asyncio
async def test_run_agent_drive_listing_uses_native_tool_call(
    db_session, crm_user: User
) -> None:
    """End-to-end golden path: 'qué archivos tengo?' must:

    1. Issue a real ``list_drive_files`` tool call (via native function calling),
    2. Receive the result and feed it back as a ``role:"tool"`` message,
    3. Terminate via the ``final_answer`` tool call with grounded content.

    The harness sends the FULL ``AGENT_TOOLS`` palette on every turn —
    no intent filtering, no must-ground gate, no budget shrink. Tool
    selection is the model's job; rich tool descriptions are the only
    knob. ``tool_choice="required"`` + ``final_answer`` terminator are
    the universal safety net (every turn ends in some tool call).
    """
    conn = await _make_drive_connection(db_session, crm_user)
    db_session.add(
        DriveFile(
            connection_id=conn.id,
            provider_file_id="r1",
            name="Rider Festival 2026.pdf",
            mime_type="application/pdf",
            modified_time=datetime(2026, 4, 17, tzinfo=UTC),
        )
    )
    await db_session.flush()

    turns = iter(
        [
            _assistant_tool_call_response(("list_drive_files", {"limit": 20})),
            _final_answer(
                "Tienes 1 archivo en tu Drive: Rider Festival 2026.pdf",
                citations=["drive_file:1"],
            ),
        ]
    )

    captured_messages: list[list[dict]] = []
    captured_tools: list[list[dict]] = []
    captured_choice: list = []

    async def _fake_chat_with_tools(*_args, messages, tools, tool_choice, **_kwargs):
        captured_messages.append([dict(m) for m in messages])
        captured_tools.append(tools)
        captured_choice.append(tool_choice)
        return next(turns)

    with patch.object(
        LLMClient, "chat_with_tools", new=AsyncMock(side_effect=_fake_chat_with_tools)
    ):
        run = await AgentService.run_agent(db_session, crm_user, "¿Qué archivos tengo?")

    assert run.status == "completed", run.error
    assert run.assistant_reply and "Rider Festival 2026.pdf" in run.assistant_reply
    assert "drive_file:1" in run.assistant_reply  # citations rendered

    # tool_choice must be "required" on every turn — this is the structural
    # guard that prevents lazy text-only replies.
    assert all(c == "required" for c in captured_choice), captured_choice

    # Full ``AGENT_TOOLS`` palette every turn (no filtering, shrink, or gate).
    from app.services.agent_tools import AGENT_TOOLS

    expected_len = len(AGENT_TOOLS)
    expected_names = {t["function"]["name"] for t in AGENT_TOOLS}
    for i, palette in enumerate(captured_tools):
        assert len(palette) == expected_len, f"turn {i + 1}: expected {expected_len} tools"
        names = {t["function"]["name"] for t in palette}
        assert names == expected_names, f"turn {i + 1} palette diverged: {names ^ expected_names}"

    # Tool result must be threaded back as role:"tool" before the model talks.
    second_turn = captured_messages[1]
    tool_msgs = [m for m in second_turn if m.get("role") == "tool"]
    assert len(tool_msgs) == 1
    assert tool_msgs[0]["name"] == "list_drive_files"
    assert "Rider Festival 2026.pdf" in tool_msgs[0]["content"]

    # Run history must record both the data call AND the final_answer call.
    tool_steps = [s for s in run.steps if s.kind == "tool"]
    assert [s.name for s in tool_steps] == ["list_drive_files", "final_answer"]
    assert tool_steps[0].payload["result"]["count"] == 1


@pytest.mark.asyncio
async def test_run_agent_completes_via_final_answer_terminator(
    db_session, crm_user: User
) -> None:
    """A simple 'Hola' should terminate via ``final_answer`` — no real data
    tool needed — and the artist sees the model's text verbatim."""
    text = "¡Hola! ¿En qué puedo ayudarte hoy?"
    with patch.object(
        LLMClient,
        "chat_with_tools",
        new=AsyncMock(return_value=_final_answer(text)),
    ):
        run = await AgentService.run_agent(db_session, crm_user, "Hola")
    assert run.status == "completed"
    assert run.assistant_reply == text


@pytest.mark.asyncio
async def test_run_agent_unknown_tool_returns_generic_error_no_alias_map(
    db_session, crm_user: User
) -> None:
    """The harness has NO tool-name alias map and NO arg-shape coercion.
    When the model calls a tool that does not exist (Gemma's classic
    ``google:search`` RLHF prior, an abbreviation, a misspelling), it
    gets a single terse ``{"error": "unknown tool '...'"}`` back —
    nothing more. No ``valid_tool_names`` payload, no recovery hint, no
    automatic remapping to ``hybrid_rag_search``. The model is expected
    to read its tools list and pick a real name; if it can't, the run
    will exhaust the step budget and fail (the OpenClaw 'use a better
    model' stance)."""
    turns = iter(
        [
            _assistant_tool_call_response(("google:search", {"queries": ["x"]})),
            _final_answer("ok"),
        ]
    )

    async def _fake(*_args, **_kwargs):
        return next(turns)

    with patch.object(LLMClient, "chat_with_tools", new=AsyncMock(side_effect=_fake)):
        run = await AgentService.run_agent(db_session, crm_user, "qué tienes")

    assert run.status == "completed"
    tool_steps = [s for s in run.steps if s.kind == "tool"]
    # Step name is recorded EXACTLY as the model issued it — no aliasing.
    assert tool_steps[0].name == "google:search"
    err = tool_steps[0].payload["result"]
    assert err == {"error": "unknown tool 'google:search'"}, (
        "Unknown-tool errors must be terse: just an error string, no "
        f"valid_tool_names payload, no hint. Got: {err!r}"
    )
    # And the args are NOT coerced — they're recorded as-issued.
    assert tool_steps[0].payload["args"] == {"queries": ["x"]}


@pytest.mark.asyncio
async def test_run_agent_falls_back_to_text_when_provider_ignores_tool_choice(
    db_session, crm_user: User
) -> None:
    """Some providers / older Ollama versions ignore ``tool_choice="required"``
    and return text-only despite the tools array. We accept that as a final
    answer rather than failing the run, so the artist still gets a reply."""
    with patch.object(
        LLMClient,
        "chat_with_tools",
        new=AsyncMock(return_value=_assistant_text_response("respuesta lazy")),
    ):
        run = await AgentService.run_agent(db_session, crm_user, "x")
    assert run.status == "completed"
    assert run.assistant_reply == "respuesta lazy"


# ---------------------------------------------------------------------------
# Connector sync-health surfacing
# ---------------------------------------------------------------------------
# The agent's read tools must include a sync_health field so the model can
# warn the artist when the upstream sync is broken (e.g. Drive API disabled,
# token revoked) — before the redesign there was NO way for the artist to
# learn about silent worker failures. The sync_health summary is also written
# in artist-friendly Spanish so the model can quote it directly.

async def _seed_sync_state(
    db_session,
    connection: ConnectorConnection,
    *,
    resource: str,
    status: str = "error",
    last_error: str = "",
    error_count: int = 1,
):
    from app.models.connection_sync_state import ConnectionSyncState

    state = ConnectionSyncState(
        connection_id=connection.id,
        resource=resource,
        status=status,
        last_error=last_error,
        error_count=error_count,
    )
    db_session.add(state)
    await db_session.flush()
    return state


@pytest.mark.asyncio
async def test_list_drive_files_surfaces_sync_health_when_api_disabled(
    db_session, crm_user: User
) -> None:
    """When the Drive sync is failing because the GCP API is disabled, the
    list_drive_files result must include a sync_health.ok=False payload with
    a Spanish-language summary the model can echo to the artist verbatim.
    Otherwise the artist sees 'no files' with no explanation of why."""
    conn = await _make_drive_connection(db_session, crm_user, provider="google_drive")
    await _seed_sync_state(
        db_session,
        conn,
        resource="drive",
        status="error",
        last_error=(
            'Drive API 403: { "error": { "code": 403, "message": '
            '"Google Drive API has not been used in project 12345 before '
            'or it is disabled. ..." } }'
        ),
        error_count=9,
    )

    out = await AgentService._tool_list_drive_files(db_session, crm_user, {})
    assert "sync_health" in out
    sh = out["sync_health"]
    assert sh["ok"] is False
    assert "Drive" in sh["summary"]
    assert "API correspondiente está desactivado" in sh["summary"]
    assert any(e["status"] == "error" for e in sh["errors"])


@pytest.mark.asyncio
async def test_list_drive_files_sync_health_ok_when_no_errors(
    db_session, crm_user: User
) -> None:
    """Healthy connections must not pollute results with phantom warnings."""
    conn = await _make_drive_connection(db_session, crm_user, provider="google_drive")
    await _seed_sync_state(db_session, conn, resource="drive", status="idle")
    db_session.add(
        DriveFile(
            connection_id=conn.id,
            provider_file_id="ok1",
            name="Healthy Doc.pdf",
            mime_type="application/pdf",
            modified_time=datetime(2026, 4, 18, tzinfo=UTC),
        )
    )
    await db_session.flush()

    out = await AgentService._tool_list_drive_files(db_session, crm_user, {})
    assert out["sync_health"]["ok"] is True
    assert len(out["files"]) == 1


@pytest.mark.asyncio
async def test_list_calendar_events_surfaces_sync_health(
    db_session, crm_user: User
) -> None:
    """Same surfacing must apply to calendar — when the upstream Calendar
    sync errors out, list_calendar_events must include the warning so the
    model can tell the artist why the agenda is empty/stale."""
    conn = ConnectorConnection(
        user_id=crm_user.id,
        provider="google_calendar",
        label="cal",
        credentials_encrypted="x",
    )
    db_session.add(conn)
    await db_session.flush()
    await _seed_sync_state(
        db_session,
        conn,
        resource="calendar",
        status="error",
        last_error="invalid_grant: token has been expired or revoked.",
        error_count=3,
    )

    out = await AgentService._tool_list_calendar_events(db_session, crm_user, {})
    assert out["sync_health"]["ok"] is False
    assert "Calendario" in out["sync_health"]["summary"]
    assert "re-autoriz" in out["sync_health"]["summary"].lower()


@pytest.mark.asyncio
async def test_search_emails_surfaces_sync_health_for_gmail(
    db_session, crm_user: User
) -> None:
    """Emails read tool must surface Gmail sync errors (same pattern)."""
    conn = ConnectorConnection(
        user_id=crm_user.id,
        provider="google_gmail",
        label="gmail",
        credentials_encrypted="x",
    )
    db_session.add(conn)
    await db_session.flush()
    await _seed_sync_state(
        db_session,
        conn,
        resource="gmail",
        status="error",
        last_error="429 Too Many Requests: rate limit exceeded",
        error_count=2,
    )

    out = await AgentService._tool_search_emails(db_session, crm_user, {})
    assert out["sync_health"]["ok"] is False
    assert "Correo" in out["sync_health"]["summary"]


@pytest.mark.asyncio
async def test_create_connection_auto_enqueues_initial_sync(
    db_session, crm_user: User
) -> None:
    """Manually-created connections (e.g. via 'submit_connector_credentials')
    must auto-enqueue the right *_initial_sync job so the artist sees their
    data appear without waiting for the next 5-minute cron tick. This was
    previously only happening via the OAuth path; non-OAuth connections sat
    in the DB silently un-synced."""
    from app.schemas.connector import ConnectorConnectionCreate
    from app.services.connector_service import ConnectorService

    enqueued: list[tuple[str, int, str | None]] = []

    async def _capture(name, *args, job_id=None, **_kwargs):
        enqueued.append((name, args[0] if args else None, job_id))
        return "ok"

    payload = ConnectorConnectionCreate(
        provider="google_drive",
        label="manual drive",
        credentials={"refresh_token": "x"},
    )

    with patch("app.services.connector_service.enqueue_initial_sync_for_connection",
               wraps=None):
        # Patch at the inner enqueue_job import site instead.
        pass

    with patch("app.services.job_queue.enqueue", new=AsyncMock(side_effect=_capture)):
        row = await ConnectorService.create_connection(db_session, crm_user, payload)

    assert row.id is not None
    assert enqueued, "create_connection must enqueue an initial sync job"
    job_name, conn_id, job_id = enqueued[0]
    assert job_name == "drive_initial_sync"
    assert conn_id == row.id
    assert job_id == f"drive-initial-{row.id}"


@pytest.mark.asyncio
async def test_create_connection_no_op_for_unknown_provider(
    db_session, crm_user: User
) -> None:
    """Providers without an associated sync (e.g. teams-only adapters) must
    NOT crash create_connection or enqueue a phantom job."""
    from app.schemas.connector import ConnectorConnectionCreate
    from app.services.connector_service import ConnectorService

    enqueued: list = []

    async def _capture(*args, **_kwargs):
        enqueued.append(args)
        return "ok"

    payload = ConnectorConnectionCreate(
        provider="microsoft_teams",
        label="teams",
        credentials={"k": "v"},
    )
    with patch("app.services.job_queue.enqueue", new=AsyncMock(side_effect=_capture)):
        row = await ConnectorService.create_connection(db_session, crm_user, payload)

    assert row.id is not None
    assert enqueued == []  # no sync registered for this provider — no-op
