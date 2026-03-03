import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import (
    Asset,
    AssetValidation,
    AssetValidationCurrent,
    RoleName,
)
from ..schemas import ValidationUpdate
from ..services.auth import CurrentUser, get_current_user, require_any_role

router = APIRouter(prefix="/assets", tags=["review"])


@router.post("/{asset_id}/review")
def review_asset(
    asset_id: str,
    payload: ValidationUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_any_role(user, RoleName.MODERATOR)

    asset = db.query(Asset).filter(Asset.id == asset_id).one_or_none()
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")

    now = datetime.now(UTC)

    review = AssetValidation(
        id=str(uuid.uuid4()),
        asset_id=asset_id,
        moderator_user_id=user.id,
        status=payload.status,
        notes=payload.notes,
        validated_at=now,
    )
    db.add(review)

    current = (
        db.query(AssetValidationCurrent)
        .filter(AssetValidationCurrent.asset_id == asset_id)
        .one_or_none()
    )
    if current is None:
        current = AssetValidationCurrent(
            asset_id=asset_id,
            status=payload.status,
            moderator_user_id=user.id,
            validated_at=now,
            notes=payload.notes,
        )
        db.add(current)
    else:
        current.status = payload.status
        current.moderator_user_id = user.id
        current.validated_at = now
        current.notes = payload.notes
        db.add(current)

    db.commit()
    return {"status": payload.status}
