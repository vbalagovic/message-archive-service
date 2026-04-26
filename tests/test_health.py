from __future__ import annotations

from httpx import AsyncClient


async def test_healthz_returns_ok(anon_client: AsyncClient) -> None:
    response = await anon_client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_readyz_with_db(anon_client: AsyncClient) -> None:
    response = await anon_client.get("/readyz")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"


async def test_request_id_header_round_trips(anon_client: AsyncClient) -> None:
    response = await anon_client.get("/healthz", headers={"X-Request-ID": "abc123"})
    assert response.headers.get("X-Request-ID") == "abc123"


async def test_request_id_header_generated(anon_client: AsyncClient) -> None:
    response = await anon_client.get("/healthz")
    assert response.headers.get("X-Request-ID")
