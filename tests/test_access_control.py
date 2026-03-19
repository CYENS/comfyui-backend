import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db import Base, get_db
from app.models import (
    Asset,
    AssetType,
    AssetValidationCurrent,
    Job,
    JobInputValue,
    JobStatus,
    RoleName,
    ValidationStatus,
    Workflow,
    WorkflowVersion,
)
from app.routers import assets, jobs, workflows
from app.security import issue_access_token
from app.seeding import seed_user_with_roles
from app.services.comfy_client import ComfyClient


@pytest.fixture()
def client_and_session(tmp_path, monkeypatch):
    db_path = tmp_path / "test_access_control.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    app = FastAPI()
    app.include_router(workflows.router, prefix="/api")
    app.include_router(jobs.router, prefix="/api")
    app.include_router(assets.router, prefix="/api")

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(settings, "auth_dev_mode", False)

    with TestClient(app) as client:
        db = TestingSessionLocal()
        try:
            yield client, db
        finally:
            db.close()
            app.dependency_overrides.clear()
            engine.dispose()


def _auth_headers(user_id: str, roles: list[RoleName]) -> dict[str, str]:
    token = issue_access_token(user_id=user_id, roles=[role.value for role in roles])
    return {"Authorization": f"Bearer {token}"}


def _create_workflow(db, owner_id: str) -> Workflow:
    workflow = Workflow(
        id=str(uuid.uuid4()),
        key="private-workflow",
        name="Private Workflow",
        description="sensitive",
        author_id=owner_id,
    )
    db.add(workflow)
    db.flush()

    version = WorkflowVersion(
        id=str(uuid.uuid4()),
        workflow_id=workflow.id,
        version_number=1,
        prompt_json={"1": {"class_type": "CLIPTextEncode", "inputs": {"text": "secret"}}},
        inputs_schema_json=[
            {
                "id": "prompt",
                "label": "Prompt",
                "type": "string",
                "required": True,
                "default": "",
                "mapping": [{"node_id": "1", "path": "inputs.text"}],
            }
        ],
        prompt_hash="hash",
        created_by_user_id=owner_id,
        change_note="initial",
        is_published=True,
    )
    db.add(version)
    db.flush()

    workflow.current_version_id = version.id
    db.add(workflow)
    db.commit()
    db.refresh(workflow)
    return workflow


def _create_job(db, workflow_id: str, workflow_version_id: str, user_id: str) -> Job:
    job = Job(
        id=str(uuid.uuid4()),
        user_id=user_id,
        workflow_id=workflow_id,
        workflow_version_id=workflow_version_id,
        status=JobStatus.QUEUED,
    )
    db.add(job)
    db.flush()
    db.add(
        JobInputValue(
            id=str(uuid.uuid4()),
            job_id=job.id,
            input_id="prompt",
            value_json="hidden prompt",
        )
    )
    db.commit()
    db.refresh(job)
    return job


def _create_asset(db, job: Job, tmp_path: Path) -> Asset:
    file_path = tmp_path / f"{job.id}.png"
    file_path.write_bytes(b"asset-bytes")
    asset = Asset(
        id=str(uuid.uuid4()),
        job_id=job.id,
        workflow_id=job.workflow_id,
        workflow_version_id=job.workflow_version_id,
        type=AssetType.IMAGE,
        file_path=str(file_path),
        original_filename="test.png",
        size_bytes=file_path.stat().st_size,
        checksum_sha256="abc123",
        media_type="image/png",
    )
    db.add(asset)
    db.flush()
    db.add(
        AssetValidationCurrent(
            asset_id=asset.id,
            status=ValidationStatus.PENDING,
            moderator_user_id=None,
            validated_at=None,
            notes=None,
        )
    )
    db.commit()
    db.refresh(asset)
    return asset


def test_workflow_reads_require_auth(client_and_session):
    client, db = client_and_session
    owner = seed_user_with_roles(db, "owner", "password", [RoleName.WORKFLOW_CREATOR])
    workflow = _create_workflow(db, owner.id)

    list_res = client.get("/api/workflows")
    detail_res = client.get(f"/api/workflows/{workflow.id}")

    assert list_res.status_code == 401
    assert detail_res.status_code == 401


def test_workflow_detail_hides_graph_for_non_owner(client_and_session):
    client, db = client_and_session
    owner = seed_user_with_roles(db, "owner", "password", [RoleName.WORKFLOW_CREATOR])
    viewer = seed_user_with_roles(db, "runner", "password", [RoleName.JOB_CREATOR])
    workflow = _create_workflow(db, owner.id)

    res = client.get(
        f"/api/workflows/{workflow.id}",
        headers=_auth_headers(viewer.id, [RoleName.JOB_CREATOR]),
    )

    assert res.status_code == 200
    body = res.json()
    assert len(body["versions"]) == 1
    assert body["versions"][0]["inputs_schema_json"] is not None
    assert body["versions"][0]["prompt_json"] is None


