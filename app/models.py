import enum
from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import relationship

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

    user_id = Column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role_id = Column(
        String(36), ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
    created_at = Column(DateTime, default=utcnow, nullable=False)


class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True)
    username = Column(String(128), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )

    roles = relationship("Role", secondary="user_roles", back_populates="users")
    jobs = relationship("Job", back_populates="user")
    workflows_created = relationship(
        "Workflow",
        back_populates="created_by",
        foreign_keys="Workflow.created_by_user_id",
    )


class Role(Base):
    __tablename__ = "roles"

    id = Column(String(36), primary_key=True)
    name = Column(Enum(RoleName), unique=True, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)

    users = relationship("User", secondary="user_roles", back_populates="roles")


class Workflow(Base):
    __tablename__ = "workflows"

    id = Column(String(36), primary_key=True)
    key = Column(String(128), unique=True, nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    created_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    parent_workflow_id = Column(String(36), ForeignKey("workflows.id"), nullable=True)
    current_version_id = Column(
        String(36),
        ForeignKey("workflow_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )

    created_by = relationship(
        "User",
        back_populates="workflows_created",
        foreign_keys="Workflow.created_by_user_id",
    )
    parent_workflow = relationship("Workflow", remote_side="Workflow.id")
    versions = relationship(
        "WorkflowVersion",
        back_populates="workflow",
        cascade="all, delete-orphan",
        foreign_keys="WorkflowVersion.workflow_id",
    )
    current_version = relationship(
        "WorkflowVersion", foreign_keys="Workflow.current_version_id", post_update=True
    )
    jobs = relationship("Job", back_populates="workflow", cascade="all, delete-orphan")


class WorkflowVersion(Base):
    __tablename__ = "workflow_versions"
    __table_args__ = (
        UniqueConstraint(
            "workflow_id", "version_number", name="uq_workflow_version_num"
        ),
    )

    id = Column(String(36), primary_key=True)
    workflow_id = Column(
        String(36), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False
    )
    version_number = Column(Integer, nullable=False)
    prompt_json = Column(JSON, nullable=False)
    inputs_schema_json = Column(JSON, nullable=True)
    prompt_hash = Column(String(128), nullable=False)
    created_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    change_note = Column(Text, nullable=True)
    is_published = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)

    workflow = relationship(
        "Workflow", back_populates="versions", foreign_keys="WorkflowVersion.workflow_id"
    )
    jobs = relationship("Job", back_populates="workflow_version")


class Job(Base):
    __tablename__ = "jobs"

    id = Column(String(36), primary_key=True)
    comfy_job_id = Column(String(64), nullable=True, index=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    workflow_id = Column(
        String(36), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False
    )
    workflow_version_id = Column(
        String(36), ForeignKey("workflow_versions.id"), nullable=False
    )
    status = Column(Enum(JobStatus), nullable=False, default=JobStatus.QUEUED)
    start_time = Column(DateTime, nullable=True)
    end_time = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    submitted_at = Column(DateTime, default=utcnow, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )

    user = relationship("User", back_populates="jobs")
    workflow = relationship("Workflow", back_populates="jobs")
    workflow_version = relationship("WorkflowVersion", back_populates="jobs")
    input_values = relationship(
        "JobInputValue", back_populates="job", cascade="all, delete-orphan"
    )
    assets = relationship("Asset", back_populates="job", cascade="all, delete-orphan")


class JobInputValue(Base):
    __tablename__ = "job_input_values"
    __table_args__ = (UniqueConstraint("job_id", "input_id", name="uq_job_input"),)

    id = Column(String(36), primary_key=True)
    job_id = Column(
        String(36), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    input_id = Column(String(128), nullable=False)
    value_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)

    job = relationship("Job", back_populates="input_values")


class Asset(Base):
    __tablename__ = "assets"

    id = Column(String(36), primary_key=True)
    job_id = Column(
        String(36), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    workflow_id = Column(
        String(36), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False
    )
    workflow_version_id = Column(
        String(36), ForeignKey("workflow_versions.id"), nullable=False
    )
    type = Column(Enum(AssetType), nullable=False)
    file_path = Column(Text, nullable=False)
    original_filename = Column(Text, nullable=True)
    size_bytes = Column(BigInteger, nullable=False)
    checksum_sha256 = Column(String(64), nullable=False)
    media_type = Column(String(128), nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)

    job = relationship("Job", back_populates="assets")
    validations = relationship(
        "AssetValidation", back_populates="asset", cascade="all, delete-orphan"
    )
    validation_current = relationship(
        "AssetValidationCurrent",
        back_populates="asset",
        uselist=False,
        cascade="all, delete-orphan",
    )
    export = relationship(
        "AssetExport",
        back_populates="asset",
        uselist=False,
        cascade="all, delete-orphan",
    )


class AssetValidation(Base):
    __tablename__ = "asset_validations"

    id = Column(String(36), primary_key=True)
    asset_id = Column(
        String(36), ForeignKey("assets.id", ondelete="CASCADE"), nullable=False
    )
    moderator_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    status = Column(
        Enum(ValidationStatus), nullable=False, default=ValidationStatus.PENDING
    )
    notes = Column(Text, nullable=True)
    validated_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)

    asset = relationship("Asset", back_populates="validations")


class AssetValidationCurrent(Base):
    __tablename__ = "asset_validation_current"

    asset_id = Column(
        String(36), ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True
    )
    status = Column(
        Enum(ValidationStatus), nullable=False, default=ValidationStatus.PENDING
    )
    moderator_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    validated_at = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)
    updated_at = Column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )

    asset = relationship("Asset", back_populates="validation_current")


class AssetExport(Base):
    __tablename__ = "asset_exports"

    id = Column(String(36), primary_key=True)
    asset_id = Column(
        String(36), ForeignKey("assets.id", ondelete="CASCADE"), nullable=False
    )
    status = Column(
        Enum(ExportStatus), nullable=False, default=ExportStatus.NOT_EXPORTED
    )
    export_path = Column(Text, nullable=True)
    manifest_path = Column(Text, nullable=True)
    exported_at = Column(DateTime, nullable=True)

    asset = relationship("Asset", back_populates="export")
