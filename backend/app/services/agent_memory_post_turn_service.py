"""Post-turn memory: legacy heuristic pass **or** multi-judge committee + rubric adaptation.

- ``heuristic`` — optional keyword gate + single JSON extraction (legacy / tests).
- ``always`` / ``committee`` — proposer + judge on each completed turn (no trivial skip).
- ``adaptive`` — same committee, but skips *very* short greeting-only turns.

Durable storage writes go through :func:`AgentMemoryService.upsert` (canonical markdown + DB).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.models.user_ai_settings import UserAISettings

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_run import AgentRun
from app.models.user import User
from app.services.agent_memory_committee import (
    adaptive_trivial_skip,
    maybe_adapt_rubric_after_turn,
    run_committee_memory_extraction,
)
from app.services.agent_memory_service import AgentMemoryService
from app.services.agent_trace import (
    EV_POST_TURN_COMPLETED,
    EV_POST_TURN_SKIPPED,
    EV_POST_TURN_STARTED,
    emit_trace_event,
)
from app.services.agent_runtime_config_service import resolve_for_user
from app.services.ai_providers import provider_kind_requires_api_key
from app.services.llm_client import LLMClient
from app.services.user_ai_settings_service import UserAISettingsService

logger = logging.getLogger(__name__)

_MAX_KEY_LEN = 200
_MAX_CONTENT_LEN = 8000
_MAX_MEMORIES = 12

# User text: remember / name / preference signals (EN + ES).
_USER_MEMORY_HINT = re.compile(
    r"(?:^|\b)(?:remember|recuerda|recuerde|recuerdas|don'?t\s+forget|no\s+olvides|"
    r"prefer|prefiero|prefieres|preference|preferencia|"
    r"my\s+name\s+is|me\s+llamo|ll[aá]mame|ll[aá]mate|your\s+name\s+is|tu\s+nombre|"
    r"te\s+llamas|te\s+llamar[áa]s|te\s+llamaras\b|how\s+should\s+i\s+call|c[oó]mo\s+te\s+llamo|"
    r"a\s+partir\s+de\s+ahora|desde\s+ahora\s+te\s+llam|"
    r"\byou\s+are\s+|\beres\b|you'?re\s+the\s+|"
    r"call\s+me|call\s+yourself|"
    r"guarda\s+en\s+memoria|guardar\s+en\s+memoria|"
    r"i\s+want\s+you\s+to\s+remember|quiero\s+que\s+recuerdes)(?:\b|$)",
    re.IGNORECASE | re.MULTILINE,
)

# User confirms a prior naming / identity assignment without repeating "agent" keywords
# (e.g. "Vale pues ese es tu nombre!").
_NAME_ASSIGNMENT_CONFIRM = re.compile(
    r"(?:^|\b)(?:"
    r"ese\s+es\s+tu\s+nombre|ese\s+es\s+el\s+nombre|as[ií]\s+te\s+llamo|"
    r"qu[eé]date\s+con\s+ese|quedamos\s+en\s+eso|vale\s+.*\bnombre\b|"
    r"that'?s\s+your\s+name|confirmed|deal\b"
    r")(?:\b|$)",
    re.IGNORECASE | re.MULTILINE,
)

# Assistant text: claimed persistence (often without a real tool call).
_ASSISTANT_MEMORY_PROMISE = re.compile(
    r"(?:^|\b)(?:guardo\s+en\s+memoria|lo\s+guardo|guardar[eé]\s+en\s+memoria|"
    r"i['’]?ll\s+save|i\s+will\s+save|saved\s+to\s+memory|"
    r"lo\s+memorizo|memorizar[eé]|"
    r"lo\s+recordar[eé]|recordar[eé]\s+para|"
    r"i['’]?ll\s+remember|remember\s+for|"
    r"a\s+partir\s+de\s+ahora\s+me\s+llamar|me\s+llamar[ée]|me\s+llamare)(?:\b|$)",
    re.IGNORECASE | re.MULTILINE,
)

_EXTRACTION_SYSTEM = """You extract durable facts for a personal assistant's persistent key-value memory.
Return ONLY a JSON object with this exact shape:
{"memories":[{"key":"string","content":"string","importance":0}]}

Rules:
- Use "memories": [] only when the exchange has no durable fact (pure small talk, no preferences, no naming).
- Keys: lowercase, dot-separated segments, max 200 characters. Use prefixes such as
  user.profile.*, agent.identity.*, memory.durable.*, prefs.* — never raw PII buckets.
