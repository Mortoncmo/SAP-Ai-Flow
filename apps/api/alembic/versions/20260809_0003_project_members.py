"""Add server-side project memberships.

Revision ID: 20260809_0003
Revises: 20260809_0002
Create Date: 2026-08-09 01:40:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260809_0003"
down_revision: str | None = "20260809_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "project_member",
        sa.Column("project_id", sa.String(length=80), nullable=False),
        sa.Column("user_id", sa.String(length=80), nullable=False),
        sa.Column("role", sa.String(length=30), nullable=False),
        sa.Column("created_by", sa.String(length=80), nullable=False),
        sa.Column("updated_by", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("project_id", "user_id"),
    )
    op.create_index("ix_project_member_user_id", "project_member", ["user_id"], unique=False)
    op.execute(
        """
        INSERT INTO project_member (
            project_id, user_id, role, created_by, updated_by, created_at, updated_at
        )
        SELECT id, created_by, 'project_admin', created_by, created_by, created_at, updated_at
        FROM project
        """
    )


def downgrade() -> None:
    op.drop_index("ix_project_member_user_id", table_name="project_member")
    op.drop_table("project_member")
