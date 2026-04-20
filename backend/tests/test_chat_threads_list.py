"""Chat thread listing: no implicit default row is inserted for new users."""

from __future__ import annotations

import pytest

from app.models.user import User
from app.services.chat_service import list_threads


@pytest.mark.asyncio
async def test_list_threads_empty_for_new_user(db_session, crm_user: User) -> None:
    rows = await list_threads(db_session, crm_user, include_archived=False)
    assert rows == []
