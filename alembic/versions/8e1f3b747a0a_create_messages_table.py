"""create messages table

Revision ID: 8e1f3b747a0a
Revises: 
Create Date: 2025-11-12 00:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "8e1f3b747a0a"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "messages",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("sender_id", sa.BigInteger(), nullable=True),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("message_date", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("chat_id", "message_id", name="uq_messages_chat_message"),
    )
    op.create_index("ix_messages_chat_id", "messages", ["chat_id"], unique=False)
    op.create_index("ix_messages_message_date", "messages", ["message_date"], unique=False)
    op.create_index("ix_messages_chat_date", "messages", ["chat_id", "message_date"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_messages_chat_date", table_name="messages")
    op.drop_index("ix_messages_message_date", table_name="messages")
    op.drop_index("ix_messages_chat_id", table_name="messages")
    op.drop_table("messages")