- Content: short plain text; one main fact per entry.
- Skip memory.durable.* (and prefs.*) for one-off tool outcomes that will go stale (e.g. a single empty Gmail search and its query list) unless the user asked to remember; skip prefs.* for generic how-to lines the user never stated. If torn about a user-specific fact, include it — noise is tolerable.
- importance: integer 0-10 (use 8-10 when the user explicitly asked to remember, or for stable identity).
- Do NOT store passwords, API keys, tokens, or full third-party message bodies.
- Do NOT assert that "scheduled" or "automatic" or "background" help is impossible — the stack supports **heartbeat** (scheduled agent turns) when configured; if the user only stated a wish (e.g. daily digest), store the wish without a false limitation.
- **Identity (required when applicable):** If the user assigns, confirms, or agrees on what the assistant
  should be called, or the assistant states or accepts a display name in the reply (e.g. "Agente Áquila",
  "Agent Aquila"), you MUST emit at least one row under agent.identity.* (e.g. agent.identity.display_name_es,
  agent.identity.display_name_en, or agent.identity.names with both in content). Use importance 8-10.
- If the user assigns the assistant display names in Spanish and/or English, use keys like
  agent.identity.display_name_es and agent.identity.display_name_en, or a single agent.identity.names
  with both names in the content.
- Do not duplicate the same fact under many keys; prefer one canonical key per fact."""

_EXTRACTION_SYSTEM_RETRY = """You extract durable facts. A previous pass returned an empty list; fix it if the exchange clearly establishes identity or preferences.

Return ONLY JSON: {"memories":[{"key":"string","content":"string","importance":0}]}

