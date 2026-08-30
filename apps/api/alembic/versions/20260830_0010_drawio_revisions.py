"""persist Draw.io revision source

Revision ID: 20260830_0010
Revises: 20260810_0009
Create Date: 2026-08-30
"""

import sqlalchemy as sa

from alembic import op

revision = "20260830_0010"
down_revision = "20260810_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("process_revision", sa.Column("drawio_xml", sa.Text(), nullable=True))
    op.add_column(
        "process_revision",
        sa.Column("drawio_sha256", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("process_revision", "drawio_sha256")
    op.drop_column("process_revision", "drawio_xml")
