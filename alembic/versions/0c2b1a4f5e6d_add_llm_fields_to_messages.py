"""add is_signal and llm_analysis to messages

Revision ID: 0c2b1a4f5e6d
Revises: 8e1f3b747a0a
Create Date: 2025-11-13 00:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "0c2b1a4f5e6d"
down_revision = "8e1f3b747a0a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("is_signal", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "messages",
        sa.Column("llm_analysis", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_index("ix_messages_is_signal", "messages", ["is_signal"], unique=False)
    # Optional: drop server_default after setting the initial default value
    op.alter_column("messages", "is_signal", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_messages_is_signal", table_name="messages")
    op.drop_column("messages", "llm_analysis")
    op.drop_column("messages", "is_signal")


