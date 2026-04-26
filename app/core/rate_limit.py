"""Per-API-key rate limiting via slowapi.

Identity for the limiter is the matched API key fingerprint when present,
falling back to client IP for unauthenticated routes (healthz/readyz/metrics).
"""

from __future__ import annotations

from fastapi import Request
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.responses import JSONResponse

from app.config import get_settings
from app.core.errors import error_envelope

API_KEY_HEADER_LOWER = "x-api-key"


def _identity(request: Request) -> str:
    key = request.headers.get(API_KEY_HEADER_LOWER)
    if key:
        # Don't use the raw key — its hash is enough to bucket requests.
        return f"key:{hash(key)}"
    return f"ip:{get_remote_address(request)}"


def build_limiter() -> Limiter:
    settings = get_settings()
    return Limiter(
        key_func=_identity,
        default_limits=[f"{settings.rate_limit_per_minute}/minute"],
        headers_enabled=True,
    )


async def rate_limit_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RateLimitExceeded)
    return JSONResponse(
        status_code=429,
        content=error_envelope(
            code="RATE_LIMITED",
            message=f"Rate limit exceeded: {exc.detail}",
        ),
    )
