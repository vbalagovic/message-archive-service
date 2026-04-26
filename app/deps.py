"""Centralised FastAPI dependencies.

Re-exporting the few things handlers actually need keeps imports short and
makes the dependency surface obvious in one place.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_api_key
from app.db.session import get_session
from app.domain.repository import MessageRepository

DbSession = Annotated[AsyncSession, Depends(get_session)]
ApiKeyId = Annotated[str, Depends(require_api_key)]


async def get_repository(session: DbSession) -> MessageRepository:
    return MessageRepository(session)


Repository = Annotated[MessageRepository, Depends(get_repository)]
