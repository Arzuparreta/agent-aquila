from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.auth import ChangePasswordRequest, LoginRequest, RegisterRequest, TokenResponse
from app.schemas.user import UserRead
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserRead)
async def register(payload: RegisterRequest, db: AsyncSession = Depends(get_db)) -> UserRead:
    user = await AuthService.register(db, payload)
    return UserRead.model_validate(user)


@router.post("/login")
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)) -> JSONResponse:
    """Login and set refresh token as HTTP-only cookie."""
    token_response = await AuthService.login(db, payload)
    
    response = JSONResponse({
        "access_token": token_response.access_token,
        "token_type": token_response.token_type,
    })
    
    # Set refresh token in HTTP-only cookie
    response.set_cookie(
        key="refresh_token",
        value=token_response.refresh_token,
        max_age=settings.refresh_token_expire_days * 24 * 3600,
        httponly=True,  # Not accessible via JavaScript (XSS protection)
        secure=not settings.jwt_secret == "change_me",  # HTTPS in production
        samesite="lax",  # CSRF protection
    )
    
    return response


@router.post("/refresh")
async def refresh(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Refresh access token using the refresh token from HTTP-only cookie."""
    refresh_token = request.cookies.get("refresh_token")
    
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Refresh token not found")
    
    try:
        token_response = await AuthService.refresh_tokens(db, refresh_token)
    except HTTPException:
        # If refresh fails, clear the cookie
        response = JSONResponse(
            {"detail": "Invalid or expired refresh token"},
            status_code=401,
        )
        response.delete_cookie("refresh_token")
        return response
    
    response = JSONResponse({
        "access_token": token_response.access_token,
        "token_type": token_response.token_type,
    })
    
    # Set new refresh token in HTTP-only cookie (rotation)
    response.set_cookie(
        key="refresh_token",
        value=token_response.refresh_token,
        max_age=settings.refresh_token_expire_days * 24 * 3600,
        httponly=True,
        secure=not settings.jwt_secret == "change_me",
        samesite="lax",
    )
    
    return response


@router.post("/logout")
async def logout(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Logout and revoke refresh token."""
    refresh_token = request.cookies.get("refresh_token")
    
    if refresh_token:
        await AuthService.logout(db, refresh_token)
    
    response = JSONResponse({"detail": "Successfully logged out"})
    response.delete_cookie("refresh_token")
    return response


@router.get("/me", response_model=UserRead)
async def me(current_user: User = Depends(get_current_user)) -> UserRead:
    return UserRead.model_validate(current_user)


@router.post("/change-password")
async def change_password(
    payload: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    await AuthService.change_password(db, current_user, payload.old_password, payload.new_password)
    return {"detail": "Password updated"}
