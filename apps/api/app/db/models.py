from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

JSON_DOCUMENT = JSON().with_variant(JSONB, "postgresql")


def utc_now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class ProjectRecord(Base):
    __tablename__ = "project"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    customer_name: Mapped[str | None] = mapped_column(String(100))
    sap_context: Mapped[dict[str, object]] = mapped_column(JSON_DOCUMENT, nullable=False)
    external_model_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ProjectMemberRecord(Base):
    __tablename__ = "project_member"

    project_id: Mapped[str] = mapped_column(
        String(80), ForeignKey("project.id", ondelete="RESTRICT"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    role: Mapped[str] = mapped_column(String(30), nullable=False)
    created_by: Mapped[str] = mapped_column(String(80), nullable=False)
    updated_by: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ProjectAuditRecord(Base):
    __tablename__ = "project_audit_log"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(80), ForeignKey("project.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    before_value: Mapped[dict[str, object]] = mapped_column(JSON_DOCUMENT, nullable=False)
    after_value: Mapped[dict[str, object]] = mapped_column(JSON_DOCUMENT, nullable=False)
    actor_user_id: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ProcessRecord(Base):
    __tablename__ = "process"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(80), ForeignKey("project.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    module: Mapped[str] = mapped_column(String(20), nullable=False)
    process_scope: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT")
    current_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latest_release_no: Mapped[int | None] = mapped_column(Integer)
    created_by: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ProcessRevisionRecord(Base):
    __tablename__ = "process_revision"
    __table_args__ = (
        UniqueConstraint("process_id", "revision_no", name="uq_process_revision"),
        UniqueConstraint("process_id", "release_no", name="uq_process_release"),
    )

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    process_id: Mapped[str] = mapped_column(
        String(80), ForeignKey("process.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    release_no: Mapped[int | None] = mapped_column(Integer)
    lifecycle_state: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT")
    schema_version: Mapped[str] = mapped_column(String(10), nullable=False)
    graph_json: Mapped[dict[str, object]] = mapped_column(JSON_DOCUMENT, nullable=False)
    created_by: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ChangeLogRecord(Base):
    __tablename__ = "change_log"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    process_id: Mapped[str] = mapped_column(
        String(80), ForeignKey("process.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    base_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    result_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    user_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_patch: Mapped[dict[str, object]] = mapped_column(JSON_DOCUMENT, nullable=False)
    decision_summary: Mapped[str] = mapped_column(String(500), nullable=False)
    evidence_refs: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, nullable=False, default=list)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    created_by: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class GapDecisionRecord(Base):
    __tablename__ = "gap_decision"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    process_id: Mapped[str] = mapped_column(
        String(80), ForeignKey("process.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    node_id: Mapped[str] = mapped_column(String(80), nullable=False)
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    from_status: Mapped[str] = mapped_column(String(30), nullable=False)
    to_status: Mapped[str] = mapped_column(String(30), nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False)
    decided_by: Mapped[str] = mapped_column(String(80), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ExportJobRecord(Base):
    __tablename__ = "export_job"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    process_id: Mapped[str] = mapped_column(
        String(80), ForeignKey("process.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    format: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    claim_token: Mapped[str | None] = mapped_column(String(80))
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    filename: Mapped[str | None] = mapped_column(String(255))
    fallback_filename: Mapped[str | None] = mapped_column(String(255))
    media_type: Mapped[str | None] = mapped_column(String(120))
    content: Mapped[bytes | None] = mapped_column(LargeBinary)
    content_length: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(String(500))
    created_by: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
