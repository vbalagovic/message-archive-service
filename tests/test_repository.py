from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import MessageRole
from app.domain.repository import ListFilters, MessageRepository
from tests.conftest import utc_at


@pytest.fixture
def repo(session: AsyncSession) -> MessageRepository:
    return MessageRepository(session)


async def test_upsert_creates_then_replaces(repo: MessageRepository, session: AsyncSession) -> None:
    mid = uuid4()
    cid = uuid4()
    first = await repo.upsert(
        message_id=mid,
        chat_id=cid,
        content="one",
        sent_at=utc_at(0),
        role=MessageRole.USER,
        rating=None,
    )
    await session.commit()
    assert first.created is True
    assert first.message.content == "one"

    second = await repo.upsert(
        message_id=mid,
        chat_id=cid,
        content="two",
        sent_at=utc_at(1),
        role=MessageRole.AI,
        rating=True,
    )
    await session.commit()
    assert second.created is False
    assert second.message.content == "two"
    assert second.message.role == MessageRole.AI
    assert second.message.rating is True


async def test_patch_returns_none_when_missing(
    repo: MessageRepository, session: AsyncSession
) -> None:
    result = await repo.patch(uuid4(), content="hi", rating_set=False)
    assert result is None


async def test_patch_clears_rating(repo: MessageRepository, session: AsyncSession) -> None:
    mid = uuid4()
    await repo.upsert(
        message_id=mid,
        chat_id=uuid4(),
        content="x",
        sent_at=utc_at(0),
        role=MessageRole.USER,
        rating=True,
    )
    await session.commit()

    updated = await repo.patch(mid, rating=None, rating_set=True)
    assert updated is not None
    assert updated.rating is None


async def test_list_orders_by_sent_at_then_id(
    repo: MessageRepository, session: AsyncSession
) -> None:
    same_time = utc_at(0)
    ids = sorted([uuid4() for _ in range(3)])
    for mid in reversed(ids):  # insert in reverse to make sure ORDER BY does the work
        await repo.upsert(
            message_id=mid,
            chat_id=uuid4(),
            content="x",
            sent_at=same_time,
            role=MessageRole.USER,
            rating=None,
        )
    await session.commit()

    page = await repo.list(filters=ListFilters(), cursor=None, limit=10)
    assert [m.message_id for m in page.items] == ids


async def test_list_filters_compose(repo: MessageRepository, session: AsyncSession) -> None:
    chat = uuid4()
    for i in range(4):
        await repo.upsert(
            message_id=uuid4(),
            chat_id=chat if i % 2 == 0 else uuid4(),
            content=f"m{i}",
            sent_at=utc_at(i),
            role=MessageRole.USER if i % 2 == 0 else MessageRole.AI,
            rating=None,
        )
    await session.commit()

    page = await repo.list(
        filters=ListFilters(chat_id=chat, role=MessageRole.USER),
        cursor=None,
        limit=10,
    )
    assert len(page.items) == 2
    assert all(m.chat_id == chat for m in page.items)
    assert all(m.role == MessageRole.USER for m in page.items)


async def test_count_helper(repo: MessageRepository, session: AsyncSession) -> None:
    for _ in range(3):
        await repo.upsert(
            message_id=uuid4(),
            chat_id=uuid4(),
            content="x",
            sent_at=utc_at(0),
            role=MessageRole.USER,
            rating=None,
        )
    await session.commit()
    assert await repo.count() == 3
