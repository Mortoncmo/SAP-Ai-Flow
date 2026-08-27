"""add project tenant isolation

Revision ID: 20260810_0009
Revises: 20260810_0008
Create Date: 2026-08-10
"""

import sqlalchemy as sa

from alembic import op

revision = "20260810_0009"
down_revision = "20260810_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "project",
        sa.Column(
            "tenant_id",
            sa.String(length=80),
            nullable=False,
            server_default="local",
        ),
    )
    op.create_index("ix_project_tenant_id", "project", ["tenant_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_project_tenant_id", table_name="project")
    op.drop_column("project", "tenant_id")
