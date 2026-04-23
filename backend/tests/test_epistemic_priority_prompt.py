"""Host-injected epistemic rules must not be regressed: memory is not product truth."""

from app.services.agent_workspace import _EPISTEMIC_PRIORITY_HOST


def test_epistemic_block_requires_describe_harness_over_memory() -> None:
    s = _EPISTEMIC_PRIORITY_HOST
    assert "describe_harness" in s
    assert "Epistemic priority" in s
    assert "tool results" in s.lower() or "Tool results" in s
