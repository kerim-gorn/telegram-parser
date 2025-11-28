"""add sender_username and chat_username to messages

Revision ID: c4d7e2f1a9b0
Revises: b1c3d5e7f9a0
Create Date: 2025-11-25 00:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c4d7e2f1a9b0"
down_revision = "b1c3d5e7f9a0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("sender_username", sa.String(length=64), nullable=True))
    op.add_column("messages", sa.Column("chat_username", sa.String(length=64), nullable=True))
    op.create_index("ix_messages_chat_username", "messages", ["chat_username"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_messages_chat_username", table_name="messages")
    op.drop_column("messages", "chat_username")
    op.drop_column("messages", "sender_username")


