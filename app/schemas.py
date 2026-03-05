from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel

from .models import ExportStatus, JobStatus, ValidationStatus, AssetType


class WorkflowListOut(BaseModel):
    id: str
    key: str
    name: str
    description: str | None = None
    created_by_user_id: str
    current_version_id: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WorkflowVersionOut(BaseModel):
    id: str
    workflow_id: str
    version_number: int
    prompt_json: dict[str, Any]
    inputs_schema_json: list[dict[str, Any]] | None = None
    prompt_hash: str
    created_by_user_id: str
    change_note: str | None = None
    is_published: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class WorkflowDetailOut(WorkflowListOut):
    versions: list[WorkflowVersionOut]


class WorkflowCreate(BaseModel):
    key: str
    name: str
    description: str | None = None
    prompt_json: dict[str, Any]
    inputs_schema_json: list[dict[str, Any]] | None = None
    change_note: str | None = None


class WorkflowUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    prompt_json: dict[str, Any] | None = None
    inputs_schema_json: list[dict[str, Any]] | None = None
    change_note: str | None = None
    is_active: bool | None = None


class WorkflowDuplicateRequest(BaseModel):
    key: str
    name: str
    description: str | None = None


class WorkflowInputsUpdate(BaseModel):
    inputs_schema_json: list[dict[str, Any]]


class WorkflowParseRequest(BaseModel):
    prompt_json: dict[str, Any]


class WorkflowParseResponse(BaseModel):
    candidate_inputs: list[dict[str, Any]]


class JobCreate(BaseModel):
    workflow_id: str
    workflow_version_id: str | None = None
    params: dict[str, Any]


class JobInputOut(BaseModel):
    input_id: str
    value_json: Any

    model_config = {"from_attributes": True}


class JobOut(BaseModel):
    id: str
    comfy_job_id: Optional[str]
    user_id: str
    workflow_id: str
    workflow_version_id: str
    status: JobStatus
    start_time: Optional[datetime]
    end_time: Optional[datetime]
    error_message: Optional[str]
    submitted_at: datetime
    inputs: list[JobInputOut]


class AssetOut(BaseModel):
    id: str
    job_id: str
    workflow_id: str
    workflow_version_id: str
    type: AssetType
    file_path: str
    size_bytes: int
    checksum_sha256: str
    media_type: Optional[str]
    validation_status: ValidationStatus | None = None


class ValidationUpdate(BaseModel):
    status: ValidationStatus
    notes: Optional[str] = None


class ExportOut(BaseModel):
    id: str
    asset_id: str
    status: ExportStatus
    export_path: Optional[str]
    manifest_path: Optional[str]

    model_config = {"from_attributes": True}


class AuthLoginRequest(BaseModel):
    username: str
    password: str


class AuthRefreshRequest(BaseModel):
    refresh_token: str


class AuthLogoutRequest(BaseModel):
    refresh_token: str


class AuthUserOut(BaseModel):
    id: str
    username: str
    roles: list[str]


class AuthTokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_seconds: int
    refresh_token: str
    user: AuthUserOut
