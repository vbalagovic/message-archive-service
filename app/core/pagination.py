"""Opaque cursor encoding for stable, write-safe pagination.

Cursor payload: ``{"sent_at": ISO8601, "id": UUID4}``.
Encoded as URL-safe base64 of the JSON. Opaque to clients: never parse it on
the wire, just round-trip whatever the server sent.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.core.errors import ValidationConflictError


@dataclass(frozen=True, slots=True)
class Cursor:
    sent_at: datetime
    message_id: UUID

    def encode(self) -> str:
        payload = json.dumps(
            {"sent_at": self.sent_at.isoformat(), "id": str(self.message_id)},
            separators=(",", ":"),
        ).encode()
        return base64.urlsafe_b64encode(payload).decode().rstrip("=")

    @classmethod
    def decode(cls, raw: str) -> Cursor:
        try:
            padded = raw + "=" * (-len(raw) % 4)
            payload = json.loads(base64.urlsafe_b64decode(padded.encode()))
            return cls(
                sent_at=datetime.fromisoformat(payload["sent_at"]),
                message_id=UUID(payload["id"]),
            )
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ValidationConflictError(f"Invalid pagination cursor: {raw!r}") from exc
