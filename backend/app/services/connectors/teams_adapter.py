from __future__ import annotations

from typing import Any

import httpx


async def post_channel_message(
    provider: str,
    creds: dict[str, Any],
    team_id: str,
    channel_id: str,
    body: str,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    token = creds.get("access_token") or creds.get("token")
    if dry_run:
        if provider in ("mock_teams",):
            return {"ok": True, "dry_run": True, "team_id": team_id, "channel_id": channel_id}
        if provider not in ("graph_teams", "teams"):
            return {"ok": False, "error": f"unsupported teams provider: {provider}"}
        if not token:
            return {"ok": False, "error": "missing access_token in connection credentials"}
        return {"ok": True, "dry_run": True, "team_id": team_id, "channel_id": channel_id, "chars": len(body)}
    if provider in ("mock_teams",):
        return {"ok": True, "mock": True, "team_id": team_id, "channel_id": channel_id}
    if provider not in ("graph_teams", "teams"):
        return {"ok": False, "error": f"unsupported teams provider: {provider}"}
    if not token:
        return {"ok": False, "error": "missing access_token in connection credentials"}
    url = f"https://graph.microsoft.com/v1.0/teams/{team_id}/channels/{channel_id}/messages"
    payload: dict[str, Any] = {"body": {"content": body}}
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(url, json=payload, headers={"Authorization": f"Bearer {token}"})
    if r.status_code >= 300:
        return {"ok": False, "status": r.status_code, "detail": r.text[:500]}
    return {"ok": True, "message": r.json()}
