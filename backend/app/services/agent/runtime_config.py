"""Runtime config service."""
from typing import Any
from app.models.user import User
from app.schemas.agent_runtime_config import (
    AgentRuntimeConfigResolved,
    AgentRuntimeConfigPartial,
)

async def resolve_for_user(db, user):
    """Resolve runtime config for user."""
    from app.services.agent_runtime_config_service import resolve_for_user as _inner
    return await _inner(db, user)

async def merge_stored_with_env(overrides):
    """Merge stored config with env defaults."""
    from app.services.agent_runtime_config_service import merge_stored_with_env as _inner
    return _inner(overrides)

class UserAISettingsService:
    """User AI settings service."""
    @staticmethod
    async def get_or_create(db, user):
        from app.services.user_ai_settings_service import UserAISettingsService as Real
        return await Real.get_or_create(db, user)
    @staticmethod
    async def get_api_key(db, user):
        from app.services.user_ai_settings_service import UserAISettingsService as Real
        return await Real.get_api_key(db, user)
