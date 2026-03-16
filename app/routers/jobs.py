import uuid
from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy.orm import Session, joinedload

from ..db import get_db
from ..models import Job, JobInputValue, JobStatus, RoleName, Workflow, WorkflowVersion
from ..schemas import JobCreate, JobOut
from ..services.auth import CurrentUser, get_current_user, require_any_role
from ..services.comfy_client import ComfyClient

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _job_to_out(job: Job) -> JobOut:
    return JobOut(
        id=job.id,
        comfy_job_id=job.comfy_job_id,
        user_id=job.user_id,
        workflow_id=job.workflow_id,
        workflow_version_id=job.workflow_version_id,
        status=job.status,
        start_time=job.start_time,
        end_time=job.end_time,
        error_message=job.error_message,
        submitted_at=job.submitted_at,
        inputs=[
            {"input_id": item.input_id, "value_json": item.value_json} for item in job.input_values
        ],
    )


@router.post("/upload-image")
async def upload_image(
    file: UploadFile,
    user: CurrentUser = Depends(get_current_user),
):
    require_any_role(user, RoleName.JOB_CREATOR)
    content = await file.read()
    try:
        async with ComfyClient() as client:
            name = await client.upload_image(
                content, file.filename or "upload.png", file.content_type or "image/png"
            )
    except (httpx.ConnectError, httpx.ConnectTimeout):
        raise HTTPException(status_code=503, detail="ComfyUI is unreachable")
    return {"name": name}


@router.post("", response_model=JobOut)
async def create_job(
    payload: JobCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_any_role(user, RoleName.JOB_CREATOR)

    wf = db.query(Workflow).filter(Workflow.id == payload.workflow_id).one_or_none()
    if wf is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    version_id = payload.workflow_version_id or wf.current_version_id
    if version_id is None:
        raise HTTPException(status_code=400, detail="Workflow has no current version")

    wv = (
        db.query(WorkflowVersion)
        .filter(WorkflowVersion.id == version_id, WorkflowVersion.workflow_id == wf.id)
        .one_or_none()
    )
    if wv is None:
        raise HTTPException(status_code=404, detail="Workflow version not found")

    # Preflight: check that all required models are available in ComfyUI
    reqs = wv.model_requirements
    if reqs:
        req_dicts = [
            {
                "folder": r.folder,
                "model_name": r.model_name,
                "model_type": r.model_type,
                "url_approved": r.url_approved,
                "_id": r.id,
            }
            for r in reqs
        ]
        try:
            async with ComfyClient() as client:
                enriched = await client.check_models_available(req_dicts)
        except (httpx.ConnectError, httpx.ConnectTimeout):
            raise HTTPException(status_code=503, detail="ComfyUI is unreachable")

        missing = [r for r in enriched if not r["available"]]
        if missing:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "missing_models",
                    "message": "Workflow requires models not available in ComfyUI",
                    "missing_models": [
                        {
                            "model_name": r["model_name"],
                            "folder": r["folder"],
                            "model_type": r["model_type"],
                            "has_approved_url": r["url_approved"],
                        }
                        for r in missing
                    ],
                },
            )

    job = Job(
        id=str(uuid.uuid4()),
        user_id=user.id,
        workflow_id=wf.id,
        workflow_version_id=wv.id,
        status=JobStatus.QUEUED,
        submitted_at=datetime.now(UTC),
    )
    db.add(job)
    db.flush()

    for input_id, value in payload.params.items():
        db.add(
            JobInputValue(
                id=str(uuid.uuid4()),
                job_id=job.id,
                input_id=input_id,
                value_json=value,
            )
        )

    db.commit()
    db.refresh(job)
    job = db.query(Job).options(joinedload(Job.input_values)).filter(Job.id == job.id).one()
    return _job_to_out(job)


@router.get("", response_model=list[JobOut])
def list_jobs(
    status: JobStatus | None = None,
    mine: bool = True,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    q = db.query(Job).options(joinedload(Job.input_values))
    if mine and not user.has(RoleName.ADMIN):
        q = q.filter(Job.user_id == user.id)
    if status is not None:
        q = q.filter(Job.status == status)
    jobs = q.order_by(Job.submitted_at.desc()).all()
    return [_job_to_out(job) for job in jobs]


@router.get("/{job_id}", response_model=JobOut)
def get_job(
    job_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    job = db.query(Job).options(joinedload(Job.input_values)).filter(Job.id == job_id).one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if not user.has(RoleName.ADMIN) and job.user_id != user.id:
        raise HTTPException(status_code=403, detail="Forbidden")
    return _job_to_out(job)


@router.post("/{job_id}/cancel")
def cancel_job(
    job_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    job = db.query(Job).filter(Job.id == job_id).one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if not user.has(RoleName.ADMIN) and job.user_id != user.id:
        raise HTTPException(status_code=403, detail="Forbidden")

    if job.status in (JobStatus.GENERATED, JobStatus.FAILED, JobStatus.CANCELLED):
        return {"status": job.status}

    job.status = JobStatus.CANCELLED
    db.add(job)
    db.commit()
    return {"status": job.status}
