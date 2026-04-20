"""Build chat `attachments` JSON from a completed :class:`~app.schemas.agent.AgentRunRead`.

Shared by thread routes and the ARQ worker when finalizing a placeholder assistant row.
"""
from __future__ import annotations

from typing import Any

from app.schemas.agent import AgentRunRead, AgentStepRead
from app.services.capability_policy import risk_tier_for_kind
from app.services.pending_execution_service import preview_for_proposal_kind


def attachments_from_agent_run_read(run: AgentRunRead) -> list[dict[str, Any]]:
    """Translate pending proposals and tool steps into inline chat cards."""
    out: list[dict[str, Any]] = []
    for prop in run.pending_proposals or []:
        out.append(
            {
                "card_kind": "approval",
                "proposal_id": prop.id,
                "kind": prop.kind,
                "summary": prop.summary,
                "risk_tier": prop.risk_tier or risk_tier_for_kind(prop.kind),
                "preview": preview_for_proposal_kind(prop.kind, dict(prop.payload)),
            }
        )
    steps: list[AgentStepRead] = run.steps or []
    for step in steps:
        if not step.payload:
            continue
        if step.kind == "provider_error" and isinstance(step.payload, dict):
            payload = dict(step.payload)
            payload.setdefault("card_kind", "provider_error")
            out.append(payload)
            continue
        if step.kind == "key_decrypt_error" and isinstance(step.payload, dict):
            payload = dict(step.payload)
            payload.setdefault("card_kind", "key_decrypt_error")
            out.append(payload)
            continue
        if step.kind != "tool":
            continue
        result = step.payload.get("result") if isinstance(step.payload, dict) else None
        if isinstance(result, dict) and result.get("card_kind") in {
            "connector_setup",
            "oauth_authorize",
        }:
            out.append(result)
    return out
