"""Coverage for opt-in features: metrics, readiness failure, CORS."""

from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import patch

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.config import Settings


@pytest_asyncio.fixture
async def metrics_client() -> AsyncIterator[AsyncClient]:
    from app.main import create_app  # noqa: PLC0415 — same lazy-import reason as conftest

    settings = Settings(enable_metrics=True, cors_origins=["http://allowed.example"])
    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def test_metrics_endpoint_exposes_prometheus(metrics_client: AsyncClient) -> None:
    # Hit a regular route to record at least one request.
    await metrics_client.get("/healthz")
    response = await metrics_client.get("/metrics")
    assert response.status_code == 200
    body = response.text
    assert "http_requests_total" in body
    assert "http_request_duration_seconds" in body


async def test_cors_preflight_when_enabled(metrics_client: AsyncClient) -> None:
    response = await metrics_client.options(
        "/api/v1/messages",
        headers={
            "Origin": "http://allowed.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://allowed.example"


async def test_readyz_503_when_db_down(anon_client: AsyncClient) -> None:
    from app.domain.repository import MessageRepository  # noqa: PLC0415

    async def boom(self: MessageRepository) -> None:
        raise RuntimeError("db unreachable")

    with patch.object(MessageRepository, "ping", boom):
        response = await anon_client.get("/readyz")
    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"
