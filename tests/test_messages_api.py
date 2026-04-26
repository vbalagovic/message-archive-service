from __future__ import annotations

from uuid import uuid4

from httpx import AsyncClient

from app.domain.models import MessageRole
from tests.conftest import make_message_payload, utc_at


# ----------------------------------------------------------------------------
# PUT
# ----------------------------------------------------------------------------
class TestPutMessage:
    async def test_create_returns_201(self, client: AsyncClient) -> None:
        payload = make_message_payload()
        response = await client.put(f"/api/v1/messages/{payload['message_id']}", json=payload)
        assert response.status_code == 201
        body = response.json()
        assert body["message_id"] == payload["message_id"]
        assert body["chat_id"] == payload["chat_id"]
        assert body["content"] == payload["content"]
        assert body["role"] == payload["role"]
        assert body["created_at"]
        assert body["updated_at"]

    async def test_replace_returns_200(self, client: AsyncClient) -> None:
        payload = make_message_payload(content="first")
        await client.put(f"/api/v1/messages/{payload['message_id']}", json=payload)

        replacement = {**payload, "content": "second", "rating": True}
        response = await client.put(f"/api/v1/messages/{payload['message_id']}", json=replacement)
        assert response.status_code == 200
        assert response.json()["content"] == "second"
        assert response.json()["rating"] is True

    async def test_path_body_id_mismatch_returns_422(self, client: AsyncClient) -> None:
        payload = make_message_payload()
        other_id = uuid4()
        response = await client.put(f"/api/v1/messages/{other_id}", json=payload)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    async def test_unknown_field_rejected(self, client: AsyncClient) -> None:
        payload = make_message_payload()
        payload["extra_field"] = "nope"
        response = await client.put(f"/api/v1/messages/{payload['message_id']}", json=payload)
        assert response.status_code == 422

    async def test_content_size_enforced(self, client: AsyncClient) -> None:
        payload = make_message_payload(content="x" * 50_000)
        response = await client.put(f"/api/v1/messages/{payload['message_id']}", json=payload)
        assert response.status_code == 422

    async def test_naive_datetime_rejected(self, client: AsyncClient) -> None:
        payload = make_message_payload()
        payload["sent_at"] = "2026-01-01T00:00:00"  # no tz
        response = await client.put(f"/api/v1/messages/{payload['message_id']}", json=payload)
        assert response.status_code == 422

    async def test_invalid_role_rejected(self, client: AsyncClient) -> None:
        payload = make_message_payload()
        payload["role"] = "bot"
        response = await client.put(f"/api/v1/messages/{payload['message_id']}", json=payload)
        assert response.status_code == 422


# ----------------------------------------------------------------------------
# PATCH
# ----------------------------------------------------------------------------
class TestPatchMessage:
    async def test_update_rating(self, client: AsyncClient) -> None:
        payload = make_message_payload()
        await client.put(f"/api/v1/messages/{payload['message_id']}", json=payload)

        response = await client.patch(
            f"/api/v1/messages/{payload['message_id']}", json={"rating": True}
        )
        assert response.status_code == 200
        assert response.json()["rating"] is True

    async def test_update_content(self, client: AsyncClient) -> None:
        payload = make_message_payload(content="orig")
        await client.put(f"/api/v1/messages/{payload['message_id']}", json=payload)

        response = await client.patch(
            f"/api/v1/messages/{payload['message_id']}", json={"content": "edited"}
        )
        assert response.status_code == 200
        assert response.json()["content"] == "edited"

    async def test_clear_rating(self, client: AsyncClient) -> None:
        payload = make_message_payload(rating=True)
        await client.put(f"/api/v1/messages/{payload['message_id']}", json=payload)

        response = await client.patch(
            f"/api/v1/messages/{payload['message_id']}", json={"rating": None}
        )
        assert response.status_code == 200
        assert response.json()["rating"] is None

    async def test_missing_returns_404(self, client: AsyncClient) -> None:
        response = await client.patch(f"/api/v1/messages/{uuid4()}", json={"rating": True})
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND"

    async def test_empty_body_rejected(self, client: AsyncClient) -> None:
        payload = make_message_payload()
        await client.put(f"/api/v1/messages/{payload['message_id']}", json=payload)

        response = await client.patch(f"/api/v1/messages/{payload['message_id']}", json={})
        assert response.status_code == 422

    async def test_unknown_field_rejected(self, client: AsyncClient) -> None:
        payload = make_message_payload()
        await client.put(f"/api/v1/messages/{payload['message_id']}", json=payload)

        response = await client.patch(
            f"/api/v1/messages/{payload['message_id']}", json={"role": "ai"}
        )
        assert response.status_code == 422


