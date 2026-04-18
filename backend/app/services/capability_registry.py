from __future__ import annotations

from typing import Any, TypedDict

from app.services.capability_policy import RiskTier, risk_tier_for_kind


class ProposalKindMeta(TypedDict):
    """Registered pending-operation kinds for agents and tooling."""

    description: str
    risk_tier: RiskTier


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
        "connector_file_upload",
        "connector_teams_message",
    ]
    return {
        k: {
            "description": f"Pending operation kind `{k}` (executed only after human approval).",
            "risk_tier": risk_tier_for_kind(k),
        }
        for k in kinds
    }


def describe_capabilities() -> dict[str, Any]:
    return {"proposal_kinds": proposal_kind_registry()}
