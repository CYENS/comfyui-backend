import hashlib
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Asset, Job, RoleName, Workflow, WorkflowVersion
from ..schemas import (
    WorkflowCreate,
    WorkflowDetailOut,
    WorkflowDuplicateRequest,
    WorkflowInputsUpdate,
    WorkflowListOut,
    WorkflowParseRequest,
    WorkflowParseResponse,
    WorkflowUpdate,
)
from ..services.auth import CurrentUser, get_current_user, require_any_role

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
        is_active=True,
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
    if payload.is_active is not None:
        wf.is_active = payload.is_active

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
        is_active=True,
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
        WorkflowUpdate(
            inputs_schema_json=payload.inputs_schema_json, change_note="inputs updated"
        ),
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
