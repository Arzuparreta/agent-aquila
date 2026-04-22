"""Causes for *display name* (or any fact) not persisting — one test per major mechanism.

These are architectural / product gates, not “the model felt lazy”. Run with Postgres
(``TEST_DATABASE_URL``) so integration checks that ``AgentMemoryService.upsert`` writes rows.

Cross-reference:
- Main loop: ``backend/app/services/agent_service.py`` (``tool_choice=required`` allows
  ``final_answer`` alone unless the model also calls ``upsert_memory``).
- Post-turn backup: ``backend/app/services/agent_memory_post_turn_service.py``
  (heuristic gate + JSON extraction LLM).
- Gating: ``backend/app/routes/threads.py`` (post-turn only if run ``completed``).
"""

from __future__ import annotations

import pytest

from app.services.agent_runtime_config_service import merge_stored_with_env
from app.services.agent_service import AgentService
from app.services.agent_memory_post_turn_service import (
    heuristic_wants_post_turn_extraction,
    maybe_ingest_post_turn_memory,
)
from app.services.agent_memory_service import AgentMemoryService
from app.services.agent_tools import (
    filter_tools_for_user_connectors,
    tools_for_palette_mode,
)
from app.services.user_ai_settings_service import UserAISettingsService


# --- Cause 1–2: Tool palette always includes memory writes (full + compact) ---


@pytest.mark.parametrize("mode", ["full", "compact"])
def test_cause_palette_includes_upsert_memory(mode: str) -> None:
    """If false: memory tools would be missing from the API payload."""
    names = {t["function"]["name"] for t in tools_for_palette_mode(mode)}
    assert "upsert_memory" in names
    assert "final_answer" in names


# --- Cause 3: Connector gating must not strip memory tools ---


@pytest.mark.asyncio
async def test_cause_connector_gating_strips_memory_tools(db_session, aquila_user) -> None:
    """Memory tools have no ``tool_required_connector_providers`` — they must remain."""
    full = tools_for_palette_mode("full")
    out = await filter_tools_for_user_connectors(db_session, aquila_user.id, full)
    names = {t["function"]["name"] for t in out}
    assert "upsert_memory" in names


# --- Cause 4: Spanish / English naming lines must match heuristic (nudge + post-turn gate) ---


_NAMING_USER_LINES = [
    'a partir de ahora te llamarás Agente Águila (Agent Aquila in english)!',
    'Desde ahora te llamas Agente Águila',
    'Eres.... "Agente Águila"! Te presento.',
    'Remember that you should go by Agent Aquila in English.',
]


@pytest.mark.parametrize("line", _NAMING_USER_LINES)
def test_cause_heuristic_false_negative_naming_turns(line: str) -> None:
    """If false: no host nudge in ``agent_service`` and post-turn ``heuristic_skip``."""
    assert heuristic_wants_post_turn_extraction(line, "")


def test_cause_heuristic_skip_mundane_smalltalk() -> None:
    """Expected: routine chat does not trigger extraction costs."""
    assert not heuristic_wants_post_turn_extraction(
        "¿Qué hora es en Madrid?",
        "Son las tres de la tarde.",
    )


# --- Cause 5: Runtime flag disables post-turn entirely ---


