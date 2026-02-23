"""add message_thread_id to messages

Revision ID: e1f2a3b4c5d6
Revises: f7a8b9c0d1e2
Create Date: 2026-02-23 00:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e1f2a3b4c5d6"
down_revision = "f7a8b9c0d1e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("message_thread_id", sa.BigInteger(), nullable=True),
    )
    op.create_index(
        "ix_messages_message_thread_id",
        "messages",
        ["message_thread_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_messages_message_thread_id", table_name="messages")
    op.drop_column("messages", "message_thread_id")


