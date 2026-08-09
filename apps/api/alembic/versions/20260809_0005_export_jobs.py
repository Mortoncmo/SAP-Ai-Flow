"""Add persistent blueprint export jobs.

Revision ID: 20260809_0005
Revises: 20260809_0004
Create Date: 2026-08-09 15:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260809_0005"
down_revision: str | None = "20260809_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "export_job",
        sa.Column("id", sa.String(length=80), nullable=False),
        sa.Column("process_id", sa.String(length=80), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("format", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=True),
        sa.Column("fallback_filename", sa.String(length=255), nullable=True),
        sa.Column("media_type", sa.String(length=120), nullable=True),
        sa.Column("content", sa.LargeBinary(), nullable=True),
        sa.Column("content_length", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("created_by", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["process_id"], ["process.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_export_job_process_id", "export_job", ["process_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_export_job_process_id", table_name="export_job")
    op.drop_table("export_job")
