from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import decrypt_secret, encrypt_secret
from app.models.user import User
from app.models.user_ai_settings import UserAISettings
from app.schemas.ai import UserAISettingsRead, UserAISettingsUpdate


class UserAISettingsService:
    @staticmethod
    async def get_or_create(db: AsyncSession, user: User) -> UserAISettings:
        result = await db.execute(select(UserAISettings).where(UserAISettings.user_id == user.id))
        row = result.scalar_one_or_none()
        if row:
            return row
        row = UserAISettings(user_id=user.id)
        db.add(row)
        await db.flush()
        return row

    @staticmethod
    def to_read(row: UserAISettings) -> UserAISettingsRead:
        return UserAISettingsRead(
            provider_kind=row.provider_kind,
            base_url=row.base_url,
            embedding_model=row.embedding_model,
            chat_model=row.chat_model,
            classify_model=row.classify_model,
            ai_disabled=row.ai_disabled,
            has_api_key=bool(row.api_key_encrypted),
            extras=row.extras,
        )

    @staticmethod
    async def update_settings(db: AsyncSession, user: User, payload: UserAISettingsUpdate) -> UserAISettingsRead:
        row = await UserAISettingsService.get_or_create(db, user)
        data = payload.model_dump(exclude_unset=True)
        if data.get("classify_model") == "":
            data["classify_model"] = None
        if "api_key" in data:
            key_val = data.pop("api_key")
            if key_val == "":
                row.api_key_encrypted = None
            elif key_val is not None:
                row.api_key_encrypted = encrypt_secret(key_val)
        for field, value in data.items():
            setattr(row, field, value)
        await db.commit()
        await db.refresh(row)
        return UserAISettingsService.to_read(row)

    @staticmethod
    async def get_api_key(db: AsyncSession, user: User) -> str | None:
        row = await UserAISettingsService.get_or_create(db, user)
        return decrypt_secret(row.api_key_encrypted)
