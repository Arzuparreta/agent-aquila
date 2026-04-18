from __future__ import annotations

from typing import Self
from urllib.parse import quote_plus

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """DATABASE_URL, when non-empty, is used as-is. Otherwise the URL is built from POSTGRES_* with proper encoding
    (so passwords containing @, :, #, etc. work). Docker Compose clears DATABASE_URL and sets POSTGRES_HOST=db.
    """

    database_url: str = Field(default="", validation_alias="DATABASE_URL")
    postgres_user: str = Field(default="crm_user", validation_alias="POSTGRES_USER")
    postgres_password: str = Field(default="crm_password", validation_alias="POSTGRES_PASSWORD")
    postgres_db: str = Field(default="crm_db", validation_alias="POSTGRES_DB")
    postgres_host: str = Field(default="localhost", validation_alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, validation_alias="POSTGRES_PORT")
    jwt_secret: str = "change_me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    cors_origins: str = "http://localhost:3000,http://localhost:3002,http://127.0.0.1:3002"
    # Fernet key (urlsafe base64, 32 bytes). If unset, a deterministic key is derived from jwt_secret (dev only).
    fernet_encryption_key: str | None = None
    embedding_dimensions: int = 1536
    # Comma-separated email domains allowed for agent-approved outbound mail (empty = allow all).
    agent_email_domain_allowlist: str = Field(default="", validation_alias="AGENT_EMAIL_DOMAIN_ALLOWLIST")
    agent_max_runs_per_hour: int = Field(default=60, ge=1, le=10_000, validation_alias="AGENT_MAX_RUNS_PER_HOUR")
    agent_max_tool_steps: int = Field(default=10, ge=1, le=100, validation_alias="AGENT_MAX_TOOL_STEPS")
    # When false, email ingest never auto-creates deals from triage/rules (aligns with human-gated agent policy).
    email_ingest_auto_create_deals: bool = Field(default=True, validation_alias="EMAIL_INGEST_AUTO_CREATE_DEALS")

    # Redis (used for OAuth state, ARQ worker queue, and sync scheduling). If unset, a local in-memory
    # fallback is used for OAuth state only (single-process dev); workers will refuse to start without it.
    redis_url: str = Field(default="", validation_alias="REDIS_URL")

    # Google OAuth (https://console.cloud.google.com → OAuth 2.0 Client IDs → "Web application").
    # Redirect URI registered in Google must be `${google_oauth_redirect_base}/api/v1/oauth/google/callback`.
    google_oauth_client_id: str = Field(default="", validation_alias="GOOGLE_OAUTH_CLIENT_ID")
    google_oauth_client_secret: str = Field(default="", validation_alias="GOOGLE_OAUTH_CLIENT_SECRET")
    google_oauth_redirect_base: str = Field(
        default="http://localhost:8000", validation_alias="GOOGLE_OAUTH_REDIRECT_BASE"
    )
    # Where to send the browser after a successful callback (usually the Next.js app).
    oauth_post_auth_redirect: str = Field(
        default="http://localhost:3002/settings", validation_alias="OAUTH_POST_AUTH_REDIRECT"
    )

    # Microsoft Graph OAuth (Azure AD app registration). Optional; enables Phase 5.
    microsoft_oauth_client_id: str = Field(default="", validation_alias="MICROSOFT_OAUTH_CLIENT_ID")
    microsoft_oauth_client_secret: str = Field(default="", validation_alias="MICROSOFT_OAUTH_CLIENT_SECRET")
    microsoft_oauth_tenant: str = Field(default="common", validation_alias="MICROSOFT_OAUTH_TENANT")

    # Gmail initial sync cap — how many recent messages to pull on first connect (None = all).
    gmail_initial_sync_max_messages: int = Field(
        default=2000, ge=0, le=200_000, validation_alias="GMAIL_INITIAL_SYNC_MAX_MESSAGES"
    )
    # Delta sync cadence (seconds) per active connection.
    gmail_delta_poll_seconds: int = Field(default=120, ge=30, le=3600, validation_alias="GMAIL_DELTA_POLL_SECONDS")
    calendar_delta_poll_seconds: int = Field(
        default=300, ge=60, le=3600, validation_alias="CALENDAR_DELTA_POLL_SECONDS"
    )
    drive_delta_poll_seconds: int = Field(default=300, ge=60, le=3600, validation_alias="DRIVE_DELTA_POLL_SECONDS")

    # Web Push (VAPID). Generate via `vapid --gen` (web-push CLI) or any standard generator.
    # Both private and public keys are required to send notifications. The public key is also
    # exposed via /push/public-key so the FE can subscribe.
    vapid_public_key: str = Field(default="", validation_alias="VAPID_PUBLIC_KEY")
    vapid_private_key: str = Field(default="", validation_alias="VAPID_PRIVATE_KEY")
    vapid_contact_email: str = Field(
        default="mailto:admin@example.com", validation_alias="VAPID_CONTACT_EMAIL"
    )

    # Local file storage root for artist-uploaded Archivos. Created on first write.
    upload_dir: str = Field(default="./uploads", validation_alias="UPLOAD_DIR")
    max_upload_bytes: int = Field(
        default=25 * 1024 * 1024, ge=1024, le=200 * 1024 * 1024, validation_alias="MAX_UPLOAD_BYTES"
    )

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @model_validator(mode="after")
    def resolve_database_url(self) -> Self:
        raw = (self.database_url or "").strip()
        if raw:
            self.database_url = raw
            return self
        user = quote_plus(self.postgres_user)
        password = quote_plus(self.postgres_password)
        self.database_url = (
            f"postgresql+asyncpg://{user}:{password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )
        return self


settings = Settings()
