from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx


async def upload_file(
    provider: str,
    creds: dict[str, Any],
    path: str,
    content: bytes,
    mime: str,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    token = creds.get("access_token") or creds.get("token")
    if not token and provider not in ("mock_files",):
        return {"ok": False, "error": "missing access_token in connection credentials"}

    safe = path.lstrip("/").replace("\\", "/")
    encoded = "/".join(quote(seg, safe="") for seg in safe.split("/"))
    filename = safe.split("/")[-1] or "upload.bin"

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "provider": provider,
            "path": safe,
            "bytes": len(content),
            "mime": mime,
        }

    if provider in ("graph_onedrive", "onedrive", "sharepoint"):
        url = f"https://graph.microsoft.com/v1.0/me/drive/root:/{encoded}:/content"
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.put(
                url,
                content=content,
                headers={"Authorization": f"Bearer {token}", "Content-Type": mime},
            )
        if r.status_code >= 300:
            return {"ok": False, "status": r.status_code, "detail": r.text[:500]}
        return {"ok": True, "item": r.json()}

    if provider in ("google_drive", "gdrive"):
        upload_url = "https://www.googleapis.com/upload/drive/v3/files?uploadType=media"
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(
                upload_url,
                content=content,
                headers={"Authorization": f"Bearer {token}", "Content-Type": mime},
            )
            if r.status_code >= 300:
                return {"ok": False, "status": r.status_code, "detail": r.text[:500]}
            file_json = r.json()
            fid = file_json.get("id")
            if fid:
                patch_r = await client.patch(
                    f"https://www.googleapis.com/drive/v3/files/{fid}",
                    json={"name": filename},
                    headers={"Authorization": f"Bearer {token}"},
                )
                if patch_r.status_code >= 300:
                    return {"ok": True, "file": file_json, "rename_warning": patch_r.text[:200]}
            return {"ok": True, "file": file_json}

    if provider == "mock_files":
        return {"ok": True, "mock": True, "path": safe, "bytes": len(content), "mime": mime}

    return {"ok": False, "error": f"unsupported files provider: {provider}"}


async def share_file(
    provider: str,
    creds: dict[str, Any],
    file_id: str,
    email: str,
    role: str = "reader",
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Grant access to a single file. Supports Google Drive (`permissions.create`) and
    OneDrive/SharePoint (`/invite`).
    """
    token = creds.get("access_token") or creds.get("token")
    if not token and provider != "mock_files":
        return {"ok": False, "error": "missing access_token"}
    if dry_run:
        return {"ok": True, "dry_run": True, "provider": provider, "file_id": file_id, "email": email, "role": role}
    if provider in ("google_drive", "gdrive"):
        body = {"type": "user", "role": "reader" if role == "reader" else "writer", "emailAddress": email}
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(
                f"https://www.googleapis.com/drive/v3/files/{file_id}/permissions",
                json=body,
                headers={"Authorization": f"Bearer {token}"},
            )
        if r.status_code >= 300:
            return {"ok": False, "status": r.status_code, "detail": r.text[:500]}
        return {"ok": True, "permission": r.json()}
    if provider in ("graph_onedrive", "onedrive", "sharepoint"):
        body = {
            "requireSignIn": True,
            "sendInvitation": False,
            "roles": ["read" if role == "reader" else "write"],
            "recipients": [{"email": email}],
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(
                f"https://graph.microsoft.com/v1.0/me/drive/items/{file_id}/invite",
                json=body,
                headers={"Authorization": f"Bearer {token}"},
            )
        if r.status_code >= 300:
            return {"ok": False, "status": r.status_code, "detail": r.text[:500]}
        return {"ok": True, "invite": r.json()}
    if provider == "mock_files":
        return {"ok": True, "mock": True}
    return {"ok": False, "error": f"unsupported provider: {provider}"}
