"""Add project external model policy and audit log.

Revision ID: 20260809_0004
Revises: 20260809_0003
Create Date: 2026-08-09 10:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260809_0004"
down_revision: str | None = "20260809_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

json_document = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.add_column(
        "project",
        sa.Column(
            "external_model_enabled",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.create_table(
        "project_audit_log",
        sa.Column("id", sa.String(length=80), nullable=False),
        sa.Column("project_id", sa.String(length=80), nullable=False),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("before_value", json_document, nullable=False),
        sa.Column("after_value", json_document, nullable=False),
        sa.Column("actor_user_id", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_project_audit_log_project_id",
        "project_audit_log",
        ["project_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_project_audit_log_project_id", table_name="project_audit_log")
    op.drop_table("project_audit_log")
    op.drop_column("project", "external_model_enabled")
