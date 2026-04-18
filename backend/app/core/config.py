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
