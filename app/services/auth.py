from dataclasses import dataclass
from typing import Annotated

import jwt
from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import RoleName, User
from ..security import decode_access_token


@dataclass
class CurrentUser:
    id: str
    roles: set[RoleName]
    username: str | None = None
    is_dev_override: bool = False

    def has(self, role: RoleName) -> bool:
        return role in self.roles

    def has_any(self, *roles: RoleName) -> bool:
        return any(r in self.roles for r in roles)


def _parse_roles_csv(raw_roles: str) -> set[RoleName]:
    parsed: set[RoleName] = set()
    for raw in raw_roles.split(","):
        item = raw.strip().lower()
        if not item:
            continue
        try:
            parsed.add(RoleName(item))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid role: {item}") from exc
    return parsed


def _dev_override_user(x_user_id: str | None, x_user_roles: str | None) -> CurrentUser:
    user_id = x_user_id or settings.auth_dev_user_id
    raw_roles = x_user_roles or settings.auth_dev_user_roles
    roles = _parse_roles_csv(raw_roles)
    if not roles:
        roles = {RoleName.ADMIN}
    return CurrentUser(id=user_id, roles=roles, username=user_id, is_dev_override=True)


def _token_user(token: str, db: Session) -> CurrentUser:
    try:
        payload = decode_access_token(token)
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc

    token_type = payload.get("typ")
    if token_type != "access":
        raise HTTPException(status_code=401, detail="Invalid token type")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token missing subject")

    role_items = payload.get("roles") or []
    roles: set[RoleName] = set()
    for item in role_items:
        try:
            roles.add(RoleName(item))
        except ValueError:
            continue
    if not roles:
        roles = {RoleName.VIEWER}

    user = db.query(User).filter(User.id == user_id).one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")

    return CurrentUser(id=user.id, roles=roles, username=user.username)


async def get_current_user(
    db: Annotated[Session, Depends(get_db)],
    authorization: Annotated[str | None, Header()] = None,
    x_user_id: Annotated[str | None, Header()] = None,
    x_user_roles: Annotated[str | None, Header()] = None,
) -> CurrentUser:
    if not authorization:
        if settings.auth_dev_mode:
            return _dev_override_user(x_user_id=x_user_id, x_user_roles=x_user_roles)
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid Authorization header")

    return _token_user(parts[1], db)


def require_any_role(user: CurrentUser, *roles: RoleName) -> None:
    if user.has(RoleName.ADMIN):
        return
    if not user.has_any(*roles):
        raise HTTPException(status_code=403, detail="Forbidden")
