from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, selectinload

from ..db import get_db
from ..models import User
from ..schemas import AuthUserOut
from ..services.auth import CurrentUser, get_current_user

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[AuthUserOut])
def list_users(
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(get_current_user),
):
    users = db.query(User).options(selectinload(User.roles)).order_by(User.username).all()
    return [
        AuthUserOut(id=u.id, username=u.username, roles=[r.name.value for r in u.roles])
        for u in users
    ]
