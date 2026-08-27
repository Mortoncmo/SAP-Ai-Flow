"""Add fenced leases for export workers.

Revision ID: 20260809_0006
Revises: 20260809_0005
Create Date: 2026-08-09 20:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260809_0006"
down_revision: str | None = "20260809_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("export_job", sa.Column("claim_token", sa.String(length=80), nullable=True))
    op.add_column(
        "export_job",
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(
        "ix_export_job_status_created_at",
        "export_job",
        ["status", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_export_job_status_created_at", table_name="export_job")
    op.drop_column("export_job", "attempt_count")
    op.drop_column("export_job", "claim_token")
