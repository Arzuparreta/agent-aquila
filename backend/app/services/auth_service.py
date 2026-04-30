from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import create_access_token, create_refresh_token, hash_password, verify_password
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse


MIN_PASSWORD_LENGTH = 8


def _registration_domain_allowset(raw: str) -> frozenset[str]:
    return frozenset(
        p.strip().lower().lstrip("@") for p in raw.split(",") if p.strip()
    )


def _email_domain_or_400(email: str) -> str:
    parts = str(email).strip().rsplit("@", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid email address")
    return parts[1].lower()


def _normalize_login_email(email: str) -> str:
    """Canonical form for lookup (avoids EmailStr normalization differing from stored `User.email`)."""
    return str(email).strip().lower()


class AuthService:
    @staticmethod
    async def register(db: AsyncSession, payload: RegisterRequest) -> User:
        if len(payload.password or "") < MIN_PASSWORD_LENGTH:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Password must be at least {MIN_PASSWORD_LENGTH} characters",
            )

        user_count = await db.scalar(select(func.count()).select_from(User)) or 0
        is_first_user = user_count == 0

        if not settings.registration_open and not is_first_user:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Registration is disabled.",
            )

        email_str = _normalize_login_email(payload.email)
        allow_domains = _registration_domain_allowset(settings.registration_email_domain_allowlist)
        if allow_domains:
            dom = _email_domain_or_400(email_str)
            if dom not in allow_domains:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Registration is restricted to approved email domains.",
                )

        if settings.registration_max_users > 0 and user_count >= settings.registration_max_users:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No additional user accounts are allowed.",
            )

        existing = await db.execute(select(User).where(func.lower(User.email) == email_str))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

        user = User(
            email=email_str,
            hashed_password=hash_password(payload.password),
            full_name=payload.full_name,
            is_admin=is_first_user,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user

    @staticmethod
    async def login(db: AsyncSession, payload: LoginRequest) -> TokenResponse:
        email_key = _normalize_login_email(payload.email)
        result = await db.execute(select(User).where(func.lower(User.email) == email_key))
        user = result.scalar_one_or_none()
        if not user or not user.is_active or not verify_password(payload.password, user.hashed_password):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

        # Create access token
        access_token = create_access_token(subject=user.email)
        
        # Create refresh token
        refresh_token_str = create_refresh_token(subject=user.email)
        
        # Store refresh token in database
        refresh_token_obj = RefreshToken(
            user_id=user.id,
            token=refresh_token_str,
            expires_at=datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days),
        )
        db.add(refresh_token_obj)
        await db.commit()
        
        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token_str,
            token_type="bearer",
        )

    @staticmethod
    async def refresh_tokens(db: AsyncSession, refresh_token_str: str) -> TokenResponse:
        """Rotate refresh token: validate old, create new tokens, revoke old."""
        # Decode and validate the refresh token
        from app.core.security import decode_token
        payload = decode_token(refresh_token_str)
        
        if not payload or payload.get("type") != "refresh":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
        
        # Check if token exists and is valid in database
        result = await db.execute(
            select(RefreshToken).where(
                RefreshToken.token == refresh_token_str,
                RefreshToken.revoked == False,
                RefreshToken.expires_at > datetime.now(timezone.utc),
            )
        )
        stored_token = result.scalar_one_or_none()
        
        if not stored_token:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token")
        
        # Get the user
        user = await db.execute(select(User).where(User.id == stored_token.user_id))
        user = user.scalar_one_or_none()
        
        if not user or not user.is_active:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")
        
        # Create new tokens
        new_access_token = create_access_token(subject=user.email)
        new_refresh_token_str = create_refresh_token(subject=user.email)
        
        # Revoke old refresh token and store new one
        stored_token.revoked = True
        stored_token.replaced_by_token = new_refresh_token_str
        
        new_refresh_token_obj = RefreshToken(
            user_id=user.id,
            token=new_refresh_token_str,
            expires_at=datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days),
        )
        db.add(new_refresh_token_obj)
        await db.commit()
        
        return TokenResponse(
            access_token=new_access_token,
            refresh_token=new_refresh_token_str,
            token_type="bearer",
        )

    @staticmethod
    async def logout(db: AsyncSession, refresh_token_str: str | None = None) -> None:
        """Revoke refresh token (logout). If no token provided, revoke all user tokens."""
        if refresh_token_str:
            result = await db.execute(
                select(RefreshToken).where(RefreshToken.token == refresh_token_str)
            )
            stored_token = result.scalar_one_or_none()
            if stored_token:
                stored_token.revoked = True
        else:
            # Revoke all tokens for the user (would need user_id - this is a simplified version)
            pass
        await db.commit()

    @staticmethod
    async def logout_all_user_sessions(db: AsyncSession, user_id: int) -> None:
        """Revoke all refresh tokens for a user (logout from all devices)."""
        await db.execute(
            RefreshToken.__table__.update()
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked == False)
            .values(revoked=True)
        )
        await db.commit()

    @staticmethod
    async def change_password(
        db: AsyncSession,
        user: User,
        old_password: str,
        new_password: str,
    ) -> None:
        if not verify_password(old_password, user.hashed_password):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Old password is incorrect")
        if len(new_password or "") < MIN_PASSWORD_LENGTH:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"New password must be at least {MIN_PASSWORD_LENGTH} characters",
            )
        if verify_password(new_password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="New password must be different from the old password",
            )
        user.hashed_password = hash_password(new_password)
        await db.commit()
