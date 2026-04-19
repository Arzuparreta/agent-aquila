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
    # POST /auth/register — disable after your account exists on a private instance.
    registration_open: bool = Field(default=True, validation_alias="REGISTRATION_OPEN")
    # Comma-separated lowercase domains (no @). Empty = any domain when registration_open is true.
    registration_email_domain_allowlist: str = Field(
        default="", validation_alias="REGISTRATION_EMAIL_DOMAIN_ALLOWLIST"
    )
    # 0 = unlimited. Set to 1 for single-tenant (only the first account may register).
    registration_max_users: int = Field(default=0, ge=0, le=1_000_000, validation_alias="REGISTRATION_MAX_USERS")
    cors_origins: str = "http://localhost:3000,http://localhost:3002,http://127.0.0.1:3002"
    # Fernet key (urlsafe base64, 32 bytes). If unset, a deterministic key is derived from jwt_secret (dev only).
    fernet_encryption_key: str | None = None
    embedding_dimensions: int = 1536
    # Comma-separated email domains allowed for agent-approved outbound mail (empty = allow all).
    agent_email_domain_allowlist: str = Field(default="", validation_alias="AGENT_EMAIL_DOMAIN_ALLOWLIST")
    agent_max_runs_per_hour: int = Field(default=60, ge=1, le=10_000, validation_alias="AGENT_MAX_RUNS_PER_HOUR")
    agent_max_tool_steps: int = Field(default=10, ge=1, le=100, validation_alias="AGENT_MAX_TOOL_STEPS")
    # Hard cap on proactive agent heartbeat runs per user/hour. 0 disables the cap.
    agent_heartbeat_burst_per_hour: int = Field(
        default=20, ge=0, le=10_000, validation_alias="AGENT_HEARTBEAT_BURST_PER_HOUR"
    )

    # Redis (used for OAuth state and the ARQ heartbeat worker). If unset, a local in-memory
    # fallback is used for OAuth state only (single-process dev); the heartbeat worker will
    # refuse to start without it.
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

    # ------------------------------------------------------------------
    # OpenClaw-style agent infrastructure
    # ------------------------------------------------------------------
    # Optional override for the agent skills folder. Defaults to
    # ``backend/skills/`` shipped with the app; override it to mount
    # a custom skill set from a docker volume without rebuilding.
    skills_dir: str = Field(default="", validation_alias="AQUILA_SKILLS_DIR")
    # OpenClaw-style workspace (SOUL.md, AGENTS.md). Default: ``backend/agent_workspace``.
    workspace_dir: str = Field(default="", validation_alias="AQUILA_WORKSPACE_DIR")
    # Heartbeat: when true, the worker runs ``agent_heartbeat`` every
    # ``agent_heartbeat_minutes`` minutes (defaults to off so freshly
    # cloned dev setups never spawn surprise LLM calls).
    agent_heartbeat_enabled: bool = Field(
        default=False, validation_alias="AGENT_HEARTBEAT_ENABLED"
    )
    agent_heartbeat_minutes: int = Field(
        default=15, ge=1, le=1440, validation_alias="AGENT_HEARTBEAT_MINUTES"
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
