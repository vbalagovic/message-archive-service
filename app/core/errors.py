"""Application error hierarchy and FastAPI exception handlers.

Every error response uses the same envelope so clients can branch on a
machine-readable ``code`` rather than parsing prose.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger, request_id_ctx

logger = get_logger(__name__)


class AppError(Exception):
    """Base class for application-level errors with a stable code + status."""

    code: str = "INTERNAL_ERROR"
    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFoundError(AppError):
    code = "NOT_FOUND"
    status_code = status.HTTP_404_NOT_FOUND


class ConflictError(AppError):
    code = "CONFLICT"
    status_code = status.HTTP_409_CONFLICT


class ValidationConflictError(AppError):
    code = "VALIDATION_ERROR"
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT


class UnauthorizedError(AppError):
    code = "UNAUTHORIZED"
    status_code = status.HTTP_401_UNAUTHORIZED


def error_envelope(
    *, code: str, message: str, details: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Build the canonical error response body.

    Public so other modules (rate-limit, custom handlers) can return identical
    envelopes without importing private symbols.
    """
    body: dict[str, Any] = {"code": code, "message": message}
    if details:
        body["details"] = details
    rid = request_id_ctx.get()
    if rid is not None:
        body["request_id"] = rid
    return {"error": body}


async def _app_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    logger.warning("app_error", code=exc.code, message=exc.message, details=exc.details)
    return JSONResponse(
        status_code=exc.status_code,
        content=error_envelope(code=exc.code, message=exc.message, details=exc.details or None),
    )


async def _validation_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    # exc.errors() can contain ValueError instances in `ctx` — run through
    # jsonable_encoder so the response body always serialises cleanly.
    safe_errors = jsonable_encoder(exc.errors(), custom_encoder={Exception: str})
    logger.info("validation_error", errors=safe_errors)
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content=error_envelope(
            code="VALIDATION_ERROR",
            message="Request body or parameters failed validation.",
            details={"errors": safe_errors},
        ),
    )


async def _http_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    return JSONResponse(
        status_code=exc.status_code,
        content=error_envelope(code=f"HTTP_{exc.status_code}", message=str(exc.detail)),
    )


async def _unhandled_handler(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled_exception", error=str(exc))
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=error_envelope(
            code="INTERNAL_ERROR",
            message="An unexpected error occurred.",
        ),
    )


def install_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_handler)
    app.add_exception_handler(StarletteHTTPException, _http_handler)
    app.add_exception_handler(Exception, _unhandled_handler)
