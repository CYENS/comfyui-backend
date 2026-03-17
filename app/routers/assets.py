from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload, selectinload

from ..db import get_db
from ..models import Asset, AssetValidationCurrent, Job, RoleName, ValidationStatus
from ..schemas import AssetOut, AssetVisibilityUpdate
from ..services.auth import CurrentUser, get_current_user, require_any_role

router = APIRouter(prefix="/assets", tags=["assets"])


_ASSET_LOADS = [
    joinedload(Asset.validation_current),
    selectinload(Asset.job).selectinload(Job.user),
    selectinload(Asset.job).selectinload(Job.workflow),
    selectinload(Asset.job).selectinload(Job.workflow_version),
]


def _asset_to_out(asset: Asset) -> AssetOut:
    job = asset.job
    status = asset.validation_current.status if asset.validation_current else None
    return AssetOut(
        id=asset.id,
        job_id=asset.job_id,
        workflow_id=asset.workflow_id,
        workflow_version_id=asset.workflow_version_id,
        type=asset.type,
        is_public=asset.is_public,
        file_path=asset.file_path,
        filename=asset.original_filename,
        size_bytes=asset.size_bytes,
        checksum_sha256=asset.checksum_sha256,
        media_type=asset.media_type,
        thumbnail_url=f"/api/assets/{asset.id}/thumbnail" if asset.thumbnail_path else None,
        validation_status=status,
        created_at=asset.created_at,
        author=job.user.username if job and job.user else None,
        workflow_name=job.workflow.name if job and job.workflow else None,
        workflow_version=job.workflow_version.version_number
        if job and job.workflow_version
        else None,
        job_submitted_at=job.submitted_at if job else None,
    )


@router.get("", response_model=list[AssetOut])
def list_assets(
    mine: bool = True,
    workflow_id: str | None = None,
    job_id: str | None = None,
    user_id: str | None = None,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    q = db.query(Asset).options(*_ASSET_LOADS)

    if workflow_id:
        q = q.filter(Asset.workflow_id == workflow_id)

    if job_id:
        q = q.filter(Asset.job_id == job_id)

    if user_id:
        # Filter by specific user via subquery to avoid join conflicts
        q = q.filter(Asset.job_id.in_(db.query(Job.id).filter(Job.user_id == user_id)))
    elif mine and not user.has(RoleName.ADMIN):
        q = q.filter(Asset.job_id.in_(db.query(Job.id).filter(Job.user_id == user.id)))

    # Non-moderator/admin visibility:
    # - mine=true (no user_id)  => all own assets (including pending/rejected)
    # - mine=false OR user_id   => approved assets from others + all own assets
    if not user.has(RoleName.ADMIN) and not user.has(RoleName.MODERATOR):
        if user_id or not mine:
            own_job_ids = db.query(Job.id).filter(Job.user_id == user.id)
            approved_asset_ids = db.query(AssetValidationCurrent.asset_id).filter(
                AssetValidationCurrent.status == ValidationStatus.APPROVED
            )
            q = q.filter(
                or_(
                    Asset.job_id.in_(own_job_ids),
                    Asset.id.in_(approved_asset_ids),
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
    asset = db.query(Asset).options(*_ASSET_LOADS).filter(Asset.id == asset_id).one_or_none()
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


@router.get("/{asset_id}/thumbnail")
def get_asset_thumbnail(
    asset_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    asset = db.query(Asset).filter(Asset.id == asset_id).one_or_none()
    if asset is None or not asset.thumbnail_path:
        raise HTTPException(status_code=404, detail="Thumbnail not found")

    if not user.has(RoleName.ADMIN) and not user.has(RoleName.MODERATOR):
        is_owner = asset.job is not None and asset.job.user_id == user.id
        is_approved = (
            asset.validation_current is not None
            and asset.validation_current.status == ValidationStatus.APPROVED
        )
        if not is_owner and not is_approved:
            raise HTTPException(status_code=403, detail="Forbidden")

    return FileResponse(path=asset.thumbnail_path, media_type="image/png")


@router.patch("/{asset_id}/visibility", response_model=AssetOut)
def set_asset_visibility(
    asset_id: str,
    payload: AssetVisibilityUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_any_role(user, RoleName.ADMIN)
    asset = db.query(Asset).options(*_ASSET_LOADS).filter(Asset.id == asset_id).one_or_none()
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    asset.is_public = payload.is_public
    db.commit()
    db.refresh(asset)
    return _asset_to_out(asset)


@router.delete("/{asset_id}")
def delete_asset(
    asset_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    asset = db.query(Asset).filter(Asset.id == asset_id).one_or_none()
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")

    is_owner = asset.job is not None and asset.job.user_id == user.id
    if not user.has(RoleName.ADMIN) and not is_owner:
        raise HTTPException(status_code=403, detail="Forbidden")

    disk_path = Path(asset.file_path)
    db.delete(asset)
    db.commit()

    try:
        if disk_path.exists():
            disk_path.unlink()
    except Exception:
        # Deleting the DB record is the primary action; file cleanup is best-effort.
        pass

    return {"status": "deleted"}
