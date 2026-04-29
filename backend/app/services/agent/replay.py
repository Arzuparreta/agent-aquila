"""Replay / regression: scripted tool outputs without calling live connectors."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentReplayContext:
    """When active, non-final tool calls consume scripted results in order.

    ``tool_results`` is a list of dicts returned as-if from ``_dispatch_tool``.
    The list is consumed for each tool call whose name is not ``final_answer``.
    If the list is exhausted, replay raises ``RuntimeError`` (tests should size it correctly).
    """

    tool_results: list[dict[str, Any]] = field(default_factory=list)
    _idx: int = field(default=0, repr=False)

    def next_tool_result(self) -> dict[str, Any]:
        if self._idx >= len(self.tool_results):
            raise RuntimeError(
                "replay tool_results exhausted — add more entries or reduce tool calls in the fixture"
            )
        r = self.tool_results[self._idx]
        self._idx += 1
        return r

    @property
    def exhausted(self) -> bool:
        return self._idx >= len(self.tool_results)
