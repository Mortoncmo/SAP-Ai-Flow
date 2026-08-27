"""Add heartbeats for long-running export worker leases.

Revision ID: 20260809_0007
Revises: 20260809_0006
Create Date: 2026-08-09 22:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260809_0007"
down_revision: str | None = "20260809_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "export_job",
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "UPDATE export_job SET heartbeat_at = started_at "
        "WHERE status = 'running' AND heartbeat_at IS NULL"
    )
    op.create_index(
        "ix_export_job_status_heartbeat_at",
        "export_job",
        ["status", "heartbeat_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_export_job_status_heartbeat_at", table_name="export_job")
    op.drop_column("export_job", "heartbeat_at")
