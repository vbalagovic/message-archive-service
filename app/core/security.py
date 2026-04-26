"""API-key authentication.

Single header (``X-API-Key``) checked in constant time against the configured
allow-list. The matched key's short fingerprint is logged so we can audit
which key did what, without ever logging the secret itself.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Annotated

import structlog
from fastapi import Depends, Security
from fastapi.security import APIKeyHeader

from app.config import Settings, get_settings
from app.core.errors import UnauthorizedError

API_KEY_HEADER = "X-API-Key"

_api_key_scheme = APIKeyHeader(name=API_KEY_HEADER, auto_error=False)
logger = structlog.stdlib.get_logger(__name__)


def _fingerprint(key: str) -> str:
    """Short non-reversible identifier for log correlation."""
    return hashlib.sha256(key.encode()).hexdigest()[:8]


def _matches_any(presented: str, allowed: list[str]) -> str | None:
    """Constant-time match against every configured key. Returns the matched key, or None."""
    presented_bytes = presented.encode()
    matched: str | None = None
    for candidate in allowed:
        if hmac.compare_digest(presented_bytes, candidate.encode()):
            matched = candidate
            # Keep iterating to keep timing flat.
    return matched


async def require_api_key(
    presented: Annotated[str | None, Security(_api_key_scheme)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> str:
    """FastAPI dependency: returns the matched key's fingerprint or raises 401."""
    if not presented:
        raise UnauthorizedError("Missing API key.")
    matched = _matches_any(presented, settings.api_keys)
    if matched is None:
        logger.warning("api_key_rejected", fingerprint=_fingerprint(presented))
        raise UnauthorizedError("Invalid API key.")
    return _fingerprint(matched)
