"""Async streaming Ollama client.

Speaks to /api/chat which returns line-delimited JSON. We yield only the new
content fragments so the BFF can re-frame them as SSE.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any, TypedDict

import httpx
import structlog

logger = structlog.stdlib.get_logger(__name__)


class ChatMessage(TypedDict):
    role: str  # "system" | "user" | "assistant"
    content: str


class OllamaClient:
    def __init__(self, base_url: str, *, timeout: float = 120.0) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(timeout, connect=10.0),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def health(self) -> bool:
        try:
            response = await self._client.get("/", timeout=5.0)
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    async def has_model(self, name: str) -> bool:
        try:
            response = await self._client.get("/api/tags", timeout=5.0)
            response.raise_for_status()
            tags = response.json().get("models", [])
            return any(m.get("name", "").startswith(name) for m in tags)
        except httpx.HTTPError as exc:
            logger.warning("ollama_tags_failed", error=str(exc))
            return False

    async def chat_stream(
        self,
        *,
        model: str,
        messages: list[ChatMessage],
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        """Yield assistant content chunks as they arrive from Ollama."""
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
            "options": {"temperature": temperature},
        }
        async with self._client.stream("POST", "/api/chat", json=payload) as response:
            if response.status_code != 200:
                body = (await response.aread()).decode(errors="replace")
                raise RuntimeError(f"Ollama {response.status_code}: {body[:500]}")
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning("ollama_bad_json", line=line[:200])
                    continue
                msg = event.get("message") or {}
                fragment = msg.get("content", "")
                if fragment:
                    yield fragment
                if event.get("done"):
                    return
