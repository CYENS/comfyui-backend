from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Asset, AssetValidationCurrent, Job, RoleName, ValidationStatus
from ..schemas import AssetOut
from ..services.auth import CurrentUser, get_current_user

router = APIRouter(prefix="/assets", tags=["assets"])


def _asset_to_out(asset: Asset) -> AssetOut:
    status = asset.validation_current.status if asset.validation_current else None
    return AssetOut(
        id=asset.id,
        job_id=asset.job_id,
        workflow_id=asset.workflow_id,
        workflow_version_id=asset.workflow_version_id,
        type=asset.type,
        file_path=asset.file_path,
        size_bytes=asset.size_bytes,
        checksum_sha256=asset.checksum_sha256,
        media_type=asset.media_type,
        validation_status=status,
    )


@router.get("", response_model=list[AssetOut])
def list_assets(
    mine: bool = True,
    workflow_id: str | None = None,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    q = db.query(Asset)

    if workflow_id:
        q = q.filter(Asset.workflow_id == workflow_id)

    if mine and not user.has(RoleName.ADMIN):
        q = q.join(Job).filter(Job.user_id == user.id)

    # Non-moderator/admin can only see approved assets
    if not user.has(RoleName.ADMIN) and not user.has(RoleName.MODERATOR):
        q = q.join(
            AssetValidationCurrent, AssetValidationCurrent.asset_id == Asset.id
        ).filter(AssetValidationCurrent.status == ValidationStatus.APPROVED)

    assets = q.order_by(Asset.created_at.desc()).all()
    return [_asset_to_out(asset) for asset in assets]


@router.get("/{asset_id}", response_model=AssetOut)
def get_asset(
    asset_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    asset = db.query(Asset).filter(Asset.id == asset_id).one_or_none()
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")

    if not user.has(RoleName.ADMIN) and not user.has(RoleName.MODERATOR):
        if (
            asset.validation_current is None
            or asset.validation_current.status != ValidationStatus.APPROVED
        ):
            raise HTTPException(status_code=403, detail="Forbidden")

    return _asset_to_out(asset)
