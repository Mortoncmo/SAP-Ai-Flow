"""Create the initial blueprint persistence schema.

Revision ID: 20260809_0001
Revises:
Create Date: 2026-08-09 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260809_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

json_document = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "project",
        sa.Column("id", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("customer_name", sa.String(length=100), nullable=True),
        sa.Column("sap_context", json_document, nullable=False),
        sa.Column("created_by", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "process",
        sa.Column("id", sa.String(length=80), nullable=False),
        sa.Column("project_id", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("module", sa.String(length=20), nullable=False),
        sa.Column("process_scope", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("current_revision", sa.Integer(), nullable=False),
        sa.Column("latest_release_no", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_process_project_id", "process", ["project_id"], unique=False)
    op.create_table(
        "process_revision",
        sa.Column("id", sa.String(length=80), nullable=False),
        sa.Column("process_id", sa.String(length=80), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("release_no", sa.Integer(), nullable=True),
        sa.Column("lifecycle_state", sa.String(length=20), nullable=False),
        sa.Column("schema_version", sa.String(length=10), nullable=False),
        sa.Column("graph_json", json_document, nullable=False),
        sa.Column("created_by", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["process_id"], ["process.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("process_id", "release_no", name="uq_process_release"),
        sa.UniqueConstraint("process_id", "revision_no", name="uq_process_revision"),
    )
    op.create_index(
        "ix_process_revision_process_id", "process_revision", ["process_id"], unique=False
    )
    op.create_table(
        "change_log",
        sa.Column("id", sa.String(length=80), nullable=False),
        sa.Column("process_id", sa.String(length=80), nullable=False),
        sa.Column("base_revision", sa.Integer(), nullable=False),
        sa.Column("result_revision", sa.Integer(), nullable=False),
        sa.Column("user_prompt", sa.Text(), nullable=False),
        sa.Column("normalized_patch", json_document, nullable=False),
        sa.Column("decision_summary", sa.String(length=500), nullable=False),
        sa.Column("evidence_refs", json_document, nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("created_by", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["process_id"], ["process.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_change_log_process_id", "change_log", ["process_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_change_log_process_id", table_name="change_log")
    op.drop_table("change_log")
    op.drop_index("ix_process_revision_process_id", table_name="process_revision")
    op.drop_table("process_revision")
    op.drop_index("ix_process_project_id", table_name="process")
    op.drop_table("process")
    op.drop_table("project")
