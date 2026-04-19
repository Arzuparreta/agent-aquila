"""Pluggable agent harness: native OpenAI tool calling vs prompted tool tags."""

from app.services.agent_harness.prompted import (
    format_tool_results_for_prompt,
    parse_tool_calls_from_content,
)
from app.services.agent_harness.selector import (
    HarnessPreference,
    default_harness_for_model,
    resolve_effective_mode,
)

__all__ = [
    "HarnessPreference",
    "default_harness_for_model",
    "resolve_effective_mode",
    "format_tool_results_for_prompt",
    "parse_tool_calls_from_content",
]
