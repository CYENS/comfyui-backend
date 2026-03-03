import uuid
from datetime import UTC, datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ..db import get_db
from ..models import Asset, AssetExport, ExportStatus, RoleName
from ..schemas import ExportOut
from ..services.auth import get_current_user, CurrentUser, require_any_role

router = APIRouter(prefix="/assets", tags=["export"])


@router.post(
    "/{asset_id}/export",
    response_model=ExportOut,
    summary="Export an asset",
    response_description="Export status",
)
def export_asset(
    asset_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_any_role(user, RoleName.MODERATOR)

    asset = db.query(Asset).filter(Asset.id == asset_id).one_or_none()
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")

    export = (
        db.query(AssetExport).filter(AssetExport.asset_id == asset_id).one_or_none()
    )
    if export is None:
        export = AssetExport(
            id=str(uuid.uuid4()),
            asset_id=asset_id,
            status=ExportStatus.EXPORTED,
            export_path=f"/data/app/exports/{asset_id}",
            manifest_path=f"/data/app/exports/{asset_id}/manifest.json",
            exported_at=datetime.now(UTC),
        )
        db.add(export)
    else:
        export.status = ExportStatus.EXPORTED
        export.exported_at = datetime.now(UTC)

    db.commit()
    db.refresh(export)
    return export
