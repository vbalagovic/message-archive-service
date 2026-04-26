"""Chat BFF — serves the UI and orchestrates Ollama + archive."""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4

import structlog
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from chat.archive_client import ArchiveClient, ArchiveError
from chat.config import Settings, get_settings
from chat.ollama_client import ChatMessage, OllamaClient

UI_DIR = Path(__file__).resolve().parent.parent / "ui"
MAX_HISTORY = 40  # cap conversation context fed to Ollama


def _configure_logging(level: str) -> None:
    logging.basicConfig(stream=sys.stdout, level=level.upper())
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
    )


logger = structlog.stdlib.get_logger("chat")


# ----------------------------------------------------------------------------
# Lifespan / clients
# ----------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    _configure_logging(settings.log_level)
    app.state.archive = ArchiveClient(
        base_url=settings.archive_url,
        api_key=settings.archive_api_key,
        timeout=settings.request_timeout_s,
    )
    app.state.ollama = OllamaClient(
        base_url=settings.ollama_url,
        timeout=settings.request_timeout_s,
    )
    logger.info(
        "chat_bff_starting",
        archive=settings.archive_url,
        ollama=settings.ollama_url,
        model=settings.llm_model,
    )
    try:
        yield
    finally:
        await app.state.archive.aclose()
        await app.state.ollama.aclose()


app = FastAPI(
    title="Chat BFF",
    description="Tiny chat orchestrator: UI + Ollama + archive.",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)


@app.middleware("http")
async def _add_cors_for_dev(request, call_next):  # type: ignore[no-untyped-def]
    response = await call_next(request)
    return response


# CORS — useful when serving the UI from a different origin during dev.
_settings = get_settings()
if _settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )


# ----------------------------------------------------------------------------
# Dependencies
# ----------------------------------------------------------------------------
def _archive() -> ArchiveClient:
    return app.state.archive  # type: ignore[no-any-return]


def _ollama() -> OllamaClient:
    return app.state.ollama  # type: ignore[no-any-return]


SettingsDep = Annotated[Settings, Depends(get_settings)]
ArchiveDep = Annotated[ArchiveClient, Depends(_archive)]
OllamaDep = Annotated[OllamaClient, Depends(_ollama)]


# ----------------------------------------------------------------------------
# Schemas
# ----------------------------------------------------------------------------
class ChatSummary(BaseModel):
    chat_id: UUID
    last_at: datetime
    last_role: str
    last_preview: str
    message_count: int


class MessageOut(BaseModel):
    message_id: UUID
    chat_id: UUID
    content: str
    role: str
    rating: bool | None
    sent_at: datetime


class NewChatOut(BaseModel):
    chat_id: UUID


class SendIn(BaseModel):
    content: str = Field(min_length=1, max_length=8000)


# ----------------------------------------------------------------------------
# Endpoints
# ----------------------------------------------------------------------------
@app.get("/api/health")
async def health(ollama: OllamaDep, settings: SettingsDep) -> dict[str, object]:
    ok = await ollama.health()
    has = await ollama.has_model(settings.llm_model) if ok else False
    return {"ollama_up": ok, "model_ready": has, "model": settings.llm_model}


@app.post("/api/chats", response_model=NewChatOut)
async def new_chat() -> NewChatOut:
    return NewChatOut(chat_id=uuid4())


@app.get("/api/chats", response_model=list[ChatSummary])
async def list_chats(archive: ArchiveDep) -> list[ChatSummary]:
    """Derive chat summaries by grouping the most recent N messages by chat_id."""
    items = await archive.list_messages(limit=200)
    groups: dict[UUID, list[dict]] = {}  # type: ignore[type-arg]
    for m in items:
        groups.setdefault(UUID(m["chat_id"]), []).append(m)
    summaries: list[ChatSummary] = []
    for chat_id, msgs in groups.items():
        msgs.sort(key=lambda x: x["sent_at"])
        last = msgs[-1]
        summaries.append(
            ChatSummary(
                chat_id=chat_id,
                last_at=datetime.fromisoformat(last["sent_at"].replace("Z", "+00:00")),
                last_role=last["role"],
                last_preview=last["content"][:80],
                message_count=len(msgs),
            )
        )
    summaries.sort(key=lambda s: s.last_at, reverse=True)
    return summaries


