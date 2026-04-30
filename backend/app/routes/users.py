from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_admin_user, get_current_user
from app.core.security import hash_password
from app.models.user import User
from app.schemas.user import UserCreateRequest, UserRead, UserUpdateRequest
from app.services.auth_service import AuthService

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserRead])
async def list_users(
    _admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> list[UserRead]:
    rows = await db.execute(select(User).order_by(User.id.asc()))
    return [UserRead.model_validate(item) for item in rows.scalars().all()]


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreateRequest,
    _admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> UserRead:
    normalized_email = str(payload.email).strip().lower()
    existing = await db.execute(select(User).where(func.lower(User.email) == normalized_email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")
    if len(payload.password or "") < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 8 characters",
        )
    user = User(
        email=normalized_email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return UserRead.model_validate(user)


@router.patch("/{user_id}", response_model=UserRead)
async def update_user(
    user_id: int,
    payload: UserUpdateRequest,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> UserRead:
    row = await db.execute(select(User).where(User.id == user_id))
    user = row.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if payload.full_name is not None:
        user.full_name = payload.full_name
    if payload.password is not None and payload.password.strip():
        if len(payload.password) < 8:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password must be at least 8 characters",
            )
        user.hashed_password = hash_password(payload.password)
        await AuthService.logout_all_user_sessions(db, user.id)
    if payload.is_active is not None:
        if user.id == admin_user.id and payload.is_active is False:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot deactivate current user")
        user.is_active = payload.is_active
    if payload.is_admin is not None:
        if user.id == admin_user.id and payload.is_admin is False:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot remove your own admin status")
        user.is_admin = payload.is_admin
    if payload.is_active is False:
        await AuthService.logout_all_user_sessions(db, user.id)
    await db.commit()
    await db.refresh(user)
    return UserRead.model_validate(user)


@router.delete("/{user_id}")
async def delete_user(
    user_id: int,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    row = await db.execute(select(User).where(User.id == user_id))
    user = row.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if user.id == admin_user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot delete current user")
    user.is_active = False
    await AuthService.logout_all_user_sessions(db, user.id)
    await db.commit()
    return {"detail": "User deactivated"}
