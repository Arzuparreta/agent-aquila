from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse


def _registration_domain_allowset(raw: str) -> frozenset[str]:
    return frozenset(
        p.strip().lower().lstrip("@") for p in raw.split(",") if p.strip()
    )


def _email_domain_or_400(email: str) -> str:
    parts = str(email).strip().rsplit("@", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid email address")
    return parts[1].lower()


class AuthService:
    @staticmethod
    async def register(db: AsyncSession, payload: RegisterRequest) -> User:
        if not settings.registration_open:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Registration is disabled.",
            )

        email_str = str(payload.email).strip()
        allow_domains = _registration_domain_allowset(settings.registration_email_domain_allowlist)
        if allow_domains:
            dom = _email_domain_or_400(email_str)
            if dom not in allow_domains:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Registration is restricted to approved email domains.",
                )

        if settings.registration_max_users > 0:
            cnt = await db.scalar(select(func.count()).select_from(User))
            if (cnt or 0) >= settings.registration_max_users:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="No additional user accounts are allowed.",
                )

        existing = await db.execute(select(User).where(User.email == email_str))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

        user = User(
            email=email_str,
            hashed_password=hash_password(payload.password),
            full_name=payload.full_name,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user

    @staticmethod
    async def login(db: AsyncSession, payload: LoginRequest) -> TokenResponse:
        result = await db.execute(select(User).where(User.email == payload.email))
        user = result.scalar_one_or_none()
        if not user or not verify_password(payload.password, user.hashed_password):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

        token = create_access_token(subject=user.email)
        return TokenResponse(access_token=token)
