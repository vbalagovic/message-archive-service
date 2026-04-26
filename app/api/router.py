"""v1 API router aggregation."""

from __future__ import annotations

from fastapi import APIRouter

from app.api import messages

api_router = APIRouter()
api_router.include_router(messages.router, prefix="/messages", tags=["messages"])