# ----------------------------------------------------------------------------
# GET (list)
# ----------------------------------------------------------------------------
class TestListMessages:
    async def test_empty_list(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/messages")
        assert response.status_code == 200
        body = response.json()
        assert body["items"] == []
        assert body["next_cursor"] is None

    async def test_list_returns_inserted(self, client: AsyncClient) -> None:
        for i in range(3):
            payload = make_message_payload(content=f"m{i}", sent_at=utc_at(i))
            await client.put(f"/api/v1/messages/{payload['message_id']}", json=payload)

        response = await client.get("/api/v1/messages")
        assert response.status_code == 200
        body = response.json()
        assert len(body["items"]) == 3
        assert [m["content"] for m in body["items"]] == ["m0", "m1", "m2"]

    async def test_filter_by_chat_id(self, client: AsyncClient) -> None:
        chat_a = uuid4()
        chat_b = uuid4()
        for i in range(2):
            for chat in (chat_a, chat_b):
                payload = make_message_payload(chat_id=chat, sent_at=utc_at(i))
                await client.put(f"/api/v1/messages/{payload['message_id']}", json=payload)

        response = await client.get(f"/api/v1/messages?chat_id={chat_a}")
        body = response.json()
        assert len(body["items"]) == 2
        assert all(m["chat_id"] == str(chat_a) for m in body["items"])

    async def test_filter_by_role(self, client: AsyncClient) -> None:
        for i, role in enumerate([MessageRole.USER, MessageRole.AI, MessageRole.USER]):
            payload = make_message_payload(role=role, sent_at=utc_at(i))
            await client.put(f"/api/v1/messages/{payload['message_id']}", json=payload)

        response = await client.get("/api/v1/messages?role=ai")
        body = response.json()
        assert len(body["items"]) == 1
        assert body["items"][0]["role"] == "ai"

    async def test_filter_by_time_range(self, client: AsyncClient) -> None:
        for i in range(5):
            payload = make_message_payload(sent_at=utc_at(i * 10))
            await client.put(f"/api/v1/messages/{payload['message_id']}", json=payload)

        # Use params= so httpx URL-encodes the datetime offset (+00:00).
        response = await client.get(
            "/api/v1/messages",
            params={"since": utc_at(15).isoformat(), "until": utc_at(35).isoformat()},
        )
        body = response.json()
        # Only entries at sent_at = 20s, 30s should match.
        assert len(body["items"]) == 2

    async def test_pagination(self, client: AsyncClient) -> None:
        for i in range(5):
            payload = make_message_payload(content=f"m{i}", sent_at=utc_at(i))
            await client.put(f"/api/v1/messages/{payload['message_id']}", json=payload)

        page1 = (await client.get("/api/v1/messages?limit=2")).json()
        assert len(page1["items"]) == 2
        assert page1["next_cursor"] is not None

        page2 = (await client.get(f"/api/v1/messages?limit=2&cursor={page1['next_cursor']}")).json()
        assert len(page2["items"]) == 2

        page3 = (await client.get(f"/api/v1/messages?limit=2&cursor={page2['next_cursor']}")).json()
        assert len(page3["items"]) == 1
        assert page3["next_cursor"] is None

        all_contents = [m["content"] for m in page1["items"] + page2["items"] + page3["items"]]
        assert all_contents == ["m0", "m1", "m2", "m3", "m4"]

    async def test_invalid_cursor_returns_422(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/messages?cursor=garbage")
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    async def test_limit_bounds_enforced(self, client: AsyncClient) -> None:
        assert (await client.get("/api/v1/messages?limit=0")).status_code == 422
        assert (await client.get("/api/v1/messages?limit=201")).status_code == 422