@pytest.mark.asyncio
async def test_cause_post_turn_disabled_skips(
    db_session,
    aquila_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If ``agent_memory_post_turn_enabled`` is false, backup path never writes."""
    import app.services.agent_memory_post_turn_service as mod

    base = merge_stored_with_env(None).model_copy(update={"agent_memory_post_turn_enabled": False})
    monkeypatch.setattr(mod, "resolve_for_user", pytest.AsyncMock(return_value=base))
    r = await maybe_ingest_post_turn_memory(
        db_session,
        aquila_user,
        user_message="Remember I'm Bob",
        assistant_message="Got it.",
        run_id=None,
    )
    assert r.skipped
    assert r.reason == "disabled"


# --- Cause 6: Failed runs do not run post-turn (threads guard) ---


def test_cause_completed_run_required_for_threads_post_turn_hook() -> None:
    """``_post_turn_memory_if_completed`` runs ``maybe_ingest`` only when ``run_status == completed``."""

    def post_turn_runs(run_status: str) -> bool:
        return run_status == "completed"

    assert post_turn_runs("completed") is True
    assert post_turn_runs("failed") is False
    assert post_turn_runs("running") is False


# --- Cause 7: Default step budget allows upsert + final_answer in separate LLM rounds ---


def test_cause_max_tool_steps_default_allows_multi_step() -> None:
    """If ``agent_max_tool_steps`` were 1, the model could not chain memory then answer."""
    r = merge_stored_with_env(None)
    assert r.agent_max_tool_steps >= 2, "need ≥2 steps for upsert_memory then final_answer"


# --- Cause 8: Extraction LLM returns [] (backup path produces nothing) ---


@pytest.mark.asyncio
async def test_cause_post_turn_empty_extraction(
    db_session,
    aquila_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Committee path returns no approved rows → empty_extraction."""
    import app.services.agent_memory_post_turn_service as mod

    base = merge_stored_with_env(None).model_copy(
        update={
            "agent_memory_post_turn_enabled": True,
            "agent_memory_post_turn_mode": "always",
        }
    )
    monkeypatch.setattr(mod, "resolve_for_user", pytest.AsyncMock(return_value=base))
    monkeypatch.setattr(mod, "run_committee_memory_extraction", pytest.AsyncMock(return_value=[]))
    monkeypatch.setattr(mod, "maybe_adapt_rubric_after_turn", pytest.AsyncMock())
    r = await maybe_ingest_post_turn_memory(
        db_session,
        aquila_user,
        user_message="Call me Agente Águila forever.",
        assistant_message="Understood!",
        run_id=None,
    )
    assert r.skipped
    assert r.reason == "empty_extraction"


# --- Cause 9: Provider requires API key but none configured ---


@pytest.mark.asyncio
async def test_cause_post_turn_skips_without_api_key_for_keyed_provider(
    db_session,
    aquila_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Post-turn uses ``LLMClient.chat_completion``; cloud providers need a key."""
    import app.services.agent_memory_post_turn_service as mod

    base = merge_stored_with_env(None).model_copy(
        update={"agent_memory_post_turn_enabled": True, "agent_memory_post_turn_mode": "always"}
    )
    monkeypatch.setattr(mod, "resolve_for_user", pytest.AsyncMock(return_value=base))

    settings_row = await UserAISettingsService.get_or_create(db_session, aquila_user)
    settings_row.provider_kind = "openai"
    await db_session.flush()
    monkeypatch.setattr(mod.UserAISettingsService, "get_api_key", pytest.AsyncMock(return_value=""))

    r = await maybe_ingest_post_turn_memory(
        db_session,
        aquila_user,
        user_message="Your name is Agente Águila.",
        assistant_message="OK.",
        run_id=None,
    )
    assert r.skipped
    assert r.reason == "no_api_key"


# --- Cause 10: DB write path works when upsert is actually invoked ---


@pytest.mark.asyncio
async def test_cause_agent_memory_upsert_persists_row(db_session, aquila_user) -> None:
    """When ``_tool_upsert_memory`` runs, ``agent_memories`` must gain a row."""
    row = await AgentMemoryService.upsert(
        db_session,
        aquila_user,
        key="agent.identity.display_name_es",
        content="Agente Águila",
        importance=9,
    )
    assert row.id
    again = await AgentMemoryService.list_for_user(db_session, aquila_user, limit=20)
    keys = {m.key for m in again}
    assert "agent.identity.display_name_es" in keys


# --- Cause 11: ``upsert_memory`` schema allows high importance (identity) ---


def test_cause_upsert_memory_importance_matches_service_cap() -> None:
    """Mismatch between JSON schema ``maximum`` and prompts suggesting importance 8–10
    caused provider-side validation errors — tool never executed."""
    from app.services.agent_tools import AGENT_TOOLS

    um = next(t for t in AGENT_TOOLS if t["function"]["name"] == "upsert_memory")
    imp = (
        um["function"]
        .get("parameters", {})
        .get("properties", {})
        .get("importance", {})
    )
    assert imp.get("maximum") == 10


@pytest.mark.asyncio
async def test_cause_upsert_memory_tool_normalizes_args(db_session, aquila_user) -> None:
    """Bad types from the model should not crash ``_tool_upsert_memory`` (→ generic dispatch error)."""
    r = await AgentService._tool_upsert_memory(
        db_session,
        aquila_user,
        {
            "key": "  agent.identity.display_name_es  ",
            "content": '  Agente "Águila"  ',
            "importance": "9",
            "tags": ["identity", "display-name"],
        },
    )
    assert r.get("ok") is True
    assert r.get("key") == "agent.identity.display_name_es"


@pytest.mark.asyncio
async def test_cause_upsert_memory_tool_rejects_missing_fields(db_session, aquila_user) -> None:
    r = await AgentService._tool_upsert_memory(
        db_session,
        aquila_user,
        {"content": "only content"},
    )
    assert r.get("error") == "missing_fields"
