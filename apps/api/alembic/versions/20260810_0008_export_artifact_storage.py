"""move export artifacts out of the application database

Revision ID: 20260810_0008
Revises: 20260809_0007
Create Date: 2026-08-10
"""

import sqlalchemy as sa

from alembic import op

revision = "20260810_0008"
down_revision = "20260809_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("export_job", sa.Column("artifact_backend", sa.String(length=20)))
    op.add_column("export_job", sa.Column("artifact_key", sa.String(length=512)))
    op.add_column("export_job", sa.Column("content_sha256", sa.String(length=64)))
    op.execute(
        "UPDATE export_job SET artifact_backend = 'database' "
        "WHERE status = 'completed' AND content IS NOT NULL"
    )
    op.create_index(
        "ix_export_job_status_expires_at",
        "export_job",
        ["status", "expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_export_job_status_expires_at", table_name="export_job")
    op.drop_column("export_job", "content_sha256")
    op.drop_column("export_job", "artifact_key")
    op.drop_column("export_job", "artifact_backend")
