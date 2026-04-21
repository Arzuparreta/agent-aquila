"""Chat thread listing: no implicit default row is inserted for new users."""

from __future__ import annotations

import pytest

from app.models.chat_thread import ChatThread
from app.models.user import User
from app.services.chat_service import delete_all_archived_threads, list_threads


@pytest.mark.asyncio
async def test_list_threads_empty_for_new_user(db_session, crm_user: User) -> None:
    rows = await list_threads(db_session, crm_user, include_archived=False)
    assert rows == []


@pytest.mark.asyncio
async def test_delete_all_archived_threads_keeps_active(db_session, crm_user: User) -> None:
    active = ChatThread(
        user_id=crm_user.id,
        kind="general",
        title="Keep",
        archived=False,
    )
    archived = ChatThread(
        user_id=crm_user.id,
        kind="general",
        title="Gone",
        archived=True,
    )
    db_session.add(active)
    db_session.add(archived)
    await db_session.commit()

    removed = await delete_all_archived_threads(db_session, crm_user)
    await db_session.commit()
    assert removed == 1

    rows = await list_threads(db_session, crm_user, include_archived=True)
    assert len(rows) == 1
    assert rows[0].id == active.id
