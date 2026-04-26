"""Thin async client for the message-archive service."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx
import structlog

logger = structlog.stdlib.get_logger(__name__)


class ArchiveError(RuntimeError):
    pass


class ArchiveClient:
    def __init__(self, base_url: str, api_key: str, *, timeout: float = 10.0) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            headers={"X-API-Key": api_key, "Content-Type": "application/json"},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def upsert_message(
        self,
        *,
        message_id: UUID,
        chat_id: UUID,
        content: str,
        role: str,
        sent_at: datetime | None = None,
        rating: bool | None = None,
    ) -> dict[str, Any]:
        body = {
            "message_id": str(message_id),
            "chat_id": str(chat_id),
            "content": content,
            "rating": rating,
            "sent_at": (sent_at or datetime.now(UTC)).isoformat(),
            "role": role,
        }
        response = await self._client.put(f"/api/v1/messages/{message_id}", json=body)
        if response.status_code not in (200, 201):
            logger.error(
                "archive_upsert_failed",
                status=response.status_code,
                body=response.text[:500],
            )
            raise ArchiveError(f"Archive returned {response.status_code}")
        return dict(response.json())

    async def list_messages(
        self,
        *,
        chat_id: UUID | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        params: dict[str, str] = {"limit": str(limit)}
        if chat_id is not None:
            params["chat_id"] = str(chat_id)
        items: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            if cursor:
                params["cursor"] = cursor
            response = await self._client.get("/api/v1/messages", params=params)
            response.raise_for_status()
            payload = response.json()
            items.extend(payload["items"])
            cursor = payload.get("next_cursor")
            if not cursor or len(items) >= limit:
                break
        return items[:limit]
