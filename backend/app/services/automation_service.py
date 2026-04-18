"""Automation engine: matches inbound events against user rules and enqueues agent runs.

`dispatch_email_received` is called from the mail mirror services (Gmail + Graph Mail) right
after a new inbound email is committed. It performs lightweight in-process condition matching
(cheap SQL + substring checks) and enqueues an `execute_automation` worker job for each match.

`execute_automation` is the worker-side entrypoint that actually runs the agent, using the rule's
`prompt_template` interpolated with the triggering email's fields.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.automation import Automation
from app.models.email import Email
from app.models.user import User
from app.services.job_queue import enqueue as enqueue_job

logger = logging.getLogger(__name__)


def _match_conditions(conds: dict[str, Any], email: Email) -> bool:
    """All supplied matchers must be true. Missing fields in `conds` are ignored."""
    if not conds:
        return True
    for key in ("from_contains", "subject_contains", "body_contains"):
        needle = conds.get(key)
        if not needle:
            continue
        needle_l = str(needle).lower()
        haystack = {
            "from_contains": f"{email.sender_name or ''} {email.sender_email or ''}",
            "subject_contains": email.subject or "",
            "body_contains": (email.body or "") + " " + (email.snippet or ""),
        }[key]
        if needle_l not in haystack.lower():
            return False
    direction = conds.get("direction")
    if direction and str(direction).lower() != (email.direction or ""):
        return False
    provider = conds.get("provider")
    if provider and str(provider) != (email.provider or ""):
        return False
    return True


async def dispatch_email_received(db: AsyncSession, user: User, email: Email) -> list[int]:
    """Find and enqueue matching automations for a newly-mirrored inbound email."""
    if email.direction != "inbound":
        return []
    r = await db.execute(
        select(Automation).where(
            Automation.user_id == user.id,
            Automation.trigger == "email_received",
            Automation.enabled == True,  # noqa: E712
        )
    )
    enqueued: list[int] = []
    for rule in r.scalars().all():
        if not _match_conditions(dict(rule.conditions or {}), email):
            continue
        payload = {
            "user_id": user.id,
            "trigger": "email_received",
            "email_id": email.id,
            "subject": email.subject,
            "from": f"{email.sender_name or ''} <{email.sender_email or ''}>".strip(),
            "body": (email.body or "")[:8000],
            "thread_id": email.provider_thread_id,
        }
        try:
            await enqueue_job("run_automation", rule.id, payload, job_id=f"auto-{rule.id}-email-{email.id}")
            enqueued.append(rule.id)
        except Exception:
            logger.exception("failed to enqueue automation %s for email %s", rule.id, email.id)
    return enqueued


def _interpolate(template: str, payload: dict[str, Any]) -> str:
    """Very small `{placeholder}` replacement. Unknown keys pass through unchanged."""

    class _SafeDict(dict):
        def __missing__(self, key: str) -> str:
            return "{" + key + "}"

    try:
        return template.format_map(_SafeDict(**payload))
    except Exception:
        return template


async def execute_automation(
    db: AsyncSession, automation_id: int, payload: dict[str, Any]
) -> dict[str, Any]:
    """Runs the agent with the rule's prompt. Does NOT auto-approve proposals by default."""
    from app.services.agent_service import AgentService

    rule = await db.get(Automation, automation_id)
    if not rule or not rule.enabled:
        return {"ok": False, "error": "rule_missing_or_disabled"}
    user = await db.get(User, rule.user_id)
    if not user:
        return {"ok": False, "error": "user_missing"}
    prompt = _interpolate(rule.prompt_template, payload)
    try:
        run = await AgentService.run_agent(db, user, prompt)
    except Exception as exc:  # noqa: BLE001
        logger.exception("automation run failed for rule %s", automation_id)
        return {"ok": False, "error": repr(exc)}

    rule.last_run_at = datetime.now(UTC)
    rule.run_count = (rule.run_count or 0) + 1
    await db.commit()

    return {
        "ok": True,
        "rule_id": rule.id,
        "agent_run_id": run.id,
        "status": run.status,
        "auto_approve": rule.auto_approve,
    }
