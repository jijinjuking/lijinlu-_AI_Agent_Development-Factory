"""
AI Runtime OS — 用户认证 API
endpoints: POST /auth/register, /auth/login, /auth/refresh, /auth/me
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import uuid

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.database import async_session_factory, get_db
from app.models.user import User

router = APIRouter(tags=["Auth"])


_scheme = HTTPBearer(auto_error=False)


# ── Schemas ───────────────────────────────────────
class RegisterReq(BaseModel):
    username: str
    password: str
    email: str | None = None
    display_name: str | None = None


class LoginReq(BaseModel):
    username: str
    password: str


class TokenResp(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshReq(BaseModel):
    refresh_token: str


# ── Helpers ──────────────────────────────────────
async def get_current_user(
    cred: HTTPAuthorizationCredentials = Depends(_scheme),
) -> User:
    """从 Authorization header 解析 JWT，返回 User 对象"""
    if not cred:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = decode_token(cred.credentials)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {e}",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not payload or "sub" not in payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user_id_str: str = payload["sub"]
    user_id = uuid.UUID(user_id_str)

    # 手动创建 DB session
    async with async_session_factory() as db:
        user = (
            (await db.execute(select(User).where(User.id == user_id)))
            .scalar_one_or_none()
        )
        if not user or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found or disabled",
            )
        return user


# ── Routes ───────────────────────────────────────
@router.post("/register", response_model=TokenResp)
async def register(req: RegisterReq, db: AsyncSession = Depends(get_db)):
    """注册新用户，返回 access + refresh token"""
    existing = (
        (await db.execute(select(User).where(User.username == req.username)))
        .scalar_one_or_none()
    )
    if existing:
        raise HTTPException(status_code=400, detail="Username already registered")

    # 邮箱可选：空字符串 / 纯空白一律归一为 None，且 None 不参与唯一性校验
    # （否则 `email IS NULL` 会命中其他未填邮箱的老用户，导致注册必然失败）
    email = (req.email or "").strip() or None
    if email:
        existing_email = (
            (await db.execute(select(User).where(User.email == email)))
            .scalar_one_or_none()
        )
        if existing_email:
            raise HTTPException(status_code=400, detail="Email already registered")

    now = datetime.now(timezone.utc)
    user = User(
        username=req.username,
        email=email,
        display_name=req.display_name,
        password_hash=hash_password(req.password),
        role="user",
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    access_token = create_access_token(str(user.id), user.username, user.role, user.tenant_id)
    refresh_token = create_refresh_token(str(user.id))
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": 60 * 24 * 60,  # 7 天（分钟）
    }


@router.post("/login", response_model=TokenResp)
async def login(req: LoginReq, db: AsyncSession = Depends(get_db)):
    """用户名 + 密码登录，返回 access + refresh token"""
    user = (
        (await db.execute(select(User).where(User.username == req.username)))
        .scalar_one_or_none()
    )
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is disabled")

    access_token = create_access_token(str(user.id), user.username, user.role, user.tenant_id)
    refresh_token = create_refresh_token(str(user.id))
    user.last_login_at = datetime.now(timezone.utc)
    await db.commit()
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": 60 * 24 * 60,
    }


@router.post("/refresh", response_model=TokenResp)
async def refresh(req: RefreshReq, db: AsyncSession = Depends(get_db)):
    """用 refresh_token 换取新的 access_token"""
    payload = decode_token(req.refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    user_id_str: str = payload["sub"]
    user_id = uuid.UUID(user_id_str)

    user = (
        (await db.execute(select(User).where(User.id == user_id)))
        .scalar_one_or_none()
    )
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or disabled")

    username: str = payload.get("username", user.username)
    access_token = create_access_token(str(user.id), username, user.role, user.tenant_id)
    return {
        "access_token": access_token,
        "refresh_token": req.refresh_token,
        "token_type": "bearer",
        "expires_in": 60 * 24 * 60,
    }


@router.get("/me")
async def read_users_me(current_user: User = Depends(get_current_user)):
    """获取当前登录用户信息"""
    return {
        "id": str(current_user.id),
        "username": current_user.username,
        "email": current_user.email,
        "display_name": current_user.display_name,
        "role": current_user.role,
        "is_active": current_user.is_active,
        "created_at": current_user.created_at.isoformat() if current_user.created_at else None,
        "last_login_at": current_user.last_login_at.isoformat() if current_user.last_login_at else None,
    }
