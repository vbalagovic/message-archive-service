"""Message endpoints: PUT (upsert), PATCH (partial), GET (list)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Query, Response, status

from app.core.errors import NotFoundError, ValidationConflictError
from app.core.pagination import Cursor
from app.deps import ApiKeyId, Repository
from app.domain.models import MessageRole
from app.domain.repository import ListFilters
from app.domain.schemas import MessageIn, MessageListOut, MessageOut, MessagePatch

router = APIRouter()

MAX_PAGE_LIMIT = 200
DEFAULT_PAGE_LIMIT = 50


@router.put(
    "/{message_id}",
    response_model=MessageOut,
    summary="Create or replace a message",
    responses={
        200: {"description": "Existing message replaced."},
        201: {"description": "New message created."},
        401: {"description": "Missing or invalid API key."},
        422: {"description": "Body failed validation or path/body id mismatch."},
    },
)
async def put_message(
    message_id: Annotated[UUID, Path(description="UUID4 of the message.")],
    body: MessageIn,
    repo: Repository,
    response: Response,
    _: ApiKeyId,
) -> MessageOut:
    if body.message_id != message_id:
        raise ValidationConflictError(
            "Path message_id does not match body message_id.",
            details={"path": str(message_id), "body": str(body.message_id)},
        )
    result = await repo.upsert(
        message_id=body.message_id,
        chat_id=body.chat_id,
        content=body.content,
        sent_at=body.sent_at,
        role=body.role,
        rating=body.rating,
    )
    response.status_code = status.HTTP_201_CREATED if result.created else status.HTTP_200_OK
    return MessageOut.model_validate(result.message)


@router.patch(
    "/{message_id}",
    response_model=MessageOut,
    summary="Partially update a message (content and/or rating)",
    responses={
        200: {"description": "Message updated."},
        401: {"description": "Missing or invalid API key."},
        404: {"description": "Message not found."},
        422: {"description": "Unknown field or invalid value."},
    },
)
async def patch_message(
    message_id: Annotated[UUID, Path(description="UUID4 of the message.")],
    body: MessagePatch,
    repo: Repository,
    _: ApiKeyId,
) -> MessageOut:
    if not body.model_fields_set:
        raise ValidationConflictError("PATCH body must contain at least one field.")
    updated = await repo.patch(message_id, **body.to_kwargs())
    if updated is None:
        raise NotFoundError(f"Message {message_id} not found.")
    return MessageOut.model_validate(updated)


@router.get(
    "",
    response_model=MessageListOut,
    summary="List messages with cursor pagination",
    responses={
        200: {"description": "Page of messages."},
        401: {"description": "Missing or invalid API key."},
        422: {"description": "Invalid cursor or filter values."},
    },
)
async def list_messages(
    repo: Repository,
    _: ApiKeyId,
    chat_id: Annotated[UUID | None, Query(description="Filter to a single chat.")] = None,
    role: Annotated[MessageRole | None, Query(description="Filter by author.")] = None,
    since: Annotated[
        datetime | None,
        Query(description="Inclusive lower bound on sent_at (ISO 8601 with offset)."),
    ] = None,
    until: Annotated[
        datetime | None,
        Query(description="Inclusive upper bound on sent_at (ISO 8601 with offset)."),
    ] = None,
    cursor: Annotated[
        str | None,
        Query(description="Opaque cursor returned from the previous page."),
    ] = None,
    limit: Annotated[
        int,
        Query(ge=1, le=MAX_PAGE_LIMIT, description="Page size; 1..200."),
    ] = DEFAULT_PAGE_LIMIT,
) -> MessageListOut:
    decoded_cursor = Cursor.decode(cursor) if cursor else None
    page = await repo.list(
        filters=ListFilters(chat_id=chat_id, role=role, since=since, until=until),
        cursor=decoded_cursor,
        limit=limit,
    )
    return MessageListOut(
        items=[MessageOut.model_validate(m) for m in page.items],
        next_cursor=page.next_cursor.encode() if page.next_cursor else None,
    )
