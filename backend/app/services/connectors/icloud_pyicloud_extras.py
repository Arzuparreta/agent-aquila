"""iCloud Reminders, Notes, and Photos via PyiCloud (best-effort, unofficial web APIs).

Uses the same SRP web session as iCloud Drive. Requires the **icloud_caldav** credential
(Apple ID + app-specific password). May prompt 2FA like Drive.

This is **not** a stable first-party Apple API — see ``docs/INTEGRATIONS_ROADMAP.md``.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.services.connectors.icloud_drive_client import (
    ICloudDriveError,
    _map_pyicloud_error,
    _open_service,
)

WARNING = (
    "PyiCloud surfaces are unofficial and may break when Apple changes their web services. "
    "Photos/Notes/Reminders reads are best-effort metadata only (no binary downloads here)."
)


def list_reminders_sync(
    apple_id: str,
    password: str,
    *,
    connection_id: int,
    china_mainland: bool = False,
    max_lists: int = 20,
    max_reminders_per_list: int = 50,
) -> dict[str, Any]:
    max_lists = max(1, min(max_lists, 50))
    max_reminders_per_list = max(1, min(max_reminders_per_list, 200))
    try:
        api = _open_service(
            apple_id,
            password,
            connection_id=connection_id,
            china_mainland=china_mainland,
        )
        svc = api.reminders
        lists_out: list[dict[str, Any]] = []
        for i, lst in enumerate(svc.lists()):
            if i >= max_lists:
                break
            batch = svc.list_reminders(
                lst.id,
                include_completed=True,
                results_limit=max_reminders_per_list,
            )
            rems = [
                {
                    "id": r.id,
                    "title": getattr(r, "title", None),
                    "completed": getattr(r, "completed", None),
                }
                for r in batch.reminders
            ]
            lists_out.append(
                {
                    "list_id": lst.id,
                    "list_title": getattr(lst, "title", None) or "",
                    "reminders": rems,
                }
            )
        return {"warning": WARNING, "lists": lists_out}
    except ICloudDriveError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _map_pyicloud_error(exc) from exc


def list_notes_sync(
    apple_id: str,
    password: str,
    *,
    connection_id: int,
    china_mainland: bool = False,
    limit: int = 40,
) -> dict[str, Any]:
    limit = max(1, min(limit, 200))
    try:
        api = _open_service(
            apple_id,
            password,
            connection_id=connection_id,
            china_mainland=china_mainland,
        )
        notes_svc = api.notes
        items: list[dict[str, Any]] = []
        for n in notes_svc.recents(limit=limit):
            items.append(
                {
                    "id": getattr(n, "id", None),
                    "title": getattr(n, "title", None),
                    "folder_id": getattr(n, "folder_id", None),
                }
            )
        return {"warning": WARNING, "notes": items}
    except ICloudDriveError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _map_pyicloud_error(exc) from exc


def list_photos_sync(
    apple_id: str,
    password: str,
    *,
    connection_id: int,
    china_mainland: bool = False,
    max_albums: int = 8,
    max_photos_per_album: int = 25,
) -> dict[str, Any]:
    max_albums = max(1, min(max_albums, 40))
    max_photos_per_album = max(1, min(max_photos_per_album, 100))
    try:
        api = _open_service(
            apple_id,
            password,
            connection_id=connection_id,
            china_mainland=china_mainland,
        )
        photos = api.photos
        albums = photos.albums
        out: list[dict[str, Any]] = []
        for i, album in enumerate(albums):
            if i >= max_albums:
                break
            aname = getattr(album, "name", None) or getattr(album, "title", None) or album.__class__.__name__
            pics: list[dict[str, Any]] = []
            for j, ph in enumerate(album.photos):
                if j >= max_photos_per_album:
                    break
                try:
                    created = ph.created.isoformat() if getattr(ph, "created", None) else None
                except Exception:  # noqa: BLE001
                    created = None
                pics.append(
                    {
                        "id": ph.id,
                        "filename": ph.filename,
                        "size": getattr(ph, "size", None),
                        "created": created,
                    }
                )
            out.append({"album": str(aname), "photos": pics})
        return {"warning": WARNING, "albums": out}
    except ICloudDriveError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _map_pyicloud_error(exc) from exc


async def list_reminders(
    apple_id: str,
    password: str,
    *,
    connection_id: int,
    china_mainland: bool = False,
    max_lists: int = 20,
    max_reminders_per_list: int = 50,
) -> dict[str, Any]:
    return await asyncio.to_thread(
        list_reminders_sync,
        apple_id,
        password,
        connection_id=connection_id,
        china_mainland=china_mainland,
        max_lists=max_lists,
        max_reminders_per_list=max_reminders_per_list,
    )


async def list_notes(
    apple_id: str,
    password: str,
    *,
    connection_id: int,
    china_mainland: bool = False,
    limit: int = 40,
) -> dict[str, Any]:
    return await asyncio.to_thread(
        list_notes_sync,
        apple_id,
        password,
        connection_id=connection_id,
        china_mainland=china_mainland,
        limit=limit,
    )


async def list_photos(
    apple_id: str,
    password: str,
    *,
    connection_id: int,
    china_mainland: bool = False,
    max_albums: int = 8,
    max_photos_per_album: int = 25,
) -> dict[str, Any]:
    return await asyncio.to_thread(
        list_photos_sync,
        apple_id,
        password,
        connection_id=connection_id,
        china_mainland=china_mainland,
        max_albums=max_albums,
        max_photos_per_album=max_photos_per_album,
    )
