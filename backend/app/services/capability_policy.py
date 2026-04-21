"""Risk-tier policy for the agent.

After the OpenClaw refactor only outbound email is gated. Every other
agent tool runs auto-applied against the live provider API.
"""
from __future__ import annotations

from typing import Literal

from fastapi import HTTPException, status

from app.core.config import settings

RiskTier = Literal["read", "external_write"]

# Proposal kinds that require human approval before execution.
KIND_RISK: dict[str, RiskTier] = {
    "email_send": "external_write",
    "email_reply": "external_write",
}


def risk_tier_for_kind(kind: str) -> RiskTier:
    return KIND_RISK.get(kind, "external_write")


def kind_is_auto_apply(kind: str) -> bool:
    # Nothing in the proposal pipeline auto-applies — by design proposals only
    # exist for outbound email, which always needs the user to click approve.
    del kind
    return False


def frozen_allowlist_from_csv(raw: str) -> frozenset[str]:
    """Comma-separated domains or full addresses (lowercased). Empty string → no restriction when checked."""
    s = (raw or "").strip()
    if not s:
        return frozenset()
    parts = {p.strip().lower() for p in s.split(",") if p.strip()}
    return frozenset(parts)


def _email_allowlist_from_settings() -> frozenset[str]:
    return frozen_allowlist_from_csv(settings.agent_email_domain_allowlist or "")


def email_recipient_allowed(address: str, allowlist: frozenset[str] | None = None) -> bool:
    allowed = allowlist if allowlist is not None else _email_allowlist_from_settings()
    if not allowed:
        return True
    addr = address.lower().strip()
    domain = addr.split("@", 1)[-1] if "@" in addr else ""
    return domain in allowed or addr in allowed


def enforce_email_recipients_allowed(
    payload: dict, *, allowlist: frozenset[str] | None = None
) -> None:
    """Raise 400 if an allowlist is set and a recipient is not allowed.

    When ``allowlist`` is ``None``, uses the server env default. Callers may pass
    a per-user merged allowlist from :func:`~app.services.agent_runtime_config_service.resolve_for_user`.
    """
    allow = allowlist if allowlist is not None else _email_allowlist_from_settings()
    if not allow:
        return
    to_raw = payload.get("to")
    recipients: list[str] = (
        to_raw if isinstance(to_raw, list) else [str(to_raw)] if to_raw else []
    )
    for addr in recipients:
        if not email_recipient_allowed(str(addr), allow):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Email recipient not on allowlist: {addr!r}",
            )
