from __future__ import annotations

import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.services.ai_providers import provider_kind_requires_api_key
from app.services.llm_client import LLMClient, parse_json_object
from app.services.user_ai_settings_service import UserAISettingsService

DEAL_KEYWORDS_PATTERN = re.compile(r"\b(concert|booking|show)\b", re.IGNORECASE)


class TriageService:
    @staticmethod
    def _regex_decision(subject: str) -> dict[str, Any]:
        match = bool(DEAL_KEYWORDS_PATTERN.search(subject))
        return {
            "intent": "booking_inquiry" if match else "other",
            "create_deal": match,
            "suggested_status": "new",
            "confidence": 0.5 if match else 0.2,
            "source": "regex",
        }

    @staticmethod
    async def evaluate(db: AsyncSession, user_id: int | None, subject: str, body: str) -> dict[str, Any]:
        fallback = TriageService._regex_decision(subject)
        if not user_id:
            return fallback
        user = await db.get(User, user_id)
        if not user:
            return fallback
        settings_row = await UserAISettingsService.get_or_create(db, user)
        if settings_row.ai_disabled:
            return fallback
        api_key = await UserAISettingsService.get_api_key(db, user)
        if provider_kind_requires_api_key(settings_row.provider_kind) and not api_key:
            return fallback
        model = settings_row.classify_model or settings_row.chat_model
        system = (
            "You classify inbound music-business email for an artist manager. "
            "Return ONLY valid JSON with keys: intent (string), create_deal (boolean), "
            "suggested_status (one of: new, contacted, negotiating, won, lost), "
            "confidence (number 0-1)."
        )
        user_msg = f"Subject: {subject}\n\nBody:\n{body[:4000]}"
        try:
            raw = await LLMClient.chat_completion(
                api_key or "",
                settings_row,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user_msg}],
                model=model,
                temperature=0.1,
            )
            parsed = parse_json_object(raw) or {}
            create_deal = bool(parsed.get("create_deal"))
            if not create_deal and TriageService._regex_decision(subject)["create_deal"]:
                create_deal = True
            return {
                "intent": str(parsed.get("intent", fallback["intent"])),
                "create_deal": create_deal,
                "suggested_status": str(parsed.get("suggested_status", "new")),
                "confidence": float(parsed.get("confidence", 0.5)),
                "source": "llm",
                "raw_preview": raw[:500],
            }
        except Exception:
            return fallback
