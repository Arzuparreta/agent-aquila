"""Regression: default-thread upsert must match partial unique index inference."""

from __future__ import annotations

import pytest

from app.models.user import User
from app.services.chat_service import get_or_create_general_thread


@pytest.mark.asyncio
async def test_get_or_create_general_thread_inserts_for_new_user(db_session, crm_user: User) -> None:
    """Fresh users had no default row; INSERT ... ON CONFLICT must match ``uq_chat_threads_user_default``."""
    row = await get_or_create_general_thread(db_session, crm_user)
    assert row.is_default is True
    again = await get_or_create_general_thread(db_session, crm_user)
    assert again.id == row.id
