import enum
from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class RoleName(str, enum.Enum):
    ADMIN = "admin"
    WORKFLOW_CREATOR = "workflow_creator"
    JOB_CREATOR = "job_creator"
    VIEWER = "viewer"
    MODERATOR = "moderator"


class JobStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    SUBMITTED = "SUBMITTED"
    RUNNING = "RUNNING"
    GENERATED = "GENERATED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class AssetType(str, enum.Enum):
    IMAGE = "IMAGE"
    AUDIO = "AUDIO"
    VIDEO = "VIDEO"
    MODEL = "MODEL"
    OTHER = "OTHER"


class ValidationStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ExportStatus(str, enum.Enum):
    NOT_EXPORTED = "NOT_EXPORTED"
    EXPORTED = "EXPORTED"


class UserRole(Base):
    __tablename__ = "user_roles"

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    username: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )

    roles: Mapped[list["Role"]] = relationship("Role", secondary="user_roles", back_populates="users")
    jobs: Mapped[list["Job"]] = relationship("Job", back_populates="user")
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        "RefreshToken", back_populates="user", cascade="all, delete-orphan"
    )
    workflows_created: Mapped[list["Workflow"]] = relationship(
        "Workflow",
        back_populates="created_by",
        foreign_keys="Workflow.created_by_user_id",
    )


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[RoleName] = mapped_column(Enum(RoleName), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    users: Mapped[list["User"]] = relationship("User", secondary="user_roles", back_populates="roles")


class Workflow(Base):
    __tablename__ = "workflows"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    parent_workflow_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("workflows.id"), nullable=True)
    current_version_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("workflow_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )

    created_by: Mapped["User"] = relationship(
        "User",
        back_populates="workflows_created",
        foreign_keys="Workflow.created_by_user_id",
    )
    parent_workflow: Mapped[Optional["Workflow"]] = relationship("Workflow", remote_side="Workflow.id")
    versions: Mapped[list["WorkflowVersion"]] = relationship(
        "WorkflowVersion",
        back_populates="workflow",
        cascade="all, delete-orphan",
        foreign_keys="WorkflowVersion.workflow_id",
    )
    current_version: Mapped[Optional["WorkflowVersion"]] = relationship(
        "WorkflowVersion", foreign_keys="Workflow.current_version_id", post_update=True
    )
    jobs: Mapped[list["Job"]] = relationship("Job", back_populates="workflow", cascade="all, delete-orphan")


class WorkflowVersion(Base):
    __tablename__ = "workflow_versions"
    __table_args__ = (
        UniqueConstraint(
            "workflow_id", "version_number", name="uq_workflow_version_num"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    inputs_schema_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    prompt_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    created_by_user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    change_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_published: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    workflow: Mapped["Workflow"] = relationship(
        "Workflow", back_populates="versions", foreign_keys="WorkflowVersion.workflow_id"
    )
    jobs: Mapped[list["Job"]] = relationship("Job", back_populates="workflow_version")
    model_requirements: Mapped[list["WorkflowModelRequirement"]] = relationship(
        "WorkflowModelRequirement",
        back_populates="workflow_version",
        cascade="all, delete-orphan",
    )


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    comfy_job_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    workflow_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False
    )
    workflow_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workflow_versions.id"), nullable=False
    )
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), nullable=False, default=JobStatus.QUEUED)
    start_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    end_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )

    user: Mapped["User"] = relationship("User", back_populates="jobs")
    workflow: Mapped["Workflow"] = relationship("Workflow", back_populates="jobs")
    workflow_version: Mapped["WorkflowVersion"] = relationship("WorkflowVersion", back_populates="jobs")
    input_values: Mapped[list["JobInputValue"]] = relationship(
        "JobInputValue", back_populates="job", cascade="all, delete-orphan"
    )
    assets: Mapped[list["Asset"]] = relationship("Asset", back_populates="job", cascade="all, delete-orphan")


class JobInputValue(Base):
    __tablename__ = "job_input_values"
    __table_args__ = (UniqueConstraint("job_id", "input_id", name="uq_job_input"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    input_id: Mapped[str] = mapped_column(String(128), nullable=False)
    value_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    job: Mapped["Job"] = relationship("Job", back_populates="input_values")


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    workflow_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False
    )
    workflow_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workflow_versions.id"), nullable=False
    )
    type: Mapped[AssetType] = mapped_column(Enum(AssetType), nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    original_filename: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    media_type: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    job: Mapped["Job"] = relationship("Job", back_populates="assets")
    validations: Mapped[list["AssetValidation"]] = relationship(
        "AssetValidation", back_populates="asset", cascade="all, delete-orphan"
    )
    validation_current: Mapped[Optional["AssetValidationCurrent"]] = relationship(
        "AssetValidationCurrent",
        back_populates="asset",
        uselist=False,
        cascade="all, delete-orphan",
    )
    export: Mapped[Optional["AssetExport"]] = relationship(
        "AssetExport",
        back_populates="asset",
        uselist=False,
        cascade="all, delete-orphan",
    )


class AssetValidation(Base):
    __tablename__ = "asset_validations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    asset_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("assets.id", ondelete="CASCADE"), nullable=False
    )
    moderator_user_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    status: Mapped[ValidationStatus] = mapped_column(
        Enum(ValidationStatus), nullable=False, default=ValidationStatus.PENDING
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    validated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    asset: Mapped["Asset"] = relationship("Asset", back_populates="validations")


class AssetValidationCurrent(Base):
    __tablename__ = "asset_validation_current"

    asset_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[ValidationStatus] = mapped_column(
        Enum(ValidationStatus), nullable=False, default=ValidationStatus.PENDING
    )
    moderator_user_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    validated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )

    asset: Mapped["Asset"] = relationship("Asset", back_populates="validation_current")


class AssetExport(Base):
    __tablename__ = "asset_exports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    asset_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("assets.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[ExportStatus] = mapped_column(
        Enum(ExportStatus), nullable=False, default=ExportStatus.NOT_EXPORTED
    )
    export_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    manifest_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    exported_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    asset: Mapped["Asset"] = relationship("Asset", back_populates="export")


class WorkflowModelRequirement(Base):
    __tablename__ = "workflow_model_requirements"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workflow_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workflow_versions.id", ondelete="CASCADE"), nullable=False
    )
    model_name: Mapped[str] = mapped_column(String(512), nullable=False)
    folder: Mapped[str] = mapped_column(String(128), nullable=False)
    model_type: Mapped[str] = mapped_column(String(64), nullable=False)
    download_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    url_approved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    approved_by_user_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    workflow_version: Mapped["WorkflowVersion"] = relationship("WorkflowVersion", back_populates="model_requirements")
    approved_by: Mapped[Optional["User"]] = relationship("User", foreign_keys=[approved_by_user_id])


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    user: Mapped["User"] = relationship("User", back_populates="refresh_tokens")
