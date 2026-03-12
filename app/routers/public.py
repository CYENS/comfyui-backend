from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Asset, AssetValidationCurrent, ValidationStatus
from ..schemas import PublicAssetOut

router = APIRouter(prefix="/public/assets", tags=["public"])


def _public_asset_out(asset: Asset, base_url: str) -> PublicAssetOut:
    return PublicAssetOut(
        id=asset.id,
        workflow_id=asset.workflow_id,
        type=asset.type,
        size_bytes=asset.size_bytes,
        media_type=asset.media_type,
        download_url=f"{base_url}api/public/assets/{asset.id}/download",
    )


def _public_approved_query(db: Session):
    return (
        db.query(Asset)
        .join(AssetValidationCurrent, AssetValidationCurrent.asset_id == Asset.id)
        .filter(
            Asset.is_public.is_(True),
            AssetValidationCurrent.status == ValidationStatus.APPROVED,
        )
    )


@router.get("", response_model=list[PublicAssetOut])
def list_public_assets(request: Request, db: Session = Depends(get_db)):
    base_url = str(request.base_url)
    assets = _public_approved_query(db).order_by(Asset.created_at.desc()).all()
    return [_public_asset_out(a, base_url) for a in assets]


@router.get("/{asset_id}", response_model=PublicAssetOut)
def get_public_asset(asset_id: str, request: Request, db: Session = Depends(get_db)):
    asset = _public_approved_query(db).filter(Asset.id == asset_id).one_or_none()
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    return _public_asset_out(asset, str(request.base_url))


@router.get("/{asset_id}/download")
def download_public_asset(asset_id: str, db: Session = Depends(get_db)):
    asset = _public_approved_query(db).filter(Asset.id == asset_id).one_or_none()
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")

    disk_path = Path(asset.file_path)
    download_name = asset.original_filename or disk_path.name
    if not Path(download_name).suffix:
        download_name += disk_path.suffix or ".bin"
    return FileResponse(
        path=asset.file_path,
        media_type=asset.media_type or "application/octet-stream",
        filename=download_name,
    )
