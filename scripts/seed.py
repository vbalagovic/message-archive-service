"""Insert sample messages so /docs is fun to play with."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.db.session import dispose_engine, get_sessionmaker
from app.domain.models import MessageRole
from app.domain.repository import MessageRepository

SAMPLE_CONVERSATIONS = [
    [
        ("user", "What's the weather like in Berlin today?"),
        ("ai", "I can't check live weather, but you could try a weather API or app."),
        ("user", "OK, can you write me a Python snippet that calls one?"),
        ("ai", "Sure — here's a small example using the Open-Meteo free API..."),
    ],
    [
        ("user", "Explain CAP theorem in one paragraph."),
        (
            "ai",
            "In a distributed system you can simultaneously guarantee at most two of: "
            "Consistency, Availability, and Partition tolerance.",
        ),
    ],
]


async def main() -> None:
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        repo = MessageRepository(session)
        ts = datetime.now(UTC)
        for chat in SAMPLE_CONVERSATIONS:
            chat_id = uuid4()
            for offset, (role, content) in enumerate(chat):
                await repo.upsert(
                    message_id=uuid4(),
                    chat_id=chat_id,
                    content=content,
                    sent_at=ts + timedelta(seconds=offset),
                    role=MessageRole(role),
                    rating=None,
                )
        await session.commit()
        total = await repo.count()
        print(f"Seed complete. Total messages: {total}")
    await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
