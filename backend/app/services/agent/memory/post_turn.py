"""Simplified post-turn memory: heuristic skip + single LLM extraction pass.

Removes committee, rubric, and adaptive modes. Uses a fast heuristic to skip
trivial exchanges, then a single LLM call to extract durable facts.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.services.agent_memory_service import AgentMemoryService
from app.services.llm_client import LLMClient

logger = logging.getLogger(__name__)

_MAX_KEY_LEN = 200
_MAX_CONTENT_LEN = 8000
_MAX_MEMORIES = 12

# User text: remember / name / preference signals (EN + ES).
_USER_MEMORY_HINT = re.compile(
    r"(?:^|\b)(?:remember|recuerda|recuerde|recuerdas|don'?t\s+forget|no\s+olvides|"
    r"prefer|prefiero|prefieres|preference|preferencia|"
    r"my\s+name\s+is|me\s+llamo|ll[aá]mame|ll[aá]mate|your\s+name\b|tu\s+nombre|"
    r"te\s+llamas|te\s+llamar[áa]s|te\s+llamaras\b|how\s+should\s+i\s+call|c[oó]mo\s+te\s+llamo|"
    r"a\s+partir\s+de\s+ahora|desde\s+ahora\s+te\s+llam|"
    r"\byou\s+are\s+|\beres\b|you'?re\s+the\s+|"
    r"call\s+me|call\s+yourself|"
    r"guarda\s+en\s+memoria|guardar\s+en\s+memoria|"
    r"i\s+want\s+you\s+to\s+remember|quiero\s+que\s+recuerdes)(?:\b|$)",
    re.IGNORECASE | re.MULTILINE,
)

# Assistant text: claimed persistence.
_ASSISTANT_MEMORY_PROMISE = re.compile(
    r"(?:^|\b)(?:guardo\s+en\s+memoria|lo\s+guardo|guardar[eé]\s+en\s+memoria|"
    r"i['’]?ll\s+save|i\s+will\s+save|saved\s+to\s+memory|"
    r"lo\s+memorizo|memorizar[eé]|"
    r"lo\s+recordar[eé]|recordar[eé]\s+para|"
    r"i['’]?ll\s+remember|remember\s+for|"
    r"a\s+partir\s+de\s+ahora\s+me\s+llamar|me\s+llamar[ée]|me\s+llamare)(?:\b|$)",
    re.IGNORECASE | re.MULTILINE,
)

_SIMPLE_EXTRACTION_SYSTEM = """Extract durable facts from this exchange for a personal assistant's memory.
Return ONLY a JSON object with this exact shape:
{"memories":[{"key":"string","content":"string","importance":0}]}

Rules:
- Keys: lowercase, dot-separated. Use prefixes: user.profile.*, agent.identity.*, memory.durable.*, prefs.*
- Content: short plain text; one fact per entry.
- importance: 0-10 (use 8-10 for identity or explicitly requested memory)
- Skip memory.durable.* for one-off tool results that will go stale.
- If user or assistant assigns/confirm assistant's name, emit agent.identity.display_name_* (importance 8-10).
- Do NOT claim scheduled/background help is impossible — heartbeat is supported.
- If no durable fact, return {"memories":[]}."""


class PostTurnMemoryResult:
    """Result of post-turn memory extraction."""

    def __init__(self, *, skipped: bool, reason: str, upserts: int, stored_keys=(), stored_items=()):
        self.skipped = skipped
        self.reason = reason
        self.upserts = upserts
        self.stored_keys = tuple(stored_keys)
        self.stored_items = tuple(stored_items)


def heuristic_wants_post_turn_extraction(user_message: str, assistant_message: str) -> bool:
    """Return True when the last exchange likely contains durable memory."""
    u = (user_message or "").strip()
    a = (assistant_message or "").strip()
    if not u and not a:
        return False
    if _USER_MEMORY_HINT.search(u):
        return True
    if _ASSISTANT_MEMORY_PROMISE.search(a):
        return True
    # Short identity-style turns
    if len(u) <= 600 and (
        re.search(r"\b(agente|agent|águila|aquila|assistant|asistente)\b", u, re.I)
        and re.search(r"\b(eres|you are|llam|name|nombre|call|llamar[áa]s|llamaras)\b", u, re.I)
    ):
        return True
    return False


def _parse_json_object(raw: str) -> dict[str, Any]:
    """Parse JSON from text, handling code fences."""
    text = (raw or "").strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.I)
    if fence:
        try:
            return json.loads(fence.group(1).strip())
        except json.JSONDecodeError:
            pass
    brace = re.search(r"\{[\s\S]*\}\s*$", text)
    if brace:
        try:
            return json.loads(brace.group(0))
        except json.JSONDecodeError:
            pass
    return {}


def _normalize_memory_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize and validate memory items from LLM output."""
    raw = payload.get("memories")
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw[:_MAX_MEMORIES]:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        content = str(item.get("content") or "").strip()
        if not key or not content:
            continue
        key = key[:_MAX_KEY_LEN]
        content = content[:_MAX_CONTENT_LEN]
        try:
            importance = max(0, min(10, int(item.get("importance", 0))))
        except (TypeError, ValueError):
            importance = 0
        out.append({"key": key, "content": content, "importance": importance})
    return out


