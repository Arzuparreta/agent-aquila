"""Per-provider AI configuration row.

One row per ``(user_id, provider_kind)``. Lets the artist keep an OpenAI
config, an Ollama config, a Google AI Studio config, etc. all saved at the
same time and switch between them via the ``active_provider_kind`` pointer
on :class:`app.models.user_ai_settings.UserAISettings`.

The API key is stored using **envelope encryption**:

- ``wrapped_dek`` is a per-row data-encryption key wrapped with the
  long-lived KEK (see :mod:`app.core.envelope_crypto`).
- ``api_key_ciphertext`` is the actual API key encrypted with the DEK.

KEK rotation re-wraps the DEKs only — the ciphertexts never have to be
re-written. See :mod:`app.scripts.rotate_kek`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class UserAIProviderConfig(Base):
    __tablename__ = "user_ai_provider_configs"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "provider_kind",
            name="uq_user_ai_provider_configs_user_kind",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    chat_model: Mapped[str] = mapped_column(String(128), nullable=False, default="", server_default="")
    embedding_model: Mapped[str] = mapped_column(
        String(128), nullable=False, default="", server_default=""
    )
    classify_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    extras: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # Envelope-encrypted API key. Both columns are NULL when no key is set.
    wrapped_dek: Mapped[str | None] = mapped_column(Text, nullable=True)
    api_key_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Last connection-test outcome (drives the green/red status pill in the UI).
    last_test_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_test_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_test_message: Mapped[str | None] = mapped_column(String(512), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    user = relationship("User", back_populates="ai_provider_configs")

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key_ciphertext and self.wrapped_dek)
