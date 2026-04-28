from __future__ import annotations
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.connector_connection import ConnectorConnection
from app.models.user import User
from app.services.agent.runtime_clients import GoogleDriveClient

# From agent_service.py (Phase 5 refactor)



def _icloud_caldav_client(row: ConnectorConnection) -> ICloudCalDAVClient:
user, pw, _china = _icloud_app_password_creds(row)
return ICloudCalDAVClient(user, pw)


def _parse_rfc3339_to_utc_datetime(s: str) -> datetime:
return datetime.fromisoformat(str(s).strip().replace("Z", "+00:00")).astimezone(UTC)


async def _default_icloud_calendar_url(client: ICloudCalDAVClient) -> str:

cals = await client.list_calendars()
if not cals:
    raise RuntimeError("no iCloud calendars found on this connection")
for cal in cals:
    name = str(cal.get("name") or "").lower()
    if "home" in name or name in ("calendar", "personal"):
        return str(cal["url"])
return str(cals[0]["url"])


async def _graph_client(db: AsyncSession, row: ConnectorConnection) -> GraphClient:
token = await TokenManager.get_valid_access_token(db, row)
return GraphClient(token)


async def _github_client(db: AsyncSession, row: ConnectorConnection) -> GitHubClient:
token = await TokenManager.get_valid_access_token(db, row)
return GitHubClient(token)



