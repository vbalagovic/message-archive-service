"""FastAPI application factory.

Keeps the module-level state minimal: ``app`` is what uvicorn imports,
everything else hangs off ``create_app`` so tests can build an isolated
instance with overridden dependencies.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded

from app.api.health import router as health_router
from app.api.router import api_router
from app.config import Settings, get_settings
from app.core.errors import install_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.core.metrics import install_metrics
from app.core.middleware import RequestContextMiddleware
from app.core.rate_limit import build_limiter, rate_limit_handler
from app.db.session import dispose_engine, get_engine

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = get_settings()
    configure_logging(settings.log_level)
    logger.info(
        "service_starting",
        service=settings.service_name,
        environment=settings.environment,
    )
    # Eagerly create the engine so the first request is not slow.
    get_engine()
    try:
        yield
    finally:
        logger.info("service_stopping")
        await dispose_engine()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="Message Archive Service",
        description=(
            "Archives chat messages for an AI assistant system. "
            "All `/api/v1/*` routes require an `X-API-Key` header."
        ),
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # --- Middleware ---
    app.add_middleware(RequestContextMiddleware)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=False,
            allow_methods=["GET", "PUT", "PATCH"],
            allow_headers=["X-API-Key", "Content-Type", "X-Request-ID"],
            expose_headers=["X-Request-ID"],
        )

    # --- Rate limit ---
    limiter = build_limiter()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_handler)

    # --- Errors ---
    install_exception_handlers(app)

    # --- Routes ---
    app.include_router(health_router)
    app.include_router(api_router, prefix="/api/v1")

    # --- Optional Prometheus ---
    if settings.enable_metrics:
        install_metrics(app)

    return app


app = create_app()
