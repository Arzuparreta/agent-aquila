"""Multi-judge memory committee: propose → filter/judge, replacing keyword heuristics for agentic capture."""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.services.agent_rubric import ImportanceRubric, load_rubric, rubric_prompt_chunk, save_rubric
from app.services.llm_client import LLMClient
from app.services.user_ai_settings_service import UserAISettingsService
from app.services.user_time_context import build_datetime_context_section, normalize_time_format

logger = logging.getLogger(__name__)

_MAX_KEY_LEN = 200
_MAX_CONTENT_LEN = 8000
_MAX_MEMORIES = 12

_PROPOSER_SYSTEM = """You are the PROPOSER in a personal-assistant memory committee.
Return ONLY valid JSON: {{"proposals":[{{"key":"...","content":"...","importance":0,"signals":{{"user_preference":0.0,"correction":0.0,"task_outcome":0.0,"repetition":0.0,"identity":0.0,"ephemeral":0.0}}}},...]}}

Rules:
- Propose durable, stable facts that will matter in future sessions (identity, preferences, standing decisions, user-specific conventions, recurring workflows).
- Use dot-separated keys: user.profile.*, memory.durable.*, agent.identity.*, memory.daily.YYYY-MM-DD, prefs.*.
- Do not propose memory.durable.* (or prefs.*) for transient tool outcomes (e.g. one Gmail search returned no rows, query strings from a single attempt) unless the user asked to remember that — use high ephemeral signal or omit; dated-only noise may use memory.daily.* if truly useful.
- Do not propose prefs.* for generic assistant playbooks the user never stated (default procedures belong in system/workspace rules, not USER memory).
- When unsure whether a user-specific fact could help later, propose it anyway — bias toward capture; judges and downstream cleanup can trim noise.
- importance 0-10 (initial estimate; judge may change).
- signals are soft scores in [0,1] for the rubric dimensions; ephemeral should be high for throwaway/one-off details.
- If nothing is worth persisting, return {{"proposals":[]}}.
- One main fact per proposal; do not duplicate the same fact with different keys.

Context:
{rubric}
"""

_JUDGE_SYSTEM = """You are the JUDGE in a personal-assistant memory committee.
You receive PROPOSALS (JSON) about what to store in long-term memory from the last user/assistant turn.

Return ONLY valid JSON: {{"approved":[{{"key":"...","content":"...","importance":0}}], "dropped":[]}}

Rules:
- Approve only entries that are truly durable; drop trivia, one-off chit-chat, and raw dumps.
- Drop (or downgrade to daily-only) proposals that are only transient API/tool diagnostics or empty-search logs unless the user asked to remember them; drop prefs.* that restate generic procedures the user never requested.
- Merge duplicates; fix keys to be canonical; adjust importance 0-10. Prefer fewer, higher-signal entries.
- When choosing between dropping a borderline user-specific fact and keeping it, prefer **approve** — noise is acceptable.
- Approve agent.identity.* when names are assigned or confirmed.
- If all proposals are low-value, return {{"approved":[], "dropped":[{{"key":"*","reason":"..."}}]}}.
- "dropped" can include objects with "key" and "reason" strings.

Rubric and policy:
{rubric}

Current time context (for dated keys):
{clock}
"""

_RUBIC_ADAPTER_SYSTEM = """You are RUBRIC_ADAPTER. Update a JSON rubric to better fit this user's observed memory needs.
Input: current_rubric JSON, a short note about the last turn outcome.
Return ONLY valid JSON: the full updated rubric object with the same schema: version, w_*, base_bias, user_conditioned_notes (string array, max 30 short items), last_adapted_at (ISO-8601 UTC), total_adaptation_steps.
Keep weights in reasonable ranges; small deltas per step. Preserve useful user_conditioned_notes; append 0-2 new distilled notes if the turn reveals new stable themes."""


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


