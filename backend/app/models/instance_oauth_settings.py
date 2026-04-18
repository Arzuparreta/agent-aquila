from __future__ import annotations

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class InstanceOAuthSettings(Base, TimestampMixin):
    """Singleton row (id=1) for OAuth *application* credentials (Google + Microsoft) from the UI.

    ``google_oauth_redirect_base`` is the shared public API origin used for both providers'
    callback URLs. User refresh tokens live on ``ConnectorConnection`` rows.
    """

    __tablename__ = "instance_oauth_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    google_oauth_client_id: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    google_oauth_client_secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    google_oauth_redirect_base: Mapped[str] = mapped_column(String(1024), default="", nullable=False)
    microsoft_oauth_client_id: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    microsoft_oauth_client_secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    microsoft_oauth_tenant: Mapped[str] = mapped_column(String(64), default="", nullable=False)
