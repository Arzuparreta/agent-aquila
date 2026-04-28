"""Runtime clients for connectors."""
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.connector_connection import ConnectorConnection
    from sqlalchemy.ext.asyncio import AsyncSession

# Forward declarations to avoid circular imports

class GmailClient:
    def __init__(self, db: "AsyncSession", row: "ConnectorConnection") -> None:
        self.db = db
        self.row = row

class GoogleCalendarClient:
    def __init__(self, db: "AsyncSession", row: "ConnectorConnection") -> None:
        self.db = db
        self.row = row

class GoogleDriveClient:
    def __init__(self, db: "AsyncSession", row: "ConnectorConnection") -> None:
        self.db = db
        self.row = row

class GoogleSheetsClient:
    def __init__(self, db: "AsyncSession", row: "ConnectorConnection") -> None:
        self.db = db
        self.row = row

class GoogleDocsClient:
    def __init__(self, db: "AsyncSession", row: "ConnectorConnection") -> None:
        self.db = db
        self.row = row

class GoogleTasksClient:
    def __init__(self, db: "AsyncSession", row: "ConnectorConnection") -> None:
        self.db = db
        self.row = row

class GooglePeopleClient:
    def __init__(self, db: "AsyncSession", row: "ConnectorConnection") -> None:
        self.db = db
        self.row = row

class GitHubClient:
    def __init__(self, db: "AsyncSession", row: "ConnectorConnection") -> None:
        self.db = db
        self.row = row

class SlackClient:
    def __init__(self, db: "AsyncSession", row: "ConnectorConnection") -> None:
        self.db = db
        self.row = row

class TelegramBotClient:
    def __init__(self, db: "AsyncSession", row: "ConnectorConnection") -> None:
        self.db = db
        self.row = row

class DiscordBotClient:
    def __init__(self, db: "AsyncSession", row: "ConnectorConnection") -> None:
        self.db = db
        self.row = row

class LinearClient:
    def __init__(self, db: "AsyncSession", row: "ConnectorConnection") -> None:
        self.db = db
        self.row = row

class NotionClient:
    def __init__(self, db: "AsyncSession", row: "ConnectorConnection") -> None:
        self.db = db
        self.row = row

class ICloudCalDAVClient:
    def __init__(self, row: "ConnectorConnection") -> None:
        self.row = row
    @staticmethod
    def _app_password_creds(row: "ConnectorConnection") -> tuple[str, str, bool]:
        from app.services.connectors.icloud_caldav_client import ConnectorService
        creds = ConnectorService.decrypt_credentials(row)
        user = str(creds.get("username") or creds.get("apple_id") or "").strip()
        pw = str(creds.get("password") or creds.get("app_password") or "")
        china = bool(creds.get("china_mainland"))
        return user, pw, china
    async def default_calendar_url(self) -> str:
        cals = await self.list_calendars()
        if not cals:
            raise RuntimeError("no iCloud calendars found")
        for cal in cals:
            name = str(cal.get("name") or "").lower()
            if "home" in name or name in ("calendar", "personal"):
                return str(cal["url"])
        return str(cals[0]["url"])
    async def list_calendars(self):
        return []

class YoutubeClient:
    def __init__(self, db: "AsyncSession", row: "ConnectorConnection") -> None:
        self.db = db
        self.row = row

def share_file(*args, **kwargs):
    pass

def upload_file(*args, **kwargs):
    pass

class TokenManager:
    @staticmethod
    async def get_valid_access_token(db, row):
        return "token"
    @staticmethod
    async def get_valid_creds(db, row):
        return "token", {}, None
