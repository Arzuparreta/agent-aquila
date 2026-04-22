"""iCloud Drive client — mocked PyiCloud (no real Apple account)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.connectors.icloud_drive_client import (
    ICloudDriveError,
    download_file_sync,
    list_folder_sync,
    verify_drive_sync,
)


def test_list_folder_root_returns_items() -> None:
    child = MagicMock()
    child.name = "Pages"
    child.type = "folder"
    child.size = None
    child.data = {"docwsid": "doc1", "drivewsid": "drv1"}

    mock_root = MagicMock()
    mock_root.type = "folder"
    mock_root.get_children.return_value = [child]

    mock_api = MagicMock()
    mock_api.drive.root = mock_root

    with patch("app.services.connectors.icloud_drive_client._open_service", return_value=mock_api):
        out = list_folder_sync("user@icloud.com", "app-pw", connection_id=42, path="")

    assert out["path"] == "."
    assert len(out["items"]) == 1
    assert out["items"][0]["name"] == "Pages"


def test_download_file_returns_base64() -> None:
    class _FakeFolder:
        type = "folder"

        def __init__(self, children: dict[str, object]) -> None:
            self._children = children

        def __getitem__(self, key: str):
            return self._children[key]

    file_node = MagicMock()
    file_node.type = "file"
    file_node.name = "hello.txt"
    file_node.size = 5
    file_node.data = {"docwsid": "d", "drivewsid": "w"}
    resp = MagicMock()
    resp.content = b"hello"
    file_node.open.return_value = resp

    tree = _FakeFolder({"Documents": _FakeFolder({"hello.txt": file_node})})
    mock_api = MagicMock()
    mock_api.drive.root = tree

    with patch("app.services.connectors.icloud_drive_client._open_service", return_value=mock_api):
        out = download_file_sync(
            "user@icloud.com",
            "app-pw",
            connection_id=3,
            path="Documents/hello.txt",
            max_bytes=1024,
        )

    assert out.get("filename") == "hello.txt"
    assert out.get("size_bytes") == 5
    assert out.get("content_base64") == "aGVsbG8="


def test_verify_drive_sync_ok() -> None:
    mock_root = MagicMock()
    mock_root.dir.return_value = ["a", "b"]
    mock_api = MagicMock()
    mock_api.drive.root = mock_root
    with patch("app.services.connectors.icloud_drive_client._open_service", return_value=mock_api):
        info = verify_drive_sync("u@i.com", "pw", connection_id=9)
    assert info["ok"] is True
    assert info["root_item_count"] == 2


def test_list_folder_file_path_returns_error_dict() -> None:
    file_node = MagicMock()
    file_node.type = "file"
    mock_api = MagicMock()
    mock_api.drive.root = file_node
    with patch("app.services.connectors.icloud_drive_client._open_service", return_value=mock_api):
        out = list_folder_sync("u", "p", connection_id=1, path="")
    assert "error" in out


@pytest.mark.parametrize(
    "msg,expect_sub",
    [
        ("Two-factor authentication required", "two-factor"),
        ("Incorrect Apple ID password", "password"),
    ],
)
def test_map_style_errors(msg: str, expect_sub: str) -> None:
    from app.services.connectors import icloud_drive_client as mod

    err = mod._map_pyicloud_error(RuntimeError(msg))
    assert isinstance(err, ICloudDriveError)
    assert expect_sub.lower() in err.detail.lower()
