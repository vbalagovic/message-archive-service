from __future__ import annotations

from httpx import AsyncClient

from tests.conftest import VALID_API_KEY, make_message_payload


async def test_missing_key_returns_401(anon_client: AsyncClient) -> None:
    response = await anon_client.get("/api/v1/messages")
    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "UNAUTHORIZED"


async def test_invalid_key_returns_401(anon_client: AsyncClient) -> None:
    response = await anon_client.get(
        "/api/v1/messages",
        headers={"X-API-Key": "wrong"},
    )
    assert response.status_code == 401


async def test_valid_key_returns_200(anon_client: AsyncClient) -> None:
    response = await anon_client.get(
        "/api/v1/messages",
        headers={"X-API-Key": VALID_API_KEY},
    )
    assert response.status_code == 200


async def test_put_requires_auth(anon_client: AsyncClient) -> None:
    payload = make_message_payload()
    response = await anon_client.put(
        f"/api/v1/messages/{payload['message_id']}",
        json=payload,
    )
    assert response.status_code == 401
