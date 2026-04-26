"""Prometheus instrumentation, opt-in via ``ENABLE_METRICS``.

Kept tiny: request count, request latency, in-flight gauge. The DB pool
exposes its own stats elsewhere if needed. We intentionally do not import
prometheus-fastapi-instrumentator to avoid pulling another dependency.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from fastapi import FastAPI
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from starlette.requests import Request
from starlette.responses import Response

REQUESTS = Counter(
    "http_requests_total",
    "Total HTTP requests",
    labelnames=("method", "path_template", "status"),
)
LATENCY = Histogram(
    "http_request_duration_seconds",
    "Request latency in seconds",
    labelnames=("method", "path_template"),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)
IN_FLIGHT = Gauge(
    "http_requests_in_flight",
    "Requests currently in flight",
)


def install_metrics(app: FastAPI) -> None:
    """Wire the metrics middleware and the ``/metrics`` endpoint."""

    @app.middleware("http")
    async def _metrics_mw(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        IN_FLIGHT.inc()
        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            elapsed = time.perf_counter() - started
            template = _route_template(request)
            REQUESTS.labels(request.method, template, str(status_code)).inc()
            LATENCY.labels(request.method, template).observe(elapsed)
            IN_FLIGHT.dec()

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    return getattr(route, "path", request.url.path)
