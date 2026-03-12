from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Asset, AssetValidationCurrent, Job, RoleName, ValidationStatus
from ..schemas import AssetOut, AssetVisibilityUpdate
from ..services.auth import CurrentUser, get_current_user, require_any_role

router = APIRouter(prefix="/assets", tags=["assets"])


def _asset_to_out(asset: Asset) -> AssetOut:
    status = asset.validation_current.status if asset.validation_current else None
    return AssetOut(
        id=asset.id,
        job_id=asset.job_id,
        workflow_id=asset.workflow_id,
        workflow_version_id=asset.workflow_version_id,
        type=asset.type,
        is_public=asset.is_public,
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

    # Non-moderator/admin visibility:
    # - mine=true  => all own assets (including pending/rejected)
    # - mine=false => approved assets from others + all own assets
    if not user.has(RoleName.ADMIN) and not user.has(RoleName.MODERATOR):
        q = q.outerjoin(AssetValidationCurrent, AssetValidationCurrent.asset_id == Asset.id).join(
            Job, Job.id == Asset.job_id
        )
        if not mine:
            q = q.filter(
                or_(
                    Job.user_id == user.id,
                    AssetValidationCurrent.status == ValidationStatus.APPROVED,
                )
            )

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
        is_owner = asset.job is not None and asset.job.user_id == user.id
        is_approved = (
            asset.validation_current is not None
            and asset.validation_current.status == ValidationStatus.APPROVED
        )
        if not is_owner and not is_approved:
            raise HTTPException(status_code=403, detail="Forbidden")

    return _asset_to_out(asset)


@router.get("/{asset_id}/download")
def download_asset(
    asset_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    asset = db.query(Asset).filter(Asset.id == asset_id).one_or_none()
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")

    if not user.has(RoleName.ADMIN) and not user.has(RoleName.MODERATOR):
        is_owner = asset.job is not None and asset.job.user_id == user.id
        is_approved = (
            asset.validation_current is not None
            and asset.validation_current.status == ValidationStatus.APPROVED
        )
        if not is_owner and not is_approved:
            raise HTTPException(status_code=403, detail="Forbidden")

    disk_path = Path(asset.file_path)
    download_name = asset.original_filename or disk_path.name
    if not Path(download_name).suffix:
        download_name += disk_path.suffix or ".bin"
    return FileResponse(
        path=asset.file_path,
        media_type=asset.media_type or "application/octet-stream",
        filename=download_name,
    )


@router.patch("/{asset_id}/visibility", response_model=AssetOut)
def set_asset_visibility(
    asset_id: str,
    payload: AssetVisibilityUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_any_role(user, RoleName.ADMIN)
    asset = db.query(Asset).filter(Asset.id == asset_id).one_or_none()
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    asset.is_public = payload.is_public
    db.commit()
    db.refresh(asset)
    return _asset_to_out(asset)
