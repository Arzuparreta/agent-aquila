"""Agent-side lifecycle for Automations (create / update / delete / list).

Different from ``automation_service`` (which executes rules on inbound events). This
module is what the AGENT calls when the artist expresses a preference in chat
("nunca enviar correos a X"). The agent records the rule silently and confirms
verbally.

We store both:
- ``instruction_natural_language``: the artist-facing sentence (shown verbatim in the
  hidden Automations panel and used by the agent when listing rules).
- ``prompt_template``: the actual instruction injected into agent runs at trigger time.
  When the agent updates an NL instruction, it should also re-derive the template.

For now we deterministically derive ``prompt_template`` from the NL instruction
(``"Apply the following user policy when handling this event: <NL>\n\n<context>"``).
That keeps the artist UI plain-language and avoids a second LLM call per write.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.automation import Automation
from app.models.user import User

# Default trigger when the agent learns a preference without specifying one.
DEFAULT_TRIGGER = "email_received"


def _derive_template(nl: str) -> str:
    """Wrap an NL instruction in a stable template the agent can execute on triggers."""
    return (
        "Política aprendida del artista (aplicar siempre): "
        + nl.strip()
        + "\n\n"
        "Contexto del evento entrante:\n"
        "De: {from}\n"
        "Asunto: {subject}\n\n"
        "{body}"
    )


def _normalize_conditions(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    for k in ("from_contains", "subject_contains", "body_contains", "direction", "provider"):
        v = raw.get(k)
        if v is None:
            continue
        out[k] = str(v)[:500]
    return out


async def list_automations(db: AsyncSession, user: User) -> list[Automation]:
    r = await db.execute(
        select(Automation).where(Automation.user_id == user.id).order_by(Automation.id.desc())
    )
    return list(r.scalars().all())


async def create_automation(
    db: AsyncSession,
    user: User,
    *,
    name: str,
    instruction_natural_language: str,
    trigger: str | None = None,
    conditions: dict[str, Any] | None = None,
    enabled: bool = True,
    source: str = "agent",
    commit: bool = False,
) -> Automation:
    rule = Automation(
        user_id=user.id,
        name=(name or instruction_natural_language[:80]).strip()[:255],
        trigger=(trigger or DEFAULT_TRIGGER)[:64],
        conditions=_normalize_conditions(conditions),
        prompt_template=_derive_template(instruction_natural_language),
        instruction_natural_language=instruction_natural_language.strip()[:2000],
        source=source[:16],
        enabled=enabled,
    )
    db.add(rule)
    await db.flush()
    if commit:
        await db.commit()
        await db.refresh(rule)
    return rule


async def update_automation(
    db: AsyncSession,
    user: User,
    *,
    automation_id: int,
    name: str | None = None,
    instruction_natural_language: str | None = None,
    conditions: dict[str, Any] | None = None,
    enabled: bool | None = None,
    commit: bool = False,
) -> Automation | None:
    rule = await db.get(Automation, automation_id)
    if not rule or rule.user_id != user.id:
        return None
    if name is not None:
        rule.name = name.strip()[:255]
    if instruction_natural_language is not None:
        rule.instruction_natural_language = instruction_natural_language.strip()[:2000]
        rule.prompt_template = _derive_template(rule.instruction_natural_language)
    if conditions is not None:
        rule.conditions = _normalize_conditions(conditions)
    if enabled is not None:
        rule.enabled = bool(enabled)
    rule.updated_at = datetime.now(UTC)
    await db.flush()
    if commit:
        await db.commit()
        await db.refresh(rule)
    return rule


async def delete_automation(
    db: AsyncSession, user: User, automation_id: int, *, commit: bool = False
) -> bool:
    rule = await db.get(Automation, automation_id)
    if not rule or rule.user_id != user.id:
        return False
    await db.delete(rule)
    if commit:
        await db.commit()
    else:
        await db.flush()
    return True


def automation_to_summary(rule: Automation) -> dict[str, Any]:
    return {
        "id": rule.id,
        "name": rule.name,
        "trigger": rule.trigger,
        "conditions": dict(rule.conditions or {}),
        "instruction": rule.instruction_natural_language or rule.prompt_template[:200],
        "enabled": rule.enabled,
        "source": rule.source,
        "run_count": rule.run_count,
        "last_run_at": rule.last_run_at.isoformat() if rule.last_run_at else None,
    }
