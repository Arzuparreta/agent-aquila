"""Hybrid relevance filter for inbound emails and calendar events.

Goal: stop spawning a chat thread + agent run + push for every ingested item.
Newsletters, automated notifications and irrelevant calendar imports flood
``Conversaciones`` if every mirror sync triggers the proactive layer
unconditionally.

This service runs after the row is persisted (so RAG / search keeps everything)
and decides whether the proactive layer should fire:

    Stage A — heuristics (free, fast, no LLM call):
        Header signals (List-Unsubscribe, Precedence, Auto-Submitted, …),
        sender local-part / domain patterns, subject regexes, calendar
        organizer / declined / birthday rules.

    Stage B — cheap LLM triage (only when Stage A returns ``informational``):
        Reuses the user's ``classify_model`` via ``TriageService.classify_relevance``
        to escalate genuinely useful informational items to ``actionable``.
        Failures degrade to ``informational`` (never to ``actionable``).

    Known-contact promotion (overrides Stage A noise verdicts):
        If the email's contact has any Deal, was created manually (not by the
        Gmail/Graph mirror), or the user has already replied to that address,
        the verdict is forced to ``actionable``. A known partner sending a
        "newsletter"-shaped message still matters.

The verdict is persisted on the row (``triage_category``/``reason``/``source``/
``at``) so the artist can review what we silenced and override it via the
``promote`` / ``suppress`` endpoints.

Modes (``settings.inbound_filter_mode``):
    - ``off``: every item is ``actionable`` (legacy behaviour).
    - ``permissive``: only obvious noise is suppressed; uncertain → actionable.
    - ``balanced`` (default): two-stage filter as described above.
    - ``strict``: heuristic noise + LLM ``noise|informational`` both silence.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Iterable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.audit_log import AuditLog
from app.models.contact import Contact
from app.models.deal import Deal
from app.models.email import Email
from app.models.event import Event
from app.models.user import User

logger = logging.getLogger(__name__)


CATEGORY_ACTIONABLE = "actionable"
CATEGORY_INFORMATIONAL = "informational"
CATEGORY_NOISE = "noise"
CATEGORY_UNKNOWN = "unknown"

SOURCE_HEURISTIC = "heuristic"
SOURCE_LLM = "llm"
SOURCE_KNOWN_CONTACT = "known_contact"
SOURCE_MANUAL = "manual"

VALID_CATEGORIES = (
    CATEGORY_ACTIONABLE,
    CATEGORY_INFORMATIONAL,
    CATEGORY_NOISE,
    CATEGORY_UNKNOWN,
)
VALID_SOURCES = (SOURCE_HEURISTIC, SOURCE_LLM, SOURCE_KNOWN_CONTACT, SOURCE_MANUAL)


@dataclass(frozen=True)
class Verdict:
    category: str
    reason: str
    source: str

    def with_override(self, *, category: str, reason: str, source: str) -> "Verdict":
        return Verdict(category=category, reason=reason, source=source)


# ---------------------------------------------------------------------------
# Heuristic patterns (kept simple and conservative; tested in isolation).
# ---------------------------------------------------------------------------

# Bulk / automated mail header signatures.
_BULK_HEADER_KEYS = (
    "list-unsubscribe",
    "list-id",
    "list-unsubscribe-post",
)
_AUTO_HEADER_KEYS = (
    "auto-submitted",
    "x-auto-response-suppress",
    "x-autoresponse",
    "x-autorespond",
    "feedback-id",
    "x-mailer-version",
)
_PRECEDENCE_NOISE_VALUES = ("bulk", "list", "junk", "auto_reply", "marketing")

# Local part patterns that strongly indicate non-human senders. Anchored at
# the start of the local-part to avoid false positives like ``support-team@``
# being treated as bulk.
_NOISE_LOCAL_RE = re.compile(
    r"^(no[-._]?reply|do[-._]?not[-._]?reply|reply\+|notifications?|alerts?|"
    r"updates?|news(letter)?|digest|info|hello|team|support|billing|receipts?|"
    r"mailer|bounce|return|postmaster|automated|account|service|security)"
    r"([-._+].*)?@",
    re.IGNORECASE,
)

# Subdomain prefixes commonly used by Email Service Providers / marketing.
_NOISE_DOMAIN_PREFIX_RE = re.compile(
    r"^(em|email|mail|mailer|marketing|notify|notifications?|news|newsletter|"
    r"updates?|alerts?|reply|bounce|t|track|click|smtp)\.",
    re.IGNORECASE,
)

# Hard-coded ESP / bulk-mail provider domains seen in the wild.
_NOISE_DOMAIN_SUFFIX = (
    "mailchimp.com",
    "sendgrid.net",
    "sendgrid.com",
    "mailgun.org",
    "mailgun.com",
    "mandrillapp.com",
    "amazonses.com",
    "sparkpostmail.com",
    "postmarkapp.com",
    "constantcontact.com",
    "campaign-archive.com",
    "leetcode.com",
    "em.linkedin.com",
    "el.linkedin.com",
    "e.linkedin.com",
    "em.notion.so",
    "mail.notion.so",
    "github.com",  # github notifications — usually informational
    "stripe.com",
    "intercom-mail.com",
    "intercom-clicks.com",
    "hubspot.com",
    "hsemail.com",
)

# Subject patterns that mark a message as digest / one-off transactional.
_NOISE_SUBJECT_RE = re.compile(
    r"\b("
    r"(weekly|monthly|daily|quarterly)\s+digest|"
    r"(weekly|monthly|daily)\s+(summary|update|recap|newsletter)|"
    r"your\s+(weekly|monthly|daily)\s+\w+|"
    r"unsubscribe|"
    r"verify\s+your\s+email|"
    r"confirm\s+your\s+(email|account)|"
    r"reset\s+your\s+password|"
    r"(otp|verification)\s+code|"
    r"one[-\s]?time\s+(password|code)|"
    r"thanks\s+for\s+(joining|signing\s+up|subscribing)|"
    r"welcome\s+to\s+|"
    r"new\s+(login|sign[-\s]?in)\s+from"
    r")\b",
    re.IGNORECASE,
)

# Subject patterns for booking / actionable music-business mail. When any of
# these match we never silence — the agent should at least look at it.
_ACTIONABLE_SUBJECT_RE = re.compile(
    r"\b(booking|concert|show|gig|tour|festival|venue|management|press|"
    r"interview|invoice|contract|propos(al|ition)|quote|deal|enquiry|inquiry|"
    r"request|payment|refund|cancellation|signed|signature)\b",
    re.IGNORECASE,
)


def _headers_lower(raw: dict | None) -> dict[str, str]:
    """Return a flat ``{lowercased-name: value}`` view across both raw header
    layouts we persist (Gmail nests under ``gmail_headers``).
    """
    if not raw or not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    nested = raw.get("gmail_headers")
    if isinstance(nested, dict):
        for k, v in nested.items():
            if isinstance(k, str):
                out[k.lower()] = str(v) if v is not None else ""
    for k, v in raw.items():
        if k == "gmail_headers":
            continue
        if isinstance(k, str):
            out[k.lower()] = str(v) if v is not None else ""
    return out


def _domain(addr: str | None) -> str:
    if not addr or "@" not in addr:
        return ""
    return addr.rsplit("@", 1)[1].strip().lower()


def _matches_any(value: str, suffixes: Iterable[str]) -> bool:
    return any(value == s or value.endswith("." + s) for s in suffixes)


def _heuristic_email_verdict(email: Email) -> Verdict:
    """Stage A. Pure-function over the row; no DB / network calls.

    Returns a ``Verdict``. Possible categories: ``noise``, ``informational``,
    ``actionable``. Stage B may upgrade ``informational`` to ``actionable``.
    """
    subject = (email.subject or "").strip()
    sender = (email.sender_email or "").lower()
    headers = _headers_lower(email.raw_headers)
    domain = _domain(sender)

    # Strong actionable signal up-front. We still let known-contact promotion
    # override later, but having this here means LLM Stage B is rarely needed
    # for booking/contract mail.
    if subject and _ACTIONABLE_SUBJECT_RE.search(subject):
        return Verdict(CATEGORY_ACTIONABLE, "subject mentions actionable keyword", SOURCE_HEURISTIC)

    # Noise via headers.
    for key in _BULK_HEADER_KEYS:
        if headers.get(key):
            return Verdict(CATEGORY_NOISE, f"bulk header: {key}", SOURCE_HEURISTIC)
    precedence = (headers.get("precedence") or "").strip().lower()
    if precedence in _PRECEDENCE_NOISE_VALUES:
        return Verdict(CATEGORY_NOISE, f"precedence: {precedence}", SOURCE_HEURISTIC)
    auto = (headers.get("auto-submitted") or "").strip().lower()
    if auto and auto != "no":
        return Verdict(CATEGORY_NOISE, f"auto-submitted: {auto}", SOURCE_HEURISTIC)
    for key in _AUTO_HEADER_KEYS:
        if key == "auto-submitted":
            continue
        if headers.get(key):
            return Verdict(CATEGORY_INFORMATIONAL, f"automated header: {key}", SOURCE_HEURISTIC)

    # Noise via sender shape.
    if sender and _NOISE_LOCAL_RE.search(sender):
        return Verdict(CATEGORY_NOISE, "no-reply / bulk local-part", SOURCE_HEURISTIC)
    if domain:
        if _NOISE_DOMAIN_PREFIX_RE.search(domain):
            return Verdict(CATEGORY_INFORMATIONAL, f"marketing subdomain: {domain}", SOURCE_HEURISTIC)
        if _matches_any(domain, _NOISE_DOMAIN_SUFFIX):
            return Verdict(CATEGORY_INFORMATIONAL, f"known ESP/bulk domain: {domain}", SOURCE_HEURISTIC)

    # Noise via subject.
    if subject and _NOISE_SUBJECT_RE.search(subject):
        return Verdict(CATEGORY_NOISE, "subject matches digest/transactional pattern", SOURCE_HEURISTIC)

    # No strong signal either way — let Stage B / known-contact decide.
    return Verdict(CATEGORY_INFORMATIONAL, "no heuristic signal", SOURCE_HEURISTIC)


def heuristic_sender_is_noise(sender_email: str | None, raw_headers: dict | None = None) -> bool:
    """Pre-DB check used to suppress Contact auto-creation for newsletter senders.

    Conservative: only returns True when we are *very* sure (no-reply local
    part, known ESP domain, or strong bulk header). Anything that just smells
    like marketing falls through and a Contact is created as before — the
    proactive filter will still silence it later.
    """
    sender = (sender_email or "").lower()
    if sender and _NOISE_LOCAL_RE.search(sender):
        return True
    domain = _domain(sender)
    if domain and _matches_any(domain, _NOISE_DOMAIN_SUFFIX):
        return True
    headers = _headers_lower(raw_headers)
    for key in _BULK_HEADER_KEYS:
        if headers.get(key):
            return True
    precedence = (headers.get("precedence") or "").strip().lower()
    if precedence in _PRECEDENCE_NOISE_VALUES:
        return True
    auto = (headers.get("auto-submitted") or "").strip().lower()
    if auto and auto != "no":
        return True
    return False


# ---------------------------------------------------------------------------
# Calendar heuristics
# ---------------------------------------------------------------------------

_NOISE_EVENT_SUMMARY_RE = re.compile(
    r"^(birthday|cumplea[ñn]os|out of office|fuera de la oficina|busy|ocupado|"
    r"working location|holiday|vacation|vacaciones|bank holiday|public holiday)\b",
    re.IGNORECASE,
)


def _user_is_event_organizer(user: User, event_payload: dict) -> bool:
    organizer = event_payload.get("organizer")
    if isinstance(organizer, dict):
        addr = (organizer.get("email") or "").lower()
        if not addr:
            inner = organizer.get("emailAddress") or {}
            addr = (inner.get("address") or "").lower() if isinstance(inner, dict) else ""
        if addr and addr == (user.email or "").lower():
            return True
    return False


def _user_response_status(user: User, event: Event) -> str | None:
    user_email = (user.email or "").lower()
    for att in event.attendees or []:
        if not isinstance(att, dict):
            continue
        addr = (att.get("email") or "").lower() or (
            (att.get("emailAddress") or {}).get("address", "").lower()
            if isinstance(att.get("emailAddress"), dict)
            else ""
        )
        if addr and addr == user_email:
            status = att.get("responseStatus") or att.get("status")
            return str(status).lower() if status else None
    return None


def _heuristic_event_verdict(user: User, event: Event, payload: dict | None = None) -> Verdict:
    summary = (event.summary or event.venue_name or "").strip()
    if summary and _NOISE_EVENT_SUMMARY_RE.search(summary):
        return Verdict(CATEGORY_NOISE, "event summary matches noise pattern", SOURCE_HEURISTIC)

    response = _user_response_status(user, event)
    if response == "declined":
        return Verdict(CATEGORY_NOISE, "user declined the invite", SOURCE_HEURISTIC)

    organizer_is_user = _user_is_event_organizer(user, payload or {})
    has_attendees = bool(event.attendees)
    has_description = bool(event.description and event.description.strip())
    linked_to_deal = event.deal_id is not None

    if organizer_is_user or linked_to_deal:
        return Verdict(CATEGORY_ACTIONABLE, "user organizes / linked to deal", SOURCE_HEURISTIC)

    if event.all_day and not has_attendees and not has_description:
        return Verdict(CATEGORY_NOISE, "all-day import without attendees/description", SOURCE_HEURISTIC)

    if not has_attendees and not has_description:
        return Verdict(CATEGORY_INFORMATIONAL, "minimal external event", SOURCE_HEURISTIC)

    return Verdict(CATEGORY_INFORMATIONAL, "external event with context", SOURCE_HEURISTIC)


# ---------------------------------------------------------------------------
# Known-contact promotion
# ---------------------------------------------------------------------------

async def _contact_is_known(
    db: AsyncSession, user: User, contact: Contact | None, sender_email: str | None
) -> tuple[bool, str]:
    """Return (is_known, reason). 'Known' means the user has already engaged
    with this address — making any incoming mail worth surfacing even if it
    looks bulk-shaped (e.g. a partner's monthly recap).
    """
    if not contact and not sender_email:
        return False, ""

    if contact:
        # 1. Linked to an active Deal.
        deal_count_q = await db.execute(
            select(func.count(Deal.id)).where(Deal.contact_id == contact.id)
        )
        if int(deal_count_q.scalar() or 0) > 0:
            return True, "contact has linked deal"

        # 2. Manually created (not auto-ingested from a connector). Audit log
        # ``created`` actions are written by the user-facing routes;
        # ``created_from_*`` actions are written by the mirror services.
        manual_q = await db.execute(
            select(func.count(AuditLog.id)).where(
                AuditLog.entity_type == "contact",
                AuditLog.entity_id == contact.id,
                AuditLog.action == "created",
            )
        )
        if int(manual_q.scalar() or 0) > 0:
            return True, "contact was manually created"

        # 3. User has previously sent a reply to this contact.
        outbound_q = await db.execute(
            select(func.count(Email.id)).where(
                Email.contact_id == contact.id,
                Email.direction == "outbound",
            )
        )
        if int(outbound_q.scalar() or 0) > 0:
            return True, "user previously replied to contact"

    if sender_email:
        # Even with no Contact row, a previous outbound mail to/from the same
        # address counts as engagement (e.g. mail sent from the artist's
        # account before contact upsert ran).
        outbound_q = await db.execute(
            select(func.count(Email.id)).where(
                Email.sender_email == sender_email.lower(),
                Email.direction == "outbound",
            )
        )
        if int(outbound_q.scalar() or 0) > 0:
            return True, "previous outbound exchange with sender address"

    return False, ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class InboundFilterService:
    """Stateless façade. Mirror services and routes call ``classify_*`` and
    must persist the returned ``Verdict`` on the row plus call
    ``apply_verdict_to_email`` / ``apply_verdict_to_event`` for consistency.
    """

    @staticmethod
    def mode() -> str:
        return (settings.inbound_filter_mode or "balanced").lower()

    @staticmethod
    def llm_enabled() -> bool:
        return bool(settings.inbound_filter_llm)

    @staticmethod
    async def classify_email(db: AsyncSession, user: User, email: Email) -> Verdict:
        mode = InboundFilterService.mode()
        if mode == "off":
            return Verdict(CATEGORY_ACTIONABLE, "filter disabled", SOURCE_HEURISTIC)

        # Outbound mail never triggers the proactive layer regardless of mode.
        if (email.direction or "").lower() == "outbound":
            return Verdict(CATEGORY_INFORMATIONAL, "outbound message", SOURCE_HEURISTIC)

        verdict = _heuristic_email_verdict(email)

        # Known-contact promotion can rescue items the heuristics silenced.
        if verdict.category in (CATEGORY_NOISE, CATEGORY_INFORMATIONAL):
            try:
                contact: Contact | None = None
                if email.contact_id:
                    contact = await db.get(Contact, email.contact_id)
                known, why = await _contact_is_known(db, user, contact, email.sender_email)
                if known:
                    return Verdict(CATEGORY_ACTIONABLE, why, SOURCE_KNOWN_CONTACT)
            except Exception:  # noqa: BLE001 — never fail ingest on a triage glitch
                logger.exception("known-contact lookup failed for email %s", getattr(email, "id", None))

        if mode == "permissive":
            # Only obvious noise (heuristic NOISE) is silenced; everything else
            # goes through.
            if verdict.category == CATEGORY_NOISE:
                return verdict
            return Verdict(CATEGORY_ACTIONABLE, "permissive: passing through", verdict.source)

        # balanced / strict: optionally consult the LLM for the grey zone.
        if (
            verdict.category == CATEGORY_INFORMATIONAL
            and InboundFilterService.llm_enabled()
        ):
            try:
                from app.services.triage_service import TriageService

                llm = await TriageService.classify_relevance(
                    db,
                    user.id,
                    subject=email.subject or "",
                    body=email.body or "",
                    sender_email=email.sender_email or "",
                )
                if llm and llm.get("category") in VALID_CATEGORIES:
                    cat = str(llm["category"])
                    reason = str(llm.get("reason") or "llm classification")
                    if mode == "strict" and cat == CATEGORY_INFORMATIONAL:
                        cat = CATEGORY_NOISE
                        reason = f"strict mode: demoted ({reason})"
                    return Verdict(cat, reason[:255], SOURCE_LLM)
            except Exception:  # noqa: BLE001
                logger.exception("LLM relevance classification failed for email %s", getattr(email, "id", None))

        return verdict

    @staticmethod
    async def classify_event(
        db: AsyncSession,
        user: User,
        event: Event,
        *,
        payload: dict | None = None,
    ) -> Verdict:
        mode = InboundFilterService.mode()
        if mode == "off":
            return Verdict(CATEGORY_ACTIONABLE, "filter disabled", SOURCE_HEURISTIC)

        verdict = _heuristic_event_verdict(user, event, payload)

        # Known-contact promotion via attendees.
        if verdict.category in (CATEGORY_NOISE, CATEGORY_INFORMATIONAL):
            try:
                addrs = [
                    (a.get("email") or "").lower()
                    for a in (event.attendees or [])
                    if isinstance(a, dict) and a.get("email")
                ]
                for addr in addrs:
                    if not addr or addr == (user.email or "").lower():
                        continue
                    res = await db.execute(select(Contact).where(Contact.email == addr))
                    contact = res.scalar_one_or_none()
                    known, why = await _contact_is_known(db, user, contact, addr)
                    if known:
                        return Verdict(CATEGORY_ACTIONABLE, f"attendee known: {why}", SOURCE_KNOWN_CONTACT)
            except Exception:  # noqa: BLE001
                logger.exception("known-contact lookup failed for event %s", getattr(event, "id", None))

        if mode == "permissive":
            if verdict.category == CATEGORY_NOISE:
                return verdict
            return Verdict(CATEGORY_ACTIONABLE, "permissive: passing through", verdict.source)

        if mode == "strict" and verdict.category == CATEGORY_INFORMATIONAL:
            return Verdict(CATEGORY_NOISE, f"strict mode: demoted ({verdict.reason})", verdict.source)

        return verdict

    @staticmethod
    def apply_verdict_to_email(email: Email, verdict: Verdict) -> None:
        email.triage_category = verdict.category
        email.triage_reason = (verdict.reason or "")[:255]
        email.triage_source = verdict.source
        email.triage_at = datetime.now(UTC)

    @staticmethod
    def apply_verdict_to_event(event: Event, verdict: Verdict) -> None:
        event.triage_category = verdict.category
        event.triage_reason = (verdict.reason or "")[:255]
        event.triage_source = verdict.source
        event.triage_at = datetime.now(UTC)


__all__ = [
    "CATEGORY_ACTIONABLE",
    "CATEGORY_INFORMATIONAL",
    "CATEGORY_NOISE",
    "CATEGORY_UNKNOWN",
    "SOURCE_HEURISTIC",
    "SOURCE_LLM",
    "SOURCE_KNOWN_CONTACT",
    "SOURCE_MANUAL",
    "InboundFilterService",
    "Verdict",
    "heuristic_sender_is_noise",
]
