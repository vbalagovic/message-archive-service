"""Structured JSON logging via structlog.

A single ``request_id`` contextvar threads through every log line emitted
during a request, so a client-side error can be traced to exact server logs.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import MutableMapping
from contextvars import ContextVar
from typing import Any

import structlog

request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)


def _add_request_id(
    _: Any, __: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    rid = request_id_ctx.get()
    if rid is not None:
        event_dict["request_id"] = rid
    return event_dict


def configure_logging(level: str = "INFO") -> None:
    """Configure stdlib + structlog to emit JSON to stdout.

    Idempotent: safe to call multiple times (test suite calls it per session).
    """
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        _add_request_id,
        timestamper,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processor=structlog.processors.JSONRenderer(),
            foreign_pre_chain=shared_processors,
        )
    )

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())

    # Quiet down noisy libraries; we add our own access log.
    for noisy in ("uvicorn.access", "sqlalchemy.engine"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.stdlib.get_logger(name)
