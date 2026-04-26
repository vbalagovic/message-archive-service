"""SQLAlchemy 2.0 ORM models."""

from __future__ import annotations

import enum
from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Index, String, func, text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Project-wide ORM base."""


class MessageRole(enum.StrEnum):
    AI = "ai"
    USER = "user"


class Message(Base):
    __tablename__ = "messages"

    message_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    chat_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    content: Mapped[str] = mapped_column(String, nullable=False)
    rating: Mapped[bool | None] = mapped_column(nullable=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    role: Mapped[MessageRole] = mapped_column(
        SAEnum(MessageRole, name="message_role", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        server_onupdate=text("now()"),  # belt-and-braces; SA also bumps it
    )

    __table_args__ = (
        Index("ix_messages_chat_sent_desc", "chat_id", text("sent_at DESC")),
        Index("ix_messages_sent_id", "sent_at", "message_id"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Message {self.message_id} chat={self.chat_id} role={self.role.value}>"
