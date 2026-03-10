import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import RefreshToken, RoleName, User
from ..schemas import (
    AuthLoginRequest,
    AuthLogoutRequest,
    AuthRefreshRequest,
    AuthTokenOut,
    AuthUserOut,
)
from ..security import (
    hash_token,
    issue_access_token,
    issue_refresh_token_value,
    verify_password,
)
from ..limiter import limiter
from ..services.auth import CurrentUser, get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])


def _role_names(user: User) -> list[str]:
    return sorted(role.name.value for role in user.roles)


def _issue_token_pair(db: Session, user: User) -> AuthTokenOut:
    roles = _role_names(user)
    access_token = issue_access_token(user_id=user.id, roles=roles)

    refresh_value = issue_refresh_token_value()
    refresh = RefreshToken(
        id=str(uuid.uuid4()),
        user_id=user.id,
        token_hash=hash_token(refresh_value),
        expires_at=datetime.now(UTC) + timedelta(days=settings.auth_refresh_token_ttl_days),
    )
    db.add(refresh)
    db.commit()

    return AuthTokenOut(
        access_token=access_token,
        token_type="bearer",
        expires_in_seconds=settings.auth_access_token_ttl_minutes * 60,
        refresh_token=refresh_value,
        user=AuthUserOut(id=user.id, username=user.username, roles=roles),
    )


@router.post(
    "/login",
    response_model=AuthTokenOut,
    summary="Authenticate user and issue JWT access + refresh tokens",
)
@limiter.limit("10/minute")
def login(request: Request, payload: AuthLoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == payload.username).one_or_none()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    return _issue_token_pair(db, user)


@router.post(
    "/refresh",
    response_model=AuthTokenOut,
    summary="Rotate refresh token and issue a fresh access token",
)
def refresh(payload: AuthRefreshRequest, db: Session = Depends(get_db)):
    token_hash = hash_token(payload.refresh_token)
    record = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).one_or_none()
    if record is None or record.revoked_at is not None:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    if record.expires_at < datetime.now(UTC):
        raise HTTPException(status_code=401, detail="Refresh token expired")

    user = db.query(User).filter(User.id == record.user_id).one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")

    record.revoked_at = datetime.now(UTC)
    db.add(record)
    db.commit()

    return _issue_token_pair(db, user)


@router.post("/logout", summary="Revoke a refresh token")
def logout(payload: AuthLogoutRequest, db: Session = Depends(get_db)):
    token_hash = hash_token(payload.refresh_token)
    record = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).one_or_none()
    if record is not None and record.revoked_at is None:
        record.revoked_at = datetime.now(UTC)
        db.add(record)
        db.commit()
    return {"status": "ok"}


@router.get("/me", response_model=AuthUserOut, summary="Current authenticated user")
def me(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    if current_user.is_dev_override:
        return AuthUserOut(
            id=current_user.id,
            username=current_user.username or current_user.id,
            roles=sorted(role.value for role in current_user.roles),
        )

    user = db.query(User).filter(User.id == current_user.id).one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return AuthUserOut(id=user.id, username=user.username, roles=_role_names(user))


@router.get("/dev", summary="Development auth mode status")
def dev_status():
    return {
        "auth_dev_mode": settings.auth_dev_mode,
        "default_user_id": settings.auth_dev_user_id if settings.auth_dev_mode else None,
        "default_roles": settings.auth_dev_user_roles if settings.auth_dev_mode else None,
    }
