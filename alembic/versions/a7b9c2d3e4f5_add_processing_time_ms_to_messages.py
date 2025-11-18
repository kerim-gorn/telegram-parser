"""add processing_time_ms to messages

Revision ID: a7b9c2d3e4f5
Revises: 0c2b1a4f5e6d
Create Date: 2025-11-16 00:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a7b9c2d3e4f5"
down_revision = "0c2b1a4f5e6d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("processing_time_ms", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("messages", "processing_time_ms")



