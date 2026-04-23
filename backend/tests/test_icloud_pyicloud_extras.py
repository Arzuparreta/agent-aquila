"""PyiCloud extras — mocked service (no Apple login)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services.connectors.icloud_pyicloud_extras import list_notes_sync, list_reminders_sync


def test_list_reminders_sync_uses_pyicloud() -> None:
    mock_api = MagicMock()
    lst = MagicMock()
    lst.id = "list-1"
    lst.title = "Todo"
    mock_rem = MagicMock()
    mock_rem.id = "r1"
    mock_rem.title = "Buy milk"
    mock_rem.completed = False
    batch = MagicMock()
    batch.reminders = [mock_rem]
    mock_api.reminders.lists.return_value = [lst]
    mock_api.reminders.list_reminders.return_value = batch

    with patch("app.services.connectors.icloud_pyicloud_extras._open_service", return_value=mock_api):
        out = list_reminders_sync("u@icloud.com", "pw", connection_id=9, china_mainland=False)
    assert len(out["lists"]) == 1
    assert out["lists"][0]["list_id"] == "list-1"
    assert out["lists"][0]["reminders"][0]["title"] == "Buy milk"
    assert "warning" in out


def test_list_notes_sync_uses_recents() -> None:
    mock_api = MagicMock()
    n = MagicMock()
    n.id = "n1"
    n.title = "Scratch"
    n.folder_id = "f1"
    mock_api.notes.recents.return_value = [n]

    with patch("app.services.connectors.icloud_pyicloud_extras._open_service", return_value=mock_api):
        out = list_notes_sync("u@icloud.com", "pw", connection_id=3, limit=5)
    assert out["notes"][0]["id"] == "n1"
    assert "warning" in out
