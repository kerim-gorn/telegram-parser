from __future__ import annotations

from typing import Any
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

from db.base import Base


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # Telegram identifiers
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    message_id: Mapped[int] = mapped_column(Integer, nullable=False)
    sender_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sender_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    chat_username: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    # Content
    text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # LLM classification fields
    intents: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    domains: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    urgency_score: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    is_spam: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    # Legacy LLM analysis field (for backward compatibility)
    llm_analysis: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Indexing timestamp (when this message was ingested into our system)
    indexed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    # Timestamps
    message_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    __table_args__ = (
        UniqueConstraint("chat_id", "message_id", name="uq_messages_chat_message"),
        Index("ix_messages_chat_date", "chat_id", "message_date"),
    )


