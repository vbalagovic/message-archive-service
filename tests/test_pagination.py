from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.core.errors import ValidationConflictError
from app.core.pagination import Cursor


def test_cursor_round_trip() -> None:
    original = Cursor(sent_at=datetime(2026, 1, 1, 12, 30, tzinfo=UTC), message_id=uuid4())
    encoded = original.encode()
    decoded = Cursor.decode(encoded)
    assert decoded == original


def test_cursor_decode_invalid_raises() -> None:
    with pytest.raises(ValidationConflictError):
        Cursor.decode("not-a-cursor")


def test_cursor_decode_truncated_raises() -> None:
    with pytest.raises(ValidationConflictError):
        Cursor.decode("eyJzZW50X2F0Ijo")  # truncated base64


def test_cursor_is_url_safe() -> None:
    cursor = Cursor(sent_at=datetime(2026, 1, 1, tzinfo=UTC), message_id=uuid4())
    encoded = cursor.encode()
    assert "+" not in encoded
    assert "/" not in encoded
    assert "=" not in encoded
