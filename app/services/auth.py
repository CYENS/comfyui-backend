from dataclasses import dataclass
from typing import Optional

from fastapi import Header, HTTPException

from ..models import RoleName


@dataclass
class CurrentUser:
    id: str
    roles: set[RoleName]

    def has(self, role: RoleName) -> bool:
        return role in self.roles

    def has_any(self, *roles: RoleName) -> bool:
        return any(r in self.roles for r in roles)


async def get_current_user(
    x_user_id: Optional[str] = Header(default=None),
    x_user_roles: Optional[str] = Header(default=None),
) -> CurrentUser:
    # MVP stub auth: trust headers; default local dev admin
    if x_user_id is None:
        return CurrentUser(id="dev-admin", roles={RoleName.ADMIN})

    if not x_user_roles:
        return CurrentUser(id=x_user_id, roles={RoleName.VIEWER})

    parsed: set[RoleName] = set()
    for raw in x_user_roles.split(","):
        item = raw.strip().lower()
        if not item:
            continue
        try:
            parsed.add(RoleName(item))
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail=f"Invalid role: {item}"
            ) from exc

    if not parsed:
        parsed = {RoleName.VIEWER}

    return CurrentUser(id=x_user_id, roles=parsed)


def require_any_role(user: CurrentUser, *roles: RoleName) -> None:
    if user.has(RoleName.ADMIN):
        return
    if not user.has_any(*roles):
        raise HTTPException(status_code=403, detail="Forbidden")
