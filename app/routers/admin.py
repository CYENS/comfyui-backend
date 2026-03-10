"""
Admin endpoints for reviewing and approving model download URLs, and triggering
server-side model downloads to the ComfyUI models directory.

Role requirements:
  GET  /pending                    — MODERATOR or ADMIN
  POST /{req_id}/approve           — MODERATOR or ADMIN
  POST /{req_id}/reject            — MODERATOR or ADMIN
  POST /{req_id}/download          — ADMIN only
"""

import logging
from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from ..db import get_db
from ..models import RoleName, Workflow, WorkflowModelRequirement, WorkflowVersion
from ..schemas import ModelRequirementOut
from ..services.auth import CurrentUser, get_current_user, require_any_role
from ..services.model_downloader import download_model

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/model-requirements", tags=["admin"])


def _req_to_out(
    req: WorkflowModelRequirement, available: bool | None = None
) -> ModelRequirementOut:
    return ModelRequirementOut(
        id=req.id,
        model_name=req.model_name,
        folder=req.folder,
        model_type=req.model_type,
        download_url=req.download_url,
        url_approved=req.url_approved,
        approved_by_username=req.approved_by.username if req.approved_by else None,
        approved_at=req.approved_at,
        available=available,
    )


def _get_req_or_404(db: Session, req_id: str) -> WorkflowModelRequirement:
    req = (
        db.query(WorkflowModelRequirement)
        .options(joinedload(WorkflowModelRequirement.approved_by))
        .filter(WorkflowModelRequirement.id == req_id)
        .one_or_none()
    )
    if req is None:
        raise HTTPException(status_code=404, detail="Model requirement not found")
    return req


class _PendingOut(ModelRequirementOut):
    workflow_id: str
    workflow_key: str
    workflow_name: str


@router.get("/pending", response_model=list[_PendingOut])
def list_pending_requirements(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Return all requirements that have a download URL but are not yet approved."""
    require_any_role(user, RoleName.MODERATOR)

    rows = (
        db.query(WorkflowModelRequirement, WorkflowVersion, Workflow)
        .join(WorkflowVersion, WorkflowModelRequirement.workflow_version_id == WorkflowVersion.id)
        .join(Workflow, WorkflowVersion.workflow_id == Workflow.id)
        .options(joinedload(WorkflowModelRequirement.approved_by))
        .filter(
            WorkflowModelRequirement.download_url.isnot(None),
            WorkflowModelRequirement.url_approved.is_(False),
        )
        .all()
    )

    return [
        _PendingOut(
            id=req.id,
            model_name=req.model_name,
            folder=req.folder,
            model_type=req.model_type,
            download_url=req.download_url,
            url_approved=req.url_approved,
            approved_by_username=req.approved_by.username if req.approved_by else None,
            approved_at=req.approved_at,
            available=None,
            workflow_id=wf.id,
            workflow_key=wf.key,
            workflow_name=wf.name,
        )
        for req, wv, wf in rows
    ]


@router.post("/{req_id}/approve", response_model=ModelRequirementOut)
def approve_requirement(
    req_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Approve a model download URL. The URL must already be set on the requirement."""
    require_any_role(user, RoleName.MODERATOR)
    req = _get_req_or_404(db, req_id)

    if not req.download_url:
        raise HTTPException(
            status_code=422,
            detail="Cannot approve a requirement with no download URL set",
        )

    req.url_approved = True
    req.approved_by_user_id = user.id
    req.approved_at = datetime.now(UTC)
    db.commit()
    db.refresh(req)
    return _req_to_out(req)


@router.post("/{req_id}/reject", response_model=ModelRequirementOut)
def reject_requirement(
    req_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Clear the download URL and reset approval status."""
    require_any_role(user, RoleName.MODERATOR)
    req = _get_req_or_404(db, req_id)

    req.download_url = None
    req.url_approved = False
    req.approved_by_user_id = None
    req.approved_at = None
    db.commit()
    db.refresh(req)
    return _req_to_out(req)


@router.post("/{req_id}/download")
async def trigger_download(
    req_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """
    Trigger a background download of the model file from its approved URL to
    the ComfyUI models directory. Returns 202 immediately.
    """
    if not user.has(RoleName.ADMIN):
        raise HTTPException(status_code=403, detail="Only admins can trigger model downloads")

    req = _get_req_or_404(db, req_id)

    if not req.download_url:
        raise HTTPException(status_code=422, detail="No download URL set for this requirement")
    if not req.url_approved:
        raise HTTPException(status_code=422, detail="Download URL has not been approved yet")

    background_tasks.add_task(
        _run_download,
        model_name=req.model_name,
        folder=req.folder,
        download_url=req.download_url,
    )

    return {
        "status": "download_started",
        "model_name": req.model_name,
        "folder": req.folder,
    }


async def _run_download(model_name: str, folder: str, download_url: str) -> None:
    try:
        await download_model(model_name=model_name, folder=folder, download_url=download_url)
    except httpx.HTTPStatusError as exc:
        logger.error(
            "Download failed for %s/%s (HTTP %s): %s",
            folder,
            model_name,
            exc.response.status_code,
            exc,
        )
    except Exception as exc:
        logger.error("Download failed for %s/%s: %s", folder, model_name, exc)