async def maybe_ingest_post_turn_memory(
    db: AsyncSession,
    user: User,
    *,
    user_message: str,
    assistant_message: str,
    run_id: int | None = None,
    extracted_items: list[dict[str, Any]] | None = None,
) -> PostTurnMemoryResult:
    """Extract and upsert memories from the last exchange using a single LLM pass.

    When ``run_id`` is set, emits post-turn trace events for observability.
    Never raises.
    """
    from app.services.agent_runtime_config_service import resolve_for_user
    from app.services.agent_trace import (
        EV_POST_TURN_COMPLETED,
        EV_POST_TURN_SKIPPED,
        EV_POST_TURN_STARTED,
        emit_trace_event,
    )
    from app.services.user_ai_settings_service import UserAISettingsService as UAISettingsService

    rt = await resolve_for_user(db, user)
    if not rt.agent_memory_post_turn_enabled:
        await _emit_trace_safe(db, run_id, EV_POST_TURN_SKIPPED, {"reason": "disabled", "upserts": 0})
        return PostTurnMemoryResult(skipped=True, reason="disabled", upserts=0)

    u = (user_message or "").strip()
    a = (assistant_message or "").strip()
    if not a:
        await _emit_trace_safe(db, run_id, EV_POST_TURN_SKIPPED, {"reason": "empty_assistant", "upserts": 0})
        return PostTurnMemoryResult(skipped=True, reason="empty_assistant", upserts=0)

    # Heuristic quick-skip for trivial exchanges
    if not heuristic_wants_post_turn_extraction(u, a):
        await _emit_trace_safe(db, run_id, EV_POST_TURN_SKIPPED, {"reason": "heuristic_skip", "upserts": 0})
        return PostTurnMemoryResult(skipped=True, reason="heuristic_skip", upserts=0)

    settings_row = await UAISettingsService.get_or_create(db, user)
    if getattr(settings_row, "agent_processing_paused", False) or settings_row.ai_disabled:
        await _emit_trace_safe(db, run_id, EV_POST_TURN_SKIPPED, {"reason": "ai_paused", "upserts": 0})
        return PostTurnMemoryResult(skipped=True, reason="ai_paused", upserts=0)

    from app.services.user_ai_settings_service import UserAISettingsService
    api_key = await UserAISettingsService.get_api_key(db, user)
    from app.services.ai_providers import provider_kind_requires_api_key
    if provider_kind_requires_api_key(settings_row.provider_kind) and not api_key:
        await _emit_trace_safe(db, run_id, EV_POST_TURN_SKIPPED, {"reason": "no_api_key", "upserts": 0})
        return PostTurnMemoryResult(skipped=True, reason="no_api_key", upserts=0)

    await _emit_trace_safe(db, run_id, EV_POST_TURN_STARTED, {
        "user_message_chars": len(u),
        "assistant_message_chars": len(a),
    })

    # Single LLM call for extraction
    items = await _run_single_extraction(db, user, settings_row, api_key, u, a)

    if extracted_items:
        items = extracted_items

    if not items:
        logger.info("post_turn_memory: no items user_id=%s reason=empty_extraction", user.id)
        await _emit_trace_safe(db, run_id, EV_POST_TURN_SKIPPED, {"reason": "empty_extraction", "upserts": 0})
        return PostTurnMemoryResult(skipped=True, reason="empty_extraction", upserts=0)

    upserts = 0
    for it in items:
        try:
            await AgentMemoryService.upsert(
                db,
                user,
                key=it["key"],
                content=it["content"],
                importance=int(it.get("importance") or 0),
            )
            upserts += 1
        except Exception:
            logger.exception("post_turn_memory: upsert failed user_id=%s key=%s", user.id, it.get("key"))

    logger.info("post_turn_memory: done user_id=%s upserts=%s", user.id, upserts)
    await _emit_trace_safe(db, run_id, EV_POST_TURN_COMPLETED, {"reason": "ok", "upserts": upserts})

    if upserts > 0:
        try:
            from app.services.agent_user_context import maybe_refresh_after_post_turn
            await maybe_refresh_after_post_turn(db, user)
        except Exception:
            logger.exception("post_turn: user context refresh failed user_id=%s", user.id)

    stored = tuple(it for it in items[:upserts]) if upserts else ()
    return PostTurnMemoryResult(skipped=False, reason="ok", upserts=upserts, stored_keys=tuple(s["key"] for s in stored), stored_items=stored)


async def _run_single_extraction(db, user, settings_row, api_key, user_message, assistant_message):
    """Single LLM call to extract memories."""
    u = user_message or "(empty)"
    ach = assistant_message or "(empty)"
    user_prompt = f"Extract durable memories from this single exchange.\n\nUSER:\n{u}\n\nASSISTANT:\n{ach}\n\nIf there is no durable fact, return {{\"memories\":[]}}. If the user assigns or confirms the assistant's name, include agent.identity.* rows."

    try:
        raw = await LLMClient.chat_completion(
            api_key,
            settings_row,
            messages=[
                {"role": "system", "content": _SIMPLE_EXTRACTION_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            response_format_json=True,
        )
    except Exception:
        logger.exception("post_turn_memory: LLM extraction failed user_id=%s", user.id)
        return []

    payload = _parse_json_object(raw)
    return _normalize_memory_items(payload)


async def _emit_trace_safe(db, run_id, event_type, payload):
    """Emit trace event if tracing is enabled and run_id is set."""
    if run_id is None:
        return
    try:
        from app.models.agent_run import AgentRun
        from app.services.agent_trace import tracing_enabled

        if not tracing_enabled():
            return

        row = await db.get(AgentRun, run_id)
        if not row or not row.root_trace_id:
            return
        from app.services.agent_trace import emit_trace_event
        await emit_trace_event(
            db,
            run_id=run_id,
            event_type=event_type,
            trace_id=row.root_trace_id,
            payload={"schema": "agent_trace.v1", **payload},
        )
        await db.commit()
    except Exception:
        pass
