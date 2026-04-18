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