@app.get("/api/chats/{chat_id}/messages", response_model=list[MessageOut])
async def list_chat_messages(chat_id: UUID, archive: ArchiveDep) -> list[MessageOut]:
    items = await archive.list_messages(chat_id=chat_id, limit=200)
    return [
        MessageOut(
            message_id=UUID(m["message_id"]),
            chat_id=UUID(m["chat_id"]),
            content=m["content"],
            role=m["role"],
            rating=m["rating"],
            sent_at=datetime.fromisoformat(m["sent_at"].replace("Z", "+00:00")),
        )
        for m in items
    ]


@app.post("/api/chats/{chat_id}/messages")
async def send_message(
    chat_id: UUID,
    body: SendIn,
    archive: ArchiveDep,
    ollama: OllamaDep,
    settings: SettingsDep,
) -> EventSourceResponse:
    """Persist user msg → stream assistant reply → persist assistant msg.

    Returns SSE events:
      - event: user_message    {message_id, sent_at}
      - event: token           {fragment}
      - event: ai_message      {message_id, sent_at, content}
      - event: error           {message}
    """
    # 1) Pull history first so the assistant has context.
    history_raw = await archive.list_messages(chat_id=chat_id, limit=MAX_HISTORY)

    # 2) Persist the user's message right away.
    user_msg_id = uuid4()
    user_sent = datetime.now(UTC)
    try:
        await archive.upsert_message(
            message_id=user_msg_id,
            chat_id=chat_id,
            content=body.content,
            role="user",
            sent_at=user_sent,
        )
    except ArchiveError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"archive: {exc}") from exc

    # Build messages for Ollama (system + history + new user turn).
    convo: list[ChatMessage] = [
        ChatMessage(role="system", content=settings.llm_system_prompt)
    ]
    for m in history_raw:
        convo.append(
            ChatMessage(
                role="assistant" if m["role"] == "ai" else "user",
                content=m["content"],
            )
        )
    convo.append(ChatMessage(role="user", content=body.content))

    async def event_stream() -> AsyncIterator[dict[str, str]]:
        yield {
            "event": "user_message",
            "data": json.dumps(
                {"message_id": str(user_msg_id), "sent_at": user_sent.isoformat()}
            ),
        }

        chunks: list[str] = []
        try:
            async for fragment in ollama.chat_stream(
                model=settings.llm_model,
                messages=convo,
                temperature=settings.llm_temperature,
            ):
                chunks.append(fragment)
                yield {"event": "token", "data": json.dumps({"fragment": fragment})}
        except Exception as exc:  # noqa: BLE001 — surface anything to the client
            logger.exception("ollama_failed")
            yield {"event": "error", "data": json.dumps({"message": str(exc)})}
            return

        full = "".join(chunks).strip() or "(empty response)"
        ai_msg_id = uuid4()
        ai_sent = datetime.now(UTC)
        try:
            await archive.upsert_message(
                message_id=ai_msg_id,
                chat_id=chat_id,
                content=full,
                role="ai",
                sent_at=ai_sent,
            )
        except ArchiveError as exc:
            yield {"event": "error", "data": json.dumps({"message": f"archive: {exc}"})}
            return

        yield {
            "event": "ai_message",
            "data": json.dumps(
                {
                    "message_id": str(ai_msg_id),
                    "sent_at": ai_sent.isoformat(),
                    "content": full,
                }
            ),
        }

    return EventSourceResponse(event_stream())


@app.post("/api/messages/{message_id}/rating")
async def rate_message(
    message_id: UUID,
    rating: bool | None,
    settings: SettingsDep,
) -> JSONResponse:
    """Pass-through to the archive's PATCH endpoint."""
    import httpx  # noqa: PLC0415

    async with httpx.AsyncClient(
        base_url=settings.archive_url,
        headers={"X-API-Key": settings.archive_api_key},
        timeout=10.0,
    ) as c:
        r = await c.patch(f"/api/v1/messages/{message_id}", json={"rating": rating})
    return JSONResponse(status_code=r.status_code, content=r.json())


# ----------------------------------------------------------------------------
# Static UI (mounted last so /api/* takes priority)
# ----------------------------------------------------------------------------
if UI_DIR.exists():
    app.mount("/static", StaticFiles(directory=UI_DIR), name="static")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(UI_DIR / "index.html")
