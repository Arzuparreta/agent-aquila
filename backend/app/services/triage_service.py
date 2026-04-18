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
    async def classify_relevance(
        db: AsyncSession,
        user_id: int | None,
        *,
        subject: str,
        body: str,
        sender_email: str = "",
    ) -> dict[str, Any] | None:
        """Cheap LLM call that decides whether an inbound email deserves a
        proactive chat thread + agent run.

        Returns a dict ``{category, confidence, reason}`` or ``None`` when no
        LLM is available (caller falls back to the heuristic verdict).

        ``category`` ∈ ``{actionable, informational, noise}``. The classifier is
        biased toward ``informational`` to avoid surprising the artist with
        spurious agent runs — only clearly user-relevant mail should be
        ``actionable``.
        """
        if not user_id:
            return None
        user = await db.get(User, user_id)
        if not user:
            return None
        settings_row = await UserAISettingsService.get_or_create(db, user)
        if settings_row.ai_disabled:
            return None
        api_key = await UserAISettingsService.get_api_key(db, user)
        if provider_kind_requires_api_key(settings_row.provider_kind) and not api_key:
            return None
        model = settings_row.classify_model or settings_row.chat_model
        system = (
            "You triage inbound email for a busy professional. Decide whether "
            "the message warrants a real-time AI assistant conversation. "
            "Respond ONLY with valid JSON: "
            '{"category":"actionable|informational|noise",'
            '"confidence":0.0,"reason":"short reason"}. '
            "Use 'actionable' only when the user almost certainly needs to "
            "act, reply, or be notified now (booking, contract, meeting "
            "request, urgent question, payment issue). Use 'informational' "
            "for context-worthy but non-urgent updates. Use 'noise' for "
            "newsletters, marketing, automated notifications, receipts and "
            "verification codes. When uncertain, prefer 'informational'."
        )
        user_msg = (
            f"Sender: {sender_email}\n"
            f"Subject: {subject}\n\n"
            f"Body:\n{(body or '')[:3500]}"
        )
        try:
            raw = await LLMClient.chat_completion(
                api_key or "",
                settings_row,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user_msg}],
                model=model,
                temperature=0.0,
            )
            parsed = parse_json_object(raw) or {}
            cat = str(parsed.get("category") or "").strip().lower()
            if cat not in ("actionable", "informational", "noise"):
                return None
            try:
                confidence = float(parsed.get("confidence", 0.5))
            except (TypeError, ValueError):
                confidence = 0.5
            reason = str(parsed.get("reason") or "")[:255]
            return {"category": cat, "confidence": confidence, "reason": reason}
        except Exception:
            return None

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
