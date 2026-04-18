"""Unit tests for the inbound noise filter heuristics.

These tests intentionally exercise only the pure-function Stage A (and the
``heuristic_sender_is_noise`` helper), which means they don't need a live
Postgres connection — handy for fast CI and for guarding against regressions
in the regex set.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.models.email import Email
from app.models.event import Event
from app.models.user import User
from app.services.inbound_filter_service import (
    CATEGORY_ACTIONABLE,
    CATEGORY_INFORMATIONAL,
    CATEGORY_NOISE,
    _heuristic_email_verdict,
    _heuristic_event_verdict,
    heuristic_sender_is_noise,
)


def _email(
    *,
    sender: str,
    subject: str,
    headers: dict | None = None,
    body: str = "",
    direction: str = "inbound",
) -> Email:
    return Email(
        sender_email=sender.lower(),
        sender_name=None,
        subject=subject,
        body=body,
        received_at=datetime.now(UTC),
        raw_headers=headers,
        direction=direction,
    )


# --- Stage A: noisy newsletter emails (the user's actual examples) ----------


@pytest.mark.parametrize(
    "email",
    [
        _email(
            sender="no-reply@leetcode.com",
            subject="LeetCode Weekly Digest",
            headers={"List-Unsubscribe": "<https://leetcode.com/unsub>"},
            body="Hi LeetCoder! …",
        ),
        _email(
            sender="linkedin@em.linkedin.com",
            subject="Rubén, thanks for being a valued member",
            headers={"List-Unsubscribe": "<mailto:unsub@linkedin.com>", "Precedence": "bulk"},
            body="Enjoy your free trial …",
        ),
        _email(
            sender="newsletter@mailchimp.com",
            subject="Your monthly recap",
            headers={"List-Id": "Newsletter <news.example.com>"},
        ),
        _email(
            sender="notifications@github.com",
            subject="[repo] You have a new follower",
            headers={"Auto-Submitted": "auto-generated"},
        ),
        _email(
            sender="no-reply@stripe.com",
            subject="Your verification code is 123456",
        ),
    ],
)
def test_known_newsletters_are_classified_as_noise(email: Email) -> None:
    verdict = _heuristic_email_verdict(email)
    assert verdict.category == CATEGORY_NOISE, verdict


# --- Stage A: actionable booking-style mail keeps passing ------------------


@pytest.mark.parametrize(
    "subject",
    [
        "Booking inquiry — Madrid festival",
        "Concert offer for June",
        "Contract draft for the show",
        "Press interview request",
        "Invoice attached",
    ],
)
def test_actionable_subjects_are_passed_through(subject: str) -> None:
    email = _email(sender="manager@partner.com", subject=subject, body="...")
    verdict = _heuristic_email_verdict(email)
    assert verdict.category == CATEGORY_ACTIONABLE, verdict


# --- Stage A: ambiguous mail returns informational (Stage B will decide) ----


def test_unknown_personal_mail_falls_through_to_informational() -> None:
    email = _email(
        sender="friend@gmail.com",
        subject="hey, are you around tonight?",
        body="want to grab a coffee?",
    )
    verdict = _heuristic_email_verdict(email)
    assert verdict.category == CATEGORY_INFORMATIONAL, verdict


# --- heuristic_sender_is_noise (used to gate Contact auto-creation) ---------


@pytest.mark.parametrize(
    "sender,headers,expected",
    [
        ("no-reply@leetcode.com", None, True),
        ("noreply@stripe.com", None, True),
        ("notifications@github.com", None, True),
        ("linkedin@em.linkedin.com", None, True),
        ("partner@somecompany.com", None, False),
        ("partner@somecompany.com", {"List-Unsubscribe": "<...>"}, True),
        ("partner@somecompany.com", {"Precedence": "bulk"}, True),
        ("partner@somecompany.com", {"Auto-Submitted": "auto-generated"}, True),
        ("manager@partner.com", {"Auto-Submitted": "no"}, False),
        ("ceo@unknownco.com", None, False),
    ],
)
def test_heuristic_sender_is_noise(
    sender: str, headers: dict | None, expected: bool
) -> None:
    assert heuristic_sender_is_noise(sender, headers) is expected


# --- Calendar heuristics ----------------------------------------------------


def _user(email: str = "me@example.com") -> User:
    return User(email=email, hashed_password="x", full_name="Me")


def _event(
    *,
    summary: str,
    attendees: list | None = None,
    description: str | None = None,
    all_day: bool | None = None,
    deal_id: int | None = None,
) -> Event:
    return Event(
        venue_name=summary,
        event_date=datetime.now(UTC).date(),
        status="confirmed",
        summary=summary,
        attendees=attendees,
        description=description,
        all_day=all_day,
        deal_id=deal_id,
    )


def test_birthday_event_is_noise() -> None:
    user = _user()
    ev = _event(summary="Birthday: María", all_day=True)
    verdict = _heuristic_event_verdict(user, ev, payload=None)
    assert verdict.category == CATEGORY_NOISE


def test_declined_event_is_noise() -> None:
    user = _user("artist@band.com")
    ev = _event(
        summary="External meeting",
        attendees=[{"email": "artist@band.com", "responseStatus": "declined"}],
    )
    verdict = _heuristic_event_verdict(user, ev, payload=None)
    assert verdict.category == CATEGORY_NOISE


def test_user_organized_event_is_actionable() -> None:
    user = _user("artist@band.com")
    ev = _event(summary="Studio session", description="block out the afternoon")
    payload = {"organizer": {"email": "artist@band.com"}}
    verdict = _heuristic_event_verdict(user, ev, payload=payload)
    assert verdict.category == CATEGORY_ACTIONABLE


def test_event_linked_to_deal_is_actionable() -> None:
    user = _user()
    ev = _event(summary="External meeting", deal_id=42)
    verdict = _heuristic_event_verdict(user, ev, payload=None)
    assert verdict.category == CATEGORY_ACTIONABLE


def test_minimal_external_event_is_informational() -> None:
    user = _user()
    ev = _event(summary="External meeting")
    verdict = _heuristic_event_verdict(user, ev, payload=None)
    assert verdict.category in (CATEGORY_INFORMATIONAL, CATEGORY_NOISE)


# --- DB-backed integration: known-contact promotion + LLM disabled mode ----


@pytest.mark.asyncio
async def test_known_contact_promotion(monkeypatch, db_session, crm_user):  # type: ignore[no-untyped-def]
    """A noise-shaped email from a contact who has a Deal must be promoted
    to ``actionable`` so the artist still hears about it.
    """
    from app.models.contact import Contact
    from app.models.deal import Deal
    from app.services.inbound_filter_service import (
        SOURCE_KNOWN_CONTACT,
        InboundFilterService,
    )

    contact = Contact(name="Important Promoter", email="boss@partner.com", role="agent")
    db_session.add(contact)
    await db_session.flush()
    deal = Deal(contact_id=contact.id, title="Festival hold", status="negotiating")
    db_session.add(deal)
    await db_session.flush()

    email = Email(
        contact_id=contact.id,
        sender_email="boss@partner.com",
        sender_name="Important Promoter",
        subject="Monthly newsletter",  # noise-ish subject
        body="Just our monthly recap.",
        received_at=datetime.now(UTC),
        raw_headers={"List-Unsubscribe": "<...>"},  # bulk header
        direction="inbound",
    )
    db_session.add(email)
    await db_session.flush()

    # Force ``off`` mode would short-circuit; ensure default mode is exercised.
    monkeypatch.setattr(
        InboundFilterService, "mode", staticmethod(lambda: "balanced")
    )
    monkeypatch.setattr(
        InboundFilterService, "llm_enabled", staticmethod(lambda: False)
    )

    verdict = await InboundFilterService.classify_email(db_session, crm_user, email)
    assert verdict.category == CATEGORY_ACTIONABLE
    assert verdict.source == SOURCE_KNOWN_CONTACT


@pytest.mark.asyncio
async def test_outbound_emails_never_classified_actionable(
    monkeypatch, db_session, crm_user
):  # type: ignore[no-untyped-def]
    from app.services.inbound_filter_service import InboundFilterService

    monkeypatch.setattr(
        InboundFilterService, "mode", staticmethod(lambda: "balanced")
    )

    email = Email(
        sender_email="me@example.com",
        sender_name=None,
        subject="Booking confirmation — please countersign",
        body="...",
        received_at=datetime.now(UTC),
        direction="outbound",
    )
    db_session.add(email)
    await db_session.flush()

    verdict = await InboundFilterService.classify_email(db_session, crm_user, email)
    assert verdict.category != CATEGORY_ACTIONABLE
