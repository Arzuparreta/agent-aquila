"""Autonomous adapter generation (missing-tool → generate → sandbox → promote).

V1 provides the **contract** and a no-op / placeholder implementation. The production loop will:

1. Detect capability gaps (unknown tool name, repeated dispatch errors, user asks for unsupported API).
2. Generate adapter code (thin wrapper or new ``agent_tools`` entry) in an isolated path.
3. Run **sandbox** tests (subprocess or restricted import) before promotion.
4. **Promote** into the live tool registry only on success.

Hosts that do not enable this remain safe: all methods are optional hooks.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)


@dataclass
class AdapterPromotionResult:
    ok: bool
    detail: str
    path: str | None = None


class AdapterSandboxPipeline:
    """Placeholder pipeline; wire real sandbox + codegen in a later iteration."""

    def __init__(self, *, work_root: Path | None = None) -> None:
        self.work_root = work_root

    def report_gap(
        self,
        *,
        user_id: int,
        reason: str,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Log a capability gap (non-blocking)."""
        logger.info(
            "adapter_gap user_id=%s reason=%s ctx=%s",
            user_id,
            reason,
            (context or {}),
        )

    async def run_sandbox(
        self,
        code_path: Path,
        *,
        runner: Callable[[Path], Awaitable[AdapterPromotionResult]] | None = None,
    ) -> AdapterPromotionResult:
        """Execute optional async test runner; default skips."""
        if runner is None:
            return AdapterPromotionResult(
                ok=False, detail="sandbox_not_configured", path=str(code_path) if code_path else None
            )
        return await runner(code_path)

    async def promote_if_pass(
        self, result: AdapterPromotionResult, *, on_promote: Callable[[], Awaitable[None]] | None = None
    ) -> bool:
        if not result.ok:
            return False
        if on_promote:
            await on_promote()
        return True
