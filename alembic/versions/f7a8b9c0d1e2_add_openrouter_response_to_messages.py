"""add openrouter_response to messages

Revision ID: f7a8b9c0d1e2
Revises: d5e8f1a2b3c4
Create Date: 2026-01-19 00:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "f7a8b9c0d1e2"
down_revision = "d5e8f1a2b3c4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("openrouter_response", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("messages", "openrouter_response")

