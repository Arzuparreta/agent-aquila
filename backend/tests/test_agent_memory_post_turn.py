"""Tests for post-turn memory extraction heuristics and parsing."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.user import User
from app.services.agent_memory_post_turn_service import (
    _parse_json_object,
    heuristic_wants_post_turn_extraction,
    maybe_ingest_post_turn_memory,
)
from app.services.agent_memory_service import AgentMemoryService
from app.services.agent_runtime_config_service import merge_stored_with_env


def test_heuristic_remembers_and_names() -> None:
    assert heuristic_wants_post_turn_extraction(
        "Remember that I prefer morning meetings",
        "Got it.",
    )
    assert heuristic_wants_post_turn_extraction(
        "Eres Agente Áquila en español y Agent Aquila en inglés.",
        "Perfecto, lo tendré en cuenta.",
    )
    assert heuristic_wants_post_turn_extraction(
        "Vale pues ese es tu nombre!",
        "¡Perfecto! A partir de ahora soy el Agente Áquila.",
    )
    assert heuristic_wants_post_turn_extraction(
        "That's your name — I'll use it.",
        "Sounds good.",
    )
    assert not heuristic_wants_post_turn_extraction(
        "¿Qué hora es?",
        "Son las tres.",
    )
    # "Eres...." without a space after Eres must still signal identity (native tool path nudge).
    assert heuristic_wants_post_turn_extraction(
        'Eres.... "Agente Águila"! Te',
        "¡Me encanta! A partir de ahora soy el **Agente Águila**.",
    )
    # Assistant promises future recall (Spanish) — should run post-turn extraction if main turn missed tools.
    assert heuristic_wants_post_turn_extraction(
        "ok",
        "Lo recordaré para nuestras próximas conversaciones.",
    )
    # "a partir de ahora te llamarás …" was not matched by older regexes → no host nudge, post_turn heuristic_skip.
    assert heuristic_wants_post_turn_extraction(
        "a partir de ahora te llamarás Agente Águila (Agent Aquila in english)!",
        "¡Entendido! A partir de ahora me llamaré **Agente Águila**.",
    )


def test_parse_json_object_fenced() -> None:
    raw = '```json\n{"memories":[{"key":"a.b","content":"x","importance":3}]}\n```'
    out = _parse_json_object(raw)
    assert out["memories"][0]["key"] == "a.b"


@pytest.mark.asyncio
async def test_maybe_ingest_skips_when_heuristic_no_match(
    db_session,
    crm_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.agent_memory_post_turn_service as mod

    base = merge_stored_with_env(None)
    fake_rt = base.model_copy(
        update={"agent_memory_post_turn_enabled": True, "agent_memory_post_turn_mode": "heuristic"}
    )
    monkeypatch.setattr(mod, "resolve_for_user", AsyncMock(return_value=fake_rt))
    spy = AsyncMock()
    monkeypatch.setattr(mod.LLMClient, "chat_completion", spy)
    result = await maybe_ingest_post_turn_memory(
        db_session,
        crm_user,
        user_message="Hola",
        assistant_message="Hola, ¿en qué puedo ayudarte?",
    )
    assert result.skipped
    assert result.reason == "heuristic_skip"
    assert result.upserts == 0
    spy.assert_not_called()


@pytest.mark.asyncio
async def test_maybe_ingest_upserts_from_committee(
    db_session,
    crm_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.agent_memory_post_turn_service as mod

    base = merge_stored_with_env(None)
    fake_rt = base.model_copy(
        update={"agent_memory_post_turn_enabled": True, "agent_memory_post_turn_mode": "always"}
    )
    monkeypatch.setattr(mod, "resolve_for_user", AsyncMock(return_value=fake_rt))

    async def fake_committee(*_a, **_k):
        return [
            {
                "key": "agent.identity.display_name_es",
                "content": "Agente Áquila",
                "importance": 9,
            }
        ]

    monkeypatch.setattr(mod, "run_committee_memory_extraction", fake_committee)
    monkeypatch.setattr(mod, "maybe_adapt_rubric_after_turn", AsyncMock())

    calls: list[dict] = []

    async def upsert_side_effect(db, user, **kwargs):
        calls.append(kwargs)
        m = MagicMock()
        m.key = kwargs["key"]
        return m

    monkeypatch.setattr(AgentMemoryService, "upsert", AsyncMock(side_effect=upsert_side_effect))

    result = await maybe_ingest_post_turn_memory(
        db_session,
        crm_user,
        user_message="Your name is Agent Aquila.",
        assistant_message="Understood.",
    )
    assert not result.skipped
    assert result.upserts == 1
    assert calls[0]["key"] == "agent.identity.display_name_es"
    assert calls[0]["content"] == "Agente Áquila"
    assert calls[0]["importance"] == 9