def _normalize_approved(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("approved")
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
            imp = max(0, min(10, int(item.get("importance", 0))))
        except (TypeError, ValueError):
            imp = 0
        out.append({"key": key, "content": content, "importance": imp})
    return out


def adaptive_trivial_skip(user_message: str, assistant_message: str) -> bool:
    """Skip expensive committee only for extremely short, low-signal exchanges (not keyword-based)."""
    u = (user_message or "").strip()
    a = (assistant_message or "").strip()
    if len(u) + len(a) > 100:
        return False
    if not u and not a:
        return True
    # "hi" / "hello" / "hola" only style turns
    short_lo = (u + " " + a).lower()
    if len(short_lo) > 60:
        return False
    words = re.sub(r"[^\w\s]", " ", short_lo).split()
    if len(words) > 5:
        return False
    greet = re.compile(r"^(h(i|ey|ola)|hello|buen(os|as)|buenas|sup|ok|yes|s[ií])[\s!?.]*$", re.I)
    if u and a and greet.match(u) and greet.match(a):
        return True
    return False


async def run_committee_memory_extraction(
    db: AsyncSession,
    user: User,
    *,
    user_message: str,
    assistant_message: str,
) -> list[dict[str, Any]]:
    """Run proposer + judge. Returns list of {key, content, importance} (possibly empty)."""
    settings_row = await UserAISettingsService.get_or_create(db, user)
    api_key = await UserAISettingsService.get_api_key(db, user)
    if not api_key:
        return []

    rubric = load_rubric(user)
    rchunk = rubric_prompt_chunk(rubric)
    clock = build_datetime_context_section(
        user_timezone=None,
        time_format=normalize_time_format("auto"),
    )
    u = user_message or "(empty)"
    ach = assistant_message or "(empty)"
    user_block = (
        "Extract and propose durable memory from this single exchange only.\n\n"
        f"USER:\n{u}\n\nASSISTANT:\n{ach}\n"
    )

    try:
        raw_p = await LLMClient.chat_completion(
            api_key,
            settings_row,
            messages=[
                {"role": "system", "content": _PROPOSER_SYSTEM.format(rubric=rchunk)},
                {"role": "user", "content": user_block},
            ],
            temperature=0.2,
            response_format_json=True,
        )
    except Exception:
        logger.exception("committee: proposer failed user_id=%s", user.id)
        return []
    pro_payload = _parse_json_object(raw_p)
    proposals = pro_payload.get("proposals")
    if not isinstance(proposals, list) or not proposals:
        return []

    try:
        raw_j = await LLMClient.chat_completion(
            api_key,
            settings_row,
            messages=[
                {
                    "role": "system",
                    "content": _JUDGE_SYSTEM.format(
                        rubric=rchunk,
                        clock=clock,
                    ),
                },
                {
                    "role": "user",
                    "content": f"PROPOSALS_JSON:\n{json.dumps(pro_payload, ensure_ascii=False)[:24_000]}",
                },
            ],
            temperature=0.1,
            response_format_json=True,
        )
    except Exception:
        logger.exception("committee: judge failed user_id=%s", user.id)
        return []
    judge_payload = _parse_json_object(raw_j)
    return _normalize_approved(judge_payload)


async def maybe_adapt_rubric_after_turn(
    db: AsyncSession,
    user: User,
    *,
    approved_count: int,
    every_n_empty_turns: int = 10,
) -> None:
    """Periodically nudge the rubric from outcomes (lightweight, online). Best-effort; never raises."""
    try:
        rubric = load_rubric(user)
        rubric.total_adaptation_steps = int(rubric.total_adaptation_steps) + 1
        should_call_llm = approved_count > 0 or (
            every_n_empty_turns > 0 and rubric.total_adaptation_steps % every_n_empty_turns == 0
        )
        if not should_call_llm:
            save_rubric(user, rubric)
            return
        settings_row = await UserAISettingsService.get_or_create(db, user)
        api_key = await UserAISettingsService.get_api_key(db, user)
        if not api_key:
            save_rubric(user, rubric)
            return
        note = f"last_turn_approved={approved_count}"
        try:
            raw = await LLMClient.chat_completion(
                api_key,
                settings_row,
                messages=[
                    {"role": "system", "content": _RUBIC_ADAPTER_SYSTEM},
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "current_rubric": json.loads(rubric.to_json()),
                                "outcome": note,
                            }
                        ),
                    },
                ],
                temperature=0.0,
                response_format_json=True,
            )
        except Exception:
            save_rubric(user, rubric)
            return
        data = _parse_json_object(raw)
        if not data:
            save_rubric(user, rubric)
            return
        updated = ImportanceRubric.from_dict(data)
        updated.last_adapted_at = datetime.now(UTC).isoformat()
        save_rubric(user, updated)
    except Exception:
        logger.exception("maybe_adapt_rubric failed user_id=%s", user.id)
