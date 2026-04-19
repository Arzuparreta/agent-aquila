"""Registry of proposal kinds the agent can produce.

After the OpenClaw refactor only outbound email is proposal-gated.
Everything else runs auto-applied via the live provider tools.
"""
from __future__ import annotations

from typing import Any, TypedDict

from app.services.capability_policy import RiskTier, risk_tier_for_kind


class ProposalKindMeta(TypedDict):
    description: str
    risk_tier: RiskTier
    auto_apply: bool


PROPOSAL_KINDS: tuple[str, ...] = ("email_send", "email_reply")


def proposal_kind_registry() -> dict[str, ProposalKindMeta]:
    return {
        kind: {
            "description": f"Operation `{kind}` — executed after human approval.",
            "risk_tier": risk_tier_for_kind(kind),
            "auto_apply": False,
        }
        for kind in PROPOSAL_KINDS
    }


def describe_capabilities() -> dict[str, Any]:
    return {"proposal_kinds": proposal_kind_registry()}
