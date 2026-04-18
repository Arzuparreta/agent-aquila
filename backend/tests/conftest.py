"""Shared pytest fixtures.

Kept minimal: the AI provider test suite only needs ``httpx.MockTransport``
plumbing and an ``asyncio`` event loop. No DB / FastAPI app is spun up here.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
