"""Proposal helpers."""
from app.models.pending_proposal import PendingProposal
from app.schemas.agent import PendingProposalRead

def proposal_to_read(proposal: PendingProposal) -> PendingProposalRead:
    """Convert PendingProposal model to read schema."""
    return PendingProposalRead(
        id=proposal.id,
        run_id=proposal.run_id,
        user_id=proposal.user_id,
        thread_id=proposal.thread_id,
        tool_name=proposal.tool_name,
        tool_args=proposal.tool_args,
        approval_status=proposal.approval_status,
        created_at=proposal.created_at,
    )
