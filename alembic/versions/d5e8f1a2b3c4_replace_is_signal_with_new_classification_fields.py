"""replace is_signal with new classification fields

Revision ID: d5e8f1a2b3c4
Revises: c4d7e2f1a9b0
Create Date: 2025-01-27 00:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "d5e8f1a2b3c4"
down_revision = "c4d7e2f1a9b0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop old is_signal index and column
    op.drop_index("ix_messages_is_signal", table_name="messages")
    op.drop_column("messages", "is_signal")
    
    # Add new classification fields
    op.add_column(
        "messages",
        sa.Column("intents", postgresql.ARRAY(sa.String()), nullable=True),
    )
    op.add_column(
        "messages",
        sa.Column("domains", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "messages",
        sa.Column("urgency_score", sa.Integer(), nullable=True),
    )
    op.add_column(
        "messages",
        sa.Column("is_spam", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "messages",
        sa.Column("reasoning", sa.Text(), nullable=True),
    )
    
    # Create indexes for new fields
    op.create_index("ix_messages_urgency_score", "messages", ["urgency_score"], unique=False)
    op.create_index("ix_messages_is_spam", "messages", ["is_spam"], unique=False)
    
    # Remove server_default after initial data migration
    op.alter_column("messages", "is_spam", server_default=None)


def downgrade() -> None:
    # Drop new indexes and columns
    op.drop_index("ix_messages_is_spam", table_name="messages")
    op.drop_index("ix_messages_urgency_score", table_name="messages")
    op.drop_column("messages", "reasoning")
    op.drop_column("messages", "is_spam")
    op.drop_column("messages", "urgency_score")
    op.drop_column("messages", "domains")
    op.drop_column("messages", "intents")
    
    # Restore old is_signal column
    op.add_column(
        "messages",
        sa.Column("is_signal", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_messages_is_signal", "messages", ["is_signal"], unique=False)
    op.alter_column("messages", "is_signal", server_default=None)

