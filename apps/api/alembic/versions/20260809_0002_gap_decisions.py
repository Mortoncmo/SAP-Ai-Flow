"""Add auditable GAP decisions.

Revision ID: 20260809_0002
Revises: 20260809_0001
Create Date: 2026-08-09 00:10:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260809_0002"
down_revision: str | None = "20260809_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "gap_decision",
        sa.Column("id", sa.String(length=80), nullable=False),
        sa.Column("process_id", sa.String(length=80), nullable=False),
        sa.Column("node_id", sa.String(length=80), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("from_status", sa.String(length=30), nullable=False),
        sa.Column("to_status", sa.String(length=30), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("decided_by", sa.String(length=80), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["process_id"], ["process.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_gap_decision_process_id", "gap_decision", ["process_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_gap_decision_process_id", table_name="gap_decision")
    op.drop_table("gap_decision")
