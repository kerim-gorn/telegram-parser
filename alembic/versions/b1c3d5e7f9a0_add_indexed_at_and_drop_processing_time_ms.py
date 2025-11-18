"""add indexed_at and drop processing_time_ms

Revision ID: b1c3d5e7f9a0
Revises: a7b9c2d3e4f5
Create Date: 2025-11-16 00:05:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b1c3d5e7f9a0"
down_revision = "a7b9c2d3e4f5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add indexed_at with server default to backfill existing rows
    op.add_column(
        "messages",
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_messages_indexed_at", "messages", ["indexed_at"], unique=False)
    # Optional: drop server_default after initial backfill
    op.alter_column("messages", "indexed_at", server_default=None)
    # Clean up previously added processing_time_ms if present in prior migration
    try:
        op.drop_column("messages", "processing_time_ms")
    except Exception:
        # If the column doesn't exist (e.g., migration order differs), ignore
        pass


def downgrade() -> None:
    # Recreate processing_time_ms as nullable on downgrade
    op.add_column("messages", sa.Column("processing_time_ms", sa.Integer(), nullable=True))
    op.drop_index("ix_messages_indexed_at", table_name="messages")
    op.drop_column("messages", "indexed_at")



