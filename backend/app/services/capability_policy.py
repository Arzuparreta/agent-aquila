from __future__ import annotations

from typing import Literal

from fastapi import HTTPException, status

from app.core.config import settings

RiskTier = Literal["read", "sync", "crm_write", "external_write"]

# Agent tool names that never mutate external systems or CRM without a pending row.
READ_ONLY_AGENT_TOOLS: frozenset[str] = frozenset(
    {
        "hybrid_rag_search",
        "get_entity",
        "search_emails",
        "get_thread",
        "list_calendar_events",
        "search_drive",
        "get_drive_file_text",
        "list_automations",
        "list_connectors",
    }
)

# Proposal / pending-operation kinds grouped by tier (used for UI labels and future auto-rules).
KIND_RISK: dict[str, RiskTier] = {
    "create_deal": "crm_write",
    "update_deal": "crm_write",
    "create_contact": "crm_write",
    "update_contact": "crm_write",
    "create_event": "crm_write",
    "update_event": "crm_write",
    "connector_email_send": "external_write",
    "connector_calendar_create": "external_write",
    "connector_calendar_update": "external_write",
    "connector_calendar_delete": "external_write",
    "connector_file_upload": "external_write",
    "connector_file_share": "external_write",
    "connector_teams_message": "external_write",
}

# Capability auto-apply policy. Internal CRM writes run instantly with UNDO; external
# actions still require approval. Anything not listed defaults to approval-required.
AUTO_APPLY_KINDS: frozenset[str] = frozenset(
    {
        "create_contact",
        "update_contact",
        "create_deal",
        "update_deal",
        "create_event",
        "update_event",
    }
)


def risk_tier_for_kind(kind: str) -> RiskTier:
    return KIND_RISK.get(kind, "crm_write")


def kind_is_auto_apply(kind: str) -> bool:
    return kind in AUTO_APPLY_KINDS


def allow_automatic_execution(tier: RiskTier) -> bool:
    """Tiered policy: only low-risk read/sync may run without human approval (future use)."""
    return tier in ("read", "sync")


def agent_tool_is_read_only(tool_name: str) -> bool:
    return tool_name in READ_ONLY_AGENT_TOOLS


def _email_allowlist_from_settings() -> frozenset[str]:
    raw = (settings.agent_email_domain_allowlist or "").strip()
    if not raw:
        return frozenset()
    parts = {p.strip().lower() for p in raw.split(",") if p.strip()}
    return frozenset(parts)


def email_recipient_allowed(address: str, allowlist: frozenset[str] | None = None) -> bool:
    allowed = allowlist if allowlist is not None else _email_allowlist_from_settings()
    if not allowed:
        return True
    addr = address.lower().strip()
    domain = addr.split("@", 1)[-1] if "@" in addr else ""
    return domain in allowed or addr in allowed


def enforce_email_recipients_allowed(payload: dict) -> None:
    """Raise400 if AGENT_EMAIL_DOMAIN_ALLOWLIST is set and a recipient is not allowed."""
    allow = _email_allowlist_from_settings()
    if not allow:
        return
    to_raw = payload.get("to")
    recipients: list[str] = to_raw if isinstance(to_raw, list) else [str(to_raw)] if to_raw else []
    for addr in recipients:
        if not email_recipient_allowed(str(addr), allow):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Email recipient not on allowlist: {addr!r}",
            )
