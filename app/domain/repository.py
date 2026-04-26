"""Data-access for messages.

Pure SQLAlchemy; no FastAPI imports. Anything that wants to talk to the
``messages`` table goes through this class.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, literal_column, or_, select
from sqlalchemy import func as sa_func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import Cursor
from app.domain.models import Message, MessageRole


@dataclass(frozen=True, slots=True)
class ListFilters:
    chat_id: UUID | None = None
    role: MessageRole | None = None
    since: datetime | None = None
    until: datetime | None = None


@dataclass(frozen=True, slots=True)
class UpsertResult:
    message: Message
    created: bool


@dataclass(frozen=True, slots=True)
class PageResult:
    items: list[Message]
    next_cursor: Cursor | None


class MessageRepository:
    """All persistence operations for messages."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------
    async def upsert(
        self,
        *,
        message_id: UUID,
        chat_id: UUID,
        content: str,
        sent_at: datetime,
        role: MessageRole,
        rating: bool | None,
    ) -> UpsertResult:
        """Idempotent create-or-replace keyed on ``message_id``.

        Uses Postgres ``INSERT ... ON CONFLICT`` so concurrent writers cannot
        race past a "select then insert" check.
        """
        stmt: Any = (
            pg_insert(Message)
            .values(
                message_id=message_id,
                chat_id=chat_id,
                content=content,
                sent_at=sent_at,
                role=role,
                rating=rating,
            )
            .on_conflict_do_update(
                index_elements=[Message.message_id],
                set_={
                    "chat_id": chat_id,
                    "content": content,
                    "sent_at": sent_at,
                    "role": role,
                    "rating": rating,
                },
            )
            # xmax=0 is Postgres's tell-tale that the row came from INSERT (not the
            # ON CONFLICT UPDATE branch). Bullet-proof regardless of trigger timing.
            .returning(Message, literal_column("(xmax = 0)").label("created"))
        )
        row = (await self._session.execute(stmt)).one()
        message: Message = row[0]
        created: bool = bool(row[1])
        await self._session.flush()
        # Identity map may already hold a stale copy of this row (true on the
        # ON CONFLICT update branch); refresh so the caller sees the new values.
        await self._session.refresh(message)
        return UpsertResult(message=message, created=created)

    async def patch(
        self,
        message_id: UUID,
        *,
        content: str | None = None,
        rating: bool | None = None,
        rating_set: bool = False,
    ) -> Message | None:
        """Partial update.

        ``rating_set`` lets the caller distinguish "leave as-is" from "set to NULL".
        ``content`` cannot be set to ``None`` (NOT NULL), so absence == leave.
        """
        message = await self.get(message_id)
        if message is None:
            return None
        if content is not None:
            message.content = content
        if rating_set:
            message.rating = rating
        await self._session.flush()
        # The BEFORE UPDATE trigger bumps updated_at server-side; refresh so that
        # accessing the attribute later (post-commit, post-greenlet) doesn't try
        # to lazy-load.
        await self._session.refresh(message)
        return message

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    async def get(self, message_id: UUID) -> Message | None:
        return await self._session.get(Message, message_id)

    async def list(
        self,
        *,
        filters: ListFilters,
        cursor: Cursor | None,
        limit: int,
    ) -> PageResult:
        """Cursor-paginated listing, ordered by (sent_at ASC, message_id ASC).

        Cursor stability: tie-breaking on ``message_id`` makes the order total,
        so a row inserted with the same ``sent_at`` as the cursor cannot
        silently shift the page boundary.
        """
        stmt = select(Message)
        conditions: list[Any] = []
        if filters.chat_id is not None:
            conditions.append(Message.chat_id == filters.chat_id)
        if filters.role is not None:
            conditions.append(Message.role == filters.role)
        if filters.since is not None:
            conditions.append(Message.sent_at >= filters.since)
        if filters.until is not None:
            conditions.append(Message.sent_at <= filters.until)
        if cursor is not None:
            conditions.append(
                or_(
                    Message.sent_at > cursor.sent_at,
                    and_(
                        Message.sent_at == cursor.sent_at,
                        Message.message_id > cursor.message_id,
                    ),
                )
            )
        if conditions:
            stmt = stmt.where(*conditions)

        stmt = stmt.order_by(Message.sent_at.asc(), Message.message_id.asc()).limit(limit + 1)

        rows = list((await self._session.execute(stmt)).scalars().all())
        if len(rows) > limit:
            last = rows[limit - 1]
            return PageResult(
                items=rows[:limit],
                next_cursor=Cursor(sent_at=last.sent_at, message_id=last.message_id),
            )
        return PageResult(items=rows, next_cursor=None)

    async def ping(self) -> None:
        """Cheap readiness probe (SELECT 1)."""
        await self._session.execute(select(1))

    # ------------------------------------------------------------------
    # Test helpers (used by tests/seed scripts only)
    # ------------------------------------------------------------------
    async def count(self) -> int:
        result = await self._session.execute(select(sa_func.count()).select_from(Message))
        return int(result.scalar_one())
