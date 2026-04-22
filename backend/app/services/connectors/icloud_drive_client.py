"""iCloud Drive via PyiCloud (Apple web APIs).

Uses the **same Apple ID + password** stored on ``icloud_caldav`` connections:
CalDAV continues to use the **app-specific password**; Drive uses PyiCloud’s
SRP-based web login. Apple may still require two-factor approval for some
accounts — surfaced as a clear error from this module.

This is not a first-party Apple REST product; behaviour can change when Apple
updates their web services. See ``docs/INTEGRATIONS_ROADMAP.md``.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path
from tempfile import gettempdir
from typing import Any

MAX_LIST_ITEMS = 500
DEFAULT_DOWNLOAD_MAX_BYTES = 4 * 1024 * 1024


class ICloudDriveError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"iCloud Drive {status_code}: {detail[:500]}")


def _cookie_dir_for_connection(connection_id: int) -> str:
    base = Path(gettempdir()) / "aquila-icloud" / f"conn-{connection_id}"
    base.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(base, 0o700)
    except OSError:
        pass
    return str(base)


def _map_pyicloud_error(exc: Exception) -> ICloudDriveError:
    """Turn PyiCloud exceptions into stable HTTP-style errors for the agent layer."""
    msg = str(exc).strip() or type(exc).__name__
    lowered = msg.lower()
    if (
        "2fa" in lowered
        or "two-step" in lowered
        or "two-factor" in lowered
        or "two factor" in lowered
    ):
        return ICloudDriveError(
            401,
            "Apple requested two-factor or device approval for iCloud web login. "
            "Complete 2FA on a trusted device, or try again after Apple sends a code. "
            "CalDAV calendar with an app-specific password may still work independently.",
        )
    if "password" in lowered or "login" in lowered or "authenticate" in lowered:
        return ICloudDriveError(401, msg)
    if "not found" in lowered or "no child named" in lowered:
        return ICloudDriveError(404, msg)
    return ICloudDriveError(502, msg)


def _open_service(
    apple_id: str,
    password: str,
    *,
    connection_id: int,
    china_mainland: bool,
) -> Any:
    from pyicloud import PyiCloudService

    return PyiCloudService(
        apple_id.strip(),
        password,
        cookie_directory=_cookie_dir_for_connection(connection_id),
        china_mainland=china_mainland,
        authenticate=True,
    )


def verify_drive_sync(
    apple_id: str,
    password: str,
    *,
    connection_id: int,
    china_mainland: bool = False,
) -> dict[str, Any]:
    """Lightweight check: authenticate and read root folder listing."""
    try:
        api = _open_service(
            apple_id,
            password,
            connection_id=connection_id,
            china_mainland=china_mainland,
        )
        names = api.drive.root.dir()
        n = len(names)
        return {"ok": True, "root_item_count": n, "sample": names[:8]}
    except Exception as exc:  # noqa: BLE001 — PyiCloud raises various types
        raise _map_pyicloud_error(exc) from exc


def list_folder_sync(
    apple_id: str,
    password: str,
    *,
    connection_id: int,
    china_mainland: bool = False,
    path: str = "",
) -> dict[str, Any]:
    """List immediate children of a folder path (slash-separated, relative to Drive root)."""
    try:
        api = _open_service(
            apple_id,
            password,
            connection_id=connection_id,
            china_mainland=china_mainland,
        )
        parts = [p for p in path.replace("\\", "/").split("/") if p and p not in (".",)]
        node = api.drive.root
        for seg in parts:
            node = node[seg]
        if node.type == "file":
            return {"error": "path is a file — use icloud_drive_get_file with this path"}
        children = node.get_children()
        truncated = len(children) > MAX_LIST_ITEMS
        slice_children = children[:MAX_LIST_ITEMS]
        items: list[dict[str, Any]] = []
        for c in slice_children:
            items.append(
                {
                    "name": c.name,
                    "type": c.type,
                    "size": c.size,
                    "docwsid": c.data.get("docwsid"),
                    "drivewsid": c.data.get("drivewsid"),
                }
            )
        return {
            "path": path.strip() or ".",
            "items": items,
            "truncated": truncated,
        }
    except ICloudDriveError:
        raise
    except KeyError as exc:
        raise ICloudDriveError(404, f"path not found: {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        raise _map_pyicloud_error(exc) from exc


def download_file_sync(
    apple_id: str,
    password: str,
    *,
    connection_id: int,
    china_mainland: bool = False,
    path: str = "",
    max_bytes: int = DEFAULT_DOWNLOAD_MAX_BYTES,
) -> dict[str, Any]:
    """Download a single file by slash-separated path from Drive root."""
    if max_bytes < 1 or max_bytes > 32 * 1024 * 1024:
        return {"error": "max_bytes must be between 1 and 33554432"}
    try:
        api = _open_service(
            apple_id,
            password,
            connection_id=connection_id,
            china_mainland=china_mainland,
        )
        parts = [p for p in path.replace("\\", "/").split("/") if p and p not in (".",)]
        if not parts:
            return {"error": "path must include a file name"}
        node = api.drive.root
        for seg in parts:
            node = node[seg]
        if node.type != "file":
            return {"error": "path is not a file (folder or unknown)"}
        sz = node.size
        if sz is not None and int(sz) > max_bytes:
            return {
                "error": f"file size {sz} bytes exceeds max_bytes {max_bytes}",
                "size_bytes": int(sz),
            }
        response = node.open()
        data = response.content if response is not None else b""
        if len(data) > max_bytes:
            return {
                "error": f"downloaded {len(data)} bytes exceeds max_bytes {max_bytes}",
                "size_bytes": len(data),
            }
        return {
            "filename": node.name,
            "size_bytes": len(data),
            "content_base64": base64.b64encode(data).decode("ascii"),
        }
    except ICloudDriveError:
        raise
    except KeyError as exc:
        raise ICloudDriveError(404, f"path not found: {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        raise _map_pyicloud_error(exc) from exc
