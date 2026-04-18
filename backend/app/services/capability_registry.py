from __future__ import annotations

from typing import Any, TypedDict

from app.services.capability_policy import RiskTier, kind_is_auto_apply, risk_tier_for_kind


class ProposalKindMeta(TypedDict):
    """Registered pending-operation kinds for agents and tooling."""

    description: str
    risk_tier: RiskTier
    auto_apply: bool


def proposal_kind_registry() -> dict[str, ProposalKindMeta]:
    kinds = [
        "create_deal",
        "update_deal",
        "create_contact",
        "update_contact",
        "create_event",
        "update_event",
        "connector_email_send",
        "connector_calendar_create",
        "connector_calendar_update",
        "connector_calendar_delete",
        "connector_file_upload",
        "connector_file_share",
        "connector_teams_message",
    ]
    out: dict[str, ProposalKindMeta] = {}
    for k in kinds:
        is_auto = kind_is_auto_apply(k)
        out[k] = {
            "description": (
                f"Operation `{k}` — "
                + ("auto-applied with UNDO." if is_auto else "executed after human approval.")
            ),
            "risk_tier": risk_tier_for_kind(k),
            "auto_apply": is_auto,
        }
    return out


def describe_capabilities() -> dict[str, Any]:
    return {"proposal_kinds": proposal_kind_registry()}