def test_jobs_mine_false_forbidden_for_non_moderator(client_and_session):
    client, db = client_and_session
    owner = seed_user_with_roles(db, "owner", "password", [RoleName.WORKFLOW_CREATOR])
    runner = seed_user_with_roles(db, "runner", "password", [RoleName.JOB_CREATOR])
    workflow = _create_workflow(db, owner.id)
    _create_job(db, workflow.id, workflow.current_version_id, runner.id)

    res = client.get(
        "/api/jobs?mine=false",
        headers=_auth_headers(runner.id, [RoleName.JOB_CREATOR]),
    )

    assert res.status_code == 403


def test_jobs_mine_false_allowed_for_admin(client_and_session):
    client, db = client_and_session
    owner = seed_user_with_roles(db, "owner", "password", [RoleName.WORKFLOW_CREATOR])
    runner = seed_user_with_roles(db, "runner", "password", [RoleName.JOB_CREATOR])
    admin = seed_user_with_roles(db, "admin", "password", [RoleName.ADMIN])
    workflow = _create_workflow(db, owner.id)
    job = _create_job(db, workflow.id, workflow.current_version_id, runner.id)

    res = client.get(
        "/api/jobs?mine=false",
        headers=_auth_headers(admin.id, [RoleName.ADMIN]),
    )

    assert res.status_code == 200
    assert [item["id"] for item in res.json()] == [job.id]


def test_cancel_queued_job_marks_failed_with_reason(client_and_session):
    client, db = client_and_session
    owner = seed_user_with_roles(db, "owner", "password", [RoleName.WORKFLOW_CREATOR])
    runner = seed_user_with_roles(db, "runner", "password", [RoleName.JOB_CREATOR])
    workflow = _create_workflow(db, owner.id)
    job = _create_job(db, workflow.id, workflow.current_version_id, runner.id)

    res = client.post(
        f"/api/jobs/{job.id}/cancel",
        headers=_auth_headers(runner.id, [RoleName.JOB_CREATOR]),
    )

    db.refresh(job)
    assert res.status_code == 200
    assert res.json()["status"] == "FAILED"
    assert "Cancelled by user before execution" in res.json()["reason"]
    assert job.status == JobStatus.FAILED


def test_cancel_running_job_interrupts_comfyui(client_and_session, monkeypatch):
    client, db = client_and_session
    owner = seed_user_with_roles(db, "owner", "password", [RoleName.WORKFLOW_CREATOR])
    runner = seed_user_with_roles(db, "runner", "password", [RoleName.JOB_CREATOR])
    workflow = _create_workflow(db, owner.id)
    job = _create_job(db, workflow.id, workflow.current_version_id, runner.id)
    job.status = JobStatus.RUNNING
    job.comfy_job_id = "prompt-123"
    db.add(job)
    db.commit()

    called = {}

    async def fake_interrupt(self, prompt_id: str):
        called["prompt_id"] = prompt_id

    monkeypatch.setattr(ComfyClient, "interrupt_prompt", fake_interrupt)

    res = client.post(
        f"/api/jobs/{job.id}/cancel",
        headers=_auth_headers(runner.id, [RoleName.JOB_CREATOR]),
    )

    db.refresh(job)
    assert res.status_code == 200
    assert res.json()["status"] == "cancellation_requested"
    assert called["prompt_id"] == "prompt-123"
    assert job.status == JobStatus.CANCELLED
    assert "Cancellation requested by user" in job.error_message


def test_asset_owner_can_delete_own_asset(client_and_session, tmp_path):
    client, db = client_and_session
    owner = seed_user_with_roles(db, "owner", "password", [RoleName.WORKFLOW_CREATOR])
    runner = seed_user_with_roles(db, "runner", "password", [RoleName.JOB_CREATOR])
    workflow = _create_workflow(db, owner.id)
    job = _create_job(db, workflow.id, workflow.current_version_id, runner.id)
    asset = _create_asset(db, job, tmp_path)

    res = client.delete(
        f"/api/assets/{asset.id}",
        headers=_auth_headers(runner.id, [RoleName.JOB_CREATOR]),
    )

    assert res.status_code == 200
    assert db.query(Asset).filter(Asset.id == asset.id).one_or_none() is None
    assert not Path(asset.file_path).exists()


def test_admin_can_delete_any_asset(client_and_session, tmp_path):
    client, db = client_and_session
    owner = seed_user_with_roles(db, "owner", "password", [RoleName.WORKFLOW_CREATOR])
    runner = seed_user_with_roles(db, "runner", "password", [RoleName.JOB_CREATOR])
    admin = seed_user_with_roles(db, "admin", "password", [RoleName.ADMIN])
    workflow = _create_workflow(db, owner.id)
    job = _create_job(db, workflow.id, workflow.current_version_id, runner.id)
    asset = _create_asset(db, job, tmp_path)

    res = client.delete(
        f"/api/assets/{asset.id}",
        headers=_auth_headers(admin.id, [RoleName.ADMIN]),
    )

    assert res.status_code == 200
    assert db.query(Asset).filter(Asset.id == asset.id).one_or_none() is None
