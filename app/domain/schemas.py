"""Pydantic v2 DTOs.

Strictly separate from ORM models so changing the storage shape doesn't
silently change the wire shape (and vice versa).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.config import get_settings
from app.domain.models import MessageRole


def _max_content_length() -> int:
    return get_settings().max_content_length


class MessageIn(BaseModel):
    """Request body for PUT /messages/{message_id} (full create-or-replace)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    message_id: UUID = Field(description="Client-supplied stable identifier (UUID4).")
    chat_id: UUID = Field(description="Identifier of the conversation this message belongs to.")
    content: str = Field(min_length=1, description="Message text. Empty strings are rejected.")
    rating: bool | None = Field(
        default=None,
        description="Optional thumbs up/down. Null means not rated.",
    )
    sent_at: datetime = Field(description="Time the message was sent (timezone-aware).")
    role: MessageRole = Field(description="Whether this message came from the user or the AI.")

    @field_validator("content")
    @classmethod
    def _content_size(cls, value: str) -> str:
        limit = _max_content_length()
        if len(value.encode("utf-8")) > limit:
            raise ValueError(f"content exceeds maximum size ({limit} bytes)")
        return value

    @field_validator("sent_at")
    @classmethod
    def _require_tz(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("sent_at must be timezone-aware (use ISO 8601 with offset)")
        return value


class MessagePatch(BaseModel):
    """Request body for PATCH /messages/{message_id} (partial update).

    Only ``content`` and ``rating`` are mutable; identity/timestamp/role are
    set on creation. Sending an unsupported field returns 422.
    """

    model_config = ConfigDict(extra="forbid")

    content: str | None = Field(default=None, min_length=1)
    rating: bool | None = Field(default=None)

    def to_kwargs(self) -> dict[str, Any]:
        """Translate into repository ``patch`` kwargs.

        Distinguishes between absent and explicit-null on ``rating`` by
        consulting ``model_fields_set``.
        """
        kwargs: dict[str, Any] = {"rating_set": "rating" in self.model_fields_set}
        if "rating" in self.model_fields_set:
            kwargs["rating"] = self.rating
        if "content" in self.model_fields_set and self.content is not None:
            kwargs["content"] = self.content
        return kwargs

    @field_validator("content")
    @classmethod
    def _content_size(cls, value: str | None) -> str | None:
        if value is None:
            return None
        limit = _max_content_length()
        if len(value.encode("utf-8")) > limit:
            raise ValueError(f"content exceeds maximum size ({limit} bytes)")
        return value


class MessageOut(BaseModel):
    """Response body for a single message."""

    model_config = ConfigDict(from_attributes=True)

    message_id: UUID
    chat_id: UUID
    content: str
    rating: bool | None
    sent_at: datetime
    role: MessageRole
    created_at: datetime
    updated_at: datetime


class MessageListOut(BaseModel):
    """Response body for GET /messages."""

    items: list[MessageOut]
    next_cursor: str | None = Field(
        default=None,
        description="Opaque cursor; pass it back as ?cursor= to fetch the next page.",
    )
