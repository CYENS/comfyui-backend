import hashlib
import json
import logging
import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Asset, Job, RoleName, Workflow, WorkflowModelRequirement, WorkflowVersion
from ..schemas import (
    ModelRequirementOut,
    ModelRequirementUrlUpdate,
    WorkflowCreate,
    WorkflowDetailOut,
    WorkflowDuplicateRequest,
    WorkflowInputsUpdate,
    WorkflowListOut,
    WorkflowParseRequest,
    WorkflowParseResponse,
    WorkflowRequirementsResponse,
    WorkflowUpdate,
)
from ..services.auth import CurrentUser, get_current_user, require_any_role
from ..services.comfy_client import ComfyClient
from ..services.model_requirements import (
    extract_from_api_json,
    extract_from_ui_json,
    validate_download_url,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workflows", tags=["workflows"])


def _hash_prompt(prompt: dict) -> str:
    data = json.dumps(prompt, sort_keys=True).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _parse_prompt_candidates(prompt: dict) -> list[dict]:
    candidates: list[dict] = []
    for node_id, node in prompt.items():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs", {})
        node_type = node.get("class_type")
        if not isinstance(inputs, dict):
            continue
        for key, value in inputs.items():
            if isinstance(value, (list, tuple)):
                continue
            if isinstance(value, bool):
                value_type = "boolean"
            elif isinstance(value, (int, float)):
                value_type = "number"
            elif isinstance(value, str):
                value_type = "string"
            else:
                continue
            candidates.append(
                {
                    "node_id": str(node_id),
                    "node_type": node_type,
                    "path": f"inputs.{key}",
                    "value_type": value_type,
                    "default": value,
                }
            )
    return candidates


def _extract_requirements(
    prompt_json: dict,
    ui_json: dict | None,
) -> list[dict]:
    """Return extracted requirements, preferring ui_json when available."""
    if ui_json is not None:
        return extract_from_ui_json(ui_json)
    return extract_from_api_json(prompt_json)


def _persist_requirements(db: Session, version_id: str, raw: list[dict]) -> None:
    """Delete old requirements for this version and insert new ones."""
    db.query(WorkflowModelRequirement).filter(
        WorkflowModelRequirement.workflow_version_id == version_id
    ).delete()
    for r in raw:
        url = r.get("download_url")
        if url:
            try:
                url = validate_download_url(url)
            except ValueError:
                logger.warning("Discarding invalid download URL for %s: %r", r["model_name"], url)
                url = None
        db.add(
            WorkflowModelRequirement(
                id=str(uuid.uuid4()),
                workflow_version_id=version_id,
                model_name=r["model_name"],
                folder=r["folder"],
                model_type=r["model_type"],
                download_url=url,
                url_approved=False,
            )
        )


@router.post("/parse", response_model=WorkflowParseResponse)
def parse_prompt(payload: WorkflowParseRequest):
    return {"candidate_inputs": _parse_prompt_candidates(payload.prompt_json)}


@router.get("", response_model=list[WorkflowListOut])
def list_workflows(db: Session = Depends(get_db)):
    return db.query(Workflow).order_by(Workflow.created_at.desc()).all()


@router.get("/{workflow_id}", response_model=WorkflowDetailOut)
def get_workflow(workflow_id: str, db: Session = Depends(get_db)):
    wf = db.query(Workflow).filter(Workflow.id == workflow_id).one_or_none()
    if wf is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return wf


@router.post("", response_model=WorkflowDetailOut)
def create_workflow(
    payload: WorkflowCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_any_role(user, RoleName.WORKFLOW_CREATOR)

    existing = db.query(Workflow).filter(Workflow.key == payload.key).one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Workflow key already exists")

    wf = Workflow(
        id=str(uuid.uuid4()),
        key=payload.key,
        name=payload.name,
        description=payload.description,
        created_by_user_id=user.id,
    )
    db.add(wf)
    db.flush()

    ver = WorkflowVersion(
        id=str(uuid.uuid4()),
        workflow_id=wf.id,
        version_number=1,
        prompt_json=payload.prompt_json,
        inputs_schema_json=payload.inputs_schema_json,
        prompt_hash=_hash_prompt(payload.prompt_json),
        created_by_user_id=user.id,
        change_note=payload.change_note,
        is_published=True,
    )
    db.add(ver)
    db.flush()

    wf.current_version_id = ver.id
    db.add(wf)
    db.flush()

    raw_reqs = _extract_requirements(payload.prompt_json, payload.ui_json)
    _persist_requirements(db, ver.id, raw_reqs)

    db.commit()
    db.refresh(wf)
    return wf


@router.patch("/{workflow_id}", response_model=WorkflowDetailOut)
def update_workflow(
    workflow_id: str,
    payload: WorkflowUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    wf = db.query(Workflow).filter(Workflow.id == workflow_id).one_or_none()
    if wf is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    is_admin = user.has(RoleName.ADMIN)
    if not is_admin:
        require_any_role(user, RoleName.WORKFLOW_CREATOR)
        if wf.created_by_user_id != user.id:
            raise HTTPException(
                status_code=403, detail="Cannot edit workflows owned by other users"
            )

    if payload.name is not None:
        wf.name = payload.name
    if payload.description is not None:
        wf.description = payload.description

    if payload.prompt_json is not None or payload.inputs_schema_json is not None:
        current = (
            db.query(WorkflowVersion)
            .filter(WorkflowVersion.id == wf.current_version_id)
            .one_or_none()
        )
        next_version = 1
        if current is not None:
            next_version = current.version_number + 1

        prompt_json = (
            payload.prompt_json
            if payload.prompt_json is not None
            else (current.prompt_json if current else {})
        )
        inputs_schema_json = (
            payload.inputs_schema_json
            if payload.inputs_schema_json is not None
            else (current.inputs_schema_json if current else None)
        )

        ver = WorkflowVersion(
            id=str(uuid.uuid4()),
            workflow_id=wf.id,
            version_number=next_version,
            prompt_json=prompt_json,
            inputs_schema_json=inputs_schema_json,
            prompt_hash=_hash_prompt(prompt_json),
            created_by_user_id=user.id,
            change_note=payload.change_note,
            is_published=True,
        )
        db.add(ver)
        db.flush()
        wf.current_version_id = ver.id

        if payload.prompt_json is not None:
            raw_reqs = _extract_requirements(prompt_json, payload.ui_json)
            _persist_requirements(db, ver.id, raw_reqs)

    db.add(wf)
    db.commit()
    db.refresh(wf)
    return wf


@router.post("/{workflow_id}/duplicate", response_model=WorkflowDetailOut)
def duplicate_workflow(
    workflow_id: str,
    payload: WorkflowDuplicateRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_any_role(user, RoleName.WORKFLOW_CREATOR)

    source = db.query(Workflow).filter(Workflow.id == workflow_id).one_or_none()
    if source is None or source.current_version is None:
        raise HTTPException(status_code=404, detail="Source workflow not found")

    existing = db.query(Workflow).filter(Workflow.key == payload.key).one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Workflow key already exists")

    wf = Workflow(
        id=str(uuid.uuid4()),
        key=payload.key,
        name=payload.name,
        description=payload.description,
        created_by_user_id=user.id,
        parent_workflow_id=source.id,
    )
    db.add(wf)
    db.flush()

    src = source.current_version
    ver = WorkflowVersion(
        id=str(uuid.uuid4()),
        workflow_id=wf.id,
        version_number=1,
        prompt_json=src.prompt_json,
        inputs_schema_json=src.inputs_schema_json,
        prompt_hash=src.prompt_hash,
        created_by_user_id=user.id,
        change_note=f"Duplicated from {source.key}",
        is_published=True,
    )
    db.add(ver)
    db.flush()

    # Copy requirements from the source version (without URL approval)
    raw_reqs = extract_from_api_json(src.prompt_json)
    _persist_requirements(db, ver.id, raw_reqs)

    wf.current_version_id = ver.id
    db.add(wf)
    db.commit()
    db.refresh(wf)
    return wf


@router.put("/{workflow_id}/inputs", response_model=WorkflowDetailOut)
def update_workflow_inputs(
    workflow_id: str,
    payload: WorkflowInputsUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    return update_workflow(
        workflow_id,
        WorkflowUpdate(inputs_schema_json=payload.inputs_schema_json, change_note="inputs updated"),
        db,
        user,
    )


@router.delete("/{workflow_id}")
def delete_workflow(
    workflow_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    wf = db.query(Workflow).filter(Workflow.id == workflow_id).one_or_none()
    if wf is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    is_admin = user.has(RoleName.ADMIN)
    if not is_admin:
        require_any_role(user, RoleName.WORKFLOW_CREATOR)
        if wf.created_by_user_id != user.id:
            raise HTTPException(
                status_code=403, detail="Cannot delete workflows owned by other users"
            )

        has_assets = (
            db.query(Asset)
            .join(Job, Asset.job_id == Job.id)
            .filter(Job.workflow_id == wf.id)
            .first()
            is not None
        )
        if has_assets:
            raise HTTPException(
                status_code=409,
                detail="Workflow has generated assets and cannot be deleted",
            )

    db.delete(wf)
    db.commit()
    return {"status": "deleted"}


@router.get("/{workflow_id}/requirements", response_model=WorkflowRequirementsResponse)
async def get_workflow_requirements(
    workflow_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    wf = db.query(Workflow).filter(Workflow.id == workflow_id).one_or_none()
    if wf is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    if wf.current_version is None:
        return WorkflowRequirementsResponse(requirements=[], all_available=True, missing=[])

    reqs = wf.current_version.model_requirements
    if not reqs:
        return WorkflowRequirementsResponse(requirements=[], all_available=True, missing=[])

    req_dicts = [
        {"folder": r.folder, "model_name": r.model_name, "model_type": r.model_type, "_id": r.id}
        for r in reqs
    ]

    try:
        async with ComfyClient() as client:
            enriched = await client.check_models_available(req_dicts)
    except (httpx.ConnectError, httpx.ConnectTimeout):
        raise HTTPException(status_code=503, detail="ComfyUI is unreachable")

    # Build response, merging DB fields with availability result
    req_by_id = {r.id: r for r in reqs}
    out_list: list[ModelRequirementOut] = []
    for item in enriched:
        db_req = req_by_id[item["_id"]]
        out_list.append(
            ModelRequirementOut(
                id=db_req.id,
                model_name=db_req.model_name,
                folder=db_req.folder,
                model_type=db_req.model_type,
                download_url=db_req.download_url,
                url_approved=db_req.url_approved,
                approved_by_username=db_req.approved_by.username if db_req.approved_by else None,
                approved_at=db_req.approved_at,
                available=item["available"],
            )
        )

    missing = [r for r in out_list if not r.available]
    return WorkflowRequirementsResponse(
        requirements=out_list,
        all_available=len(missing) == 0,
        missing=missing,
    )


@router.patch(
    "/{workflow_id}/requirements/{req_id}",
    response_model=ModelRequirementOut,
)
def update_requirement_url(
    workflow_id: str,
    req_id: str,
    payload: ModelRequirementUrlUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    wf = db.query(Workflow).filter(Workflow.id == workflow_id).one_or_none()
    if wf is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    is_admin = user.has(RoleName.ADMIN)
    if not is_admin:
        require_any_role(user, RoleName.WORKFLOW_CREATOR)
        if wf.created_by_user_id != user.id:
            raise HTTPException(
                status_code=403, detail="Cannot edit requirements for workflows you do not own"
            )

    req = (
        db.query(WorkflowModelRequirement)
        .filter(
            WorkflowModelRequirement.id == req_id,
            WorkflowModelRequirement.workflow_version_id == wf.current_version_id,
        )
        .one_or_none()
    )
    if req is None:
        raise HTTPException(status_code=404, detail="Model requirement not found")

    try:
        validated_url = validate_download_url(payload.download_url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    req.download_url = validated_url
    req.url_approved = False
    req.approved_by_user_id = None
    req.approved_at = None
    db.commit()
    db.refresh(req)

    return ModelRequirementOut(
        id=req.id,
        model_name=req.model_name,
        folder=req.folder,
        model_type=req.model_type,
        download_url=req.download_url,
        url_approved=req.url_approved,
        approved_by_username=None,
        approved_at=None,
        available=None,
    )