If the USER or ASSISTANT assigns, confirms, or states the assistant's name (including nicknames like
"Agente Áquila"), you MUST include at least one agent.identity.* row with importance 8-10 unless there is
literally no name or preference in the text. Otherwise return {"memories":[]}. Do not invent claims that
background or scheduled help is impossible — omit that."""


@dataclass(frozen=True)
class PostTurnMemoryResult:
    skipped: bool
    reason: str
    upserts: int
    stored_keys: tuple[str, ...] = ()
    stored_items: tuple[dict[str, Any], ...] = ()


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
    if len(u) <= 600 and _NAME_ASSIGNMENT_CONFIRM.search(u):
        return True
    # Short identity-style turns (e.g. "Eres Agente Áquila en español..." or "te llamarás X")
    if len(u) <= 600 and (
        re.search(r"\b(agente|agent|águila|aquila|assistant|asistente)\b", u, re.I)
        and re.search(
            r"\b(eres|you are|llam|name|nombre|call|llamar[áa]s|llamaras|llamarte)\b",
            u,
            re.I,
        )
    ):
        return True
    return False


async def _emit_post_turn_trace(
    db: AsyncSession,
    run_id: int | None,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    if run_id is None:
        return
    row = await db.get(AgentRun, run_id)
    if not row or not row.root_trace_id:
        return
    await emit_trace_event(
        db,
        run_id=run_id,
        event_type=event_type,
        trace_id=row.root_trace_id,
        payload={"schema": "agent_trace.v1", **payload},
    )
    await db.commit()


def _parse_json_object(raw: str) -> dict[str, Any]:
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
        imp = item.get("importance", 0)
        try:
            importance = max(0, min(10, int(imp)))
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
    """Optionally extract and upsert memories from the last exchange. Never raises.

    When ``run_id`` is set, emits ``post_turn.*`` rows into ``agent_trace_events``
    (same trace id as the agent run) for observability.
    """
    rt = await resolve_for_user(db, user)
    if not rt.agent_memory_post_turn_enabled:
        await _emit_post_turn_trace(
            db,
            run_id,
            EV_POST_TURN_SKIPPED,
            {"reason": "disabled", "mode": None, "upserts": 0},
        )
        return PostTurnMemoryResult(skipped=True, reason="disabled", upserts=0)

    mode = (rt.agent_memory_post_turn_mode or "committee").strip().lower()
    if mode not in ("heuristic", "always", "committee", "adaptive"):
        mode = "committee"

    u = (user_message or "").strip()
    a = (assistant_message or "").strip()
    if not a:
        await _emit_post_turn_trace(
            db,
            run_id,
            EV_POST_TURN_SKIPPED,
            {"reason": "empty_assistant", "mode": mode, "upserts": 0},
        )
        return PostTurnMemoryResult(skipped=True, reason="empty_assistant", upserts=0)

    if mode == "heuristic" and not heuristic_wants_post_turn_extraction(u, a):
        await _emit_post_turn_trace(
            db,
            run_id,
            EV_POST_TURN_SKIPPED,
            {"reason": "heuristic_skip", "mode": mode, "upserts": 0},
        )
        return PostTurnMemoryResult(skipped=True, reason="heuristic_skip", upserts=0)

    if mode == "adaptive" and adaptive_trivial_skip(u, a):
        await _emit_post_turn_trace(
            db,
            run_id,
            EV_POST_TURN_SKIPPED,
            {"reason": "adaptive_trivial_skip", "mode": mode, "upserts": 0},
        )
        return PostTurnMemoryResult(skipped=True, reason="adaptive_trivial_skip", upserts=0)

    settings_row = await UserAISettingsService.get_or_create(db, user)
    if getattr(settings_row, "agent_processing_paused", False) or settings_row.ai_disabled:
        await _emit_post_turn_trace(
            db,
            run_id,
            EV_POST_TURN_SKIPPED,
            {"reason": "ai_paused_or_disabled", "mode": mode, "upserts": 0},
        )
        return PostTurnMemoryResult(skipped=True, reason="ai_paused_or_disabled", upserts=0)

    api_key = await UserAISettingsService.get_api_key(db, user)
    if provider_kind_requires_api_key(settings_row.provider_kind) and not api_key:
        await _emit_post_turn_trace(
            db,
            run_id,
            EV_POST_TURN_SKIPPED,
            {"reason": "no_api_key", "mode": mode, "upserts": 0},
        )
        return PostTurnMemoryResult(skipped=True, reason="no_api_key", upserts=0)

    await _emit_post_turn_trace(
        db,
        run_id,
        EV_POST_TURN_STARTED,
        {"mode": mode, "user_message_chars": len(u), "assistant_message_chars": len(a)},
    )

    if mode == "heuristic":
        items = await _run_legacy_extraction(
            user,
            settings_row=settings_row,
            api_key=api_key,
            user_message=u,
            assistant_message=a,
        )
    else:
        items = await run_committee_memory_extraction(
            db,
            user,
            user_message=u,
            assistant_message=a,
        )

    if not items:
        items = extracted_items or []

    if not items:
        logger.info(
            "post_turn_memory: no items user_id=%s mode=%s reason=empty_extraction",
            user.id,
            mode,
        )
        await _emit_post_turn_trace(
            db,
            run_id,
            EV_POST_TURN_SKIPPED,
            {"reason": "empty_extraction", "mode": mode, "upserts": 0},
        )
        if mode != "heuristic":
            await maybe_adapt_rubric_after_turn(db, user, approved_count=0)
        return PostTurnMemoryResult(
            skipped=True,
            reason="empty_extraction",
            upserts=0,
            stored_keys=(),
            stored_items=(),
        )

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
            logger.exception(
                "post_turn_memory: upsert failed user_id=%s key=%s",
                user.id,
                it.get("key"),
            )

    if mode != "heuristic":
        await maybe_adapt_rubric_after_turn(db, user, approved_count=upserts)

    logger.info(
        "post_turn_memory: done user_id=%s mode=%s upserts=%s",
        user.id,
        mode,
        upserts,
    )
    await _emit_post_turn_trace(
        db,
        run_id,
        EV_POST_TURN_COMPLETED,
        {
            "reason": "ok",
            "mode": mode,
            "upserts": upserts,
            "stored_keys": [it["key"] for it in items[:upserts]] if upserts else [],
        },
    )
    if upserts > 0:
        try:
            from app.services.agent_user_context import maybe_refresh_after_post_turn

            await maybe_refresh_after_post_turn(db, user)
        except Exception:  # noqa: BLE001
            logger.exception("post_turn: user context snapshot refresh failed user_id=%s", user.id)
    stored = tuple(it for it in items[:upserts]) if upserts else ()
    return PostTurnMemoryResult(
        skipped=False,
        reason="ok",
        upserts=upserts,
        stored_keys=tuple(it["key"] for it in stored),
        stored_items=stored,
    )


async def _run_legacy_extraction(
    user: User,
    *,
    settings_row: "UserAISettings",
    api_key: str,
    user_message: str,
    assistant_message: str,
) -> list[dict[str, Any]]:
    u = (user_message or "").strip()
    a = (assistant_message or "").strip()
    user_block = u if u else "(empty)"
    assistant_block = a if a else "(empty)"
    user_prompt = (
        "Extract durable memories from this single exchange only.\n\n"
        f"USER:\n{user_block}\n\nASSISTANT:\n{assistant_block}\n\n"
        'If the exchange only contains greetings or questions with no durable fact, return {"memories":[]}. '
        "If identity or preferences are established, include them in memories."
    )

    try:
        raw = await LLMClient.chat_completion(
            api_key,
            settings_row,
            messages=[
                {"role": "system", "content": _EXTRACTION_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            response_format_json=True,
        )
    except Exception:
        logger.exception("post_turn_memory: LLM extraction failed user_id=%s", user.id)
        return []

    payload = _parse_json_object(raw)
    items = _normalize_memory_items(payload)
    if not items and heuristic_wants_post_turn_extraction(u, a):
        try:
            raw_retry = await LLMClient.chat_completion(
                api_key,
                settings_row,
                messages=[
                    {"role": "system", "content": _EXTRACTION_SYSTEM_RETRY},
                    {
                        "role": "user",
                        "content": user_prompt
                        + "\n\n[Retry: previous extraction returned []. "
                        "If this dialogue names or confirms the assistant, emit agent.identity.* rows.]",
                    },
                ],
                temperature=0.0,
                response_format_json=True,
            )
        except Exception:
            logger.exception("post_turn_memory: LLM retry failed user_id=%s", user.id)
            return []
        payload = _parse_json_object(raw_retry)
        items = _normalize_memory_items(payload)
    return items
