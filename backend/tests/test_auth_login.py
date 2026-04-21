"""Auth login behavior (email normalization, password check)."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.user import User
from app.schemas.auth import LoginRequest
from app.services.auth_service import AuthService


@pytest.mark.asyncio
async def test_login_email_is_case_insensitive(db_session: AsyncSession) -> None:
    """Lookup uses lower(email); users with legacy mixed-case rows can still sign in."""
    raw_email = "MixedCase@Example.COM"
    password = "correct-horse-battery-staple"
    user = User(
        email=raw_email,
        hashed_password=hash_password(password),
        full_name="Case Test",
    )
    db_session.add(user)
    await db_session.flush()

    token = await AuthService.login(
        db_session,
        LoginRequest(email="mixedcase@example.com", password=password),
    )
    assert token.access_token
