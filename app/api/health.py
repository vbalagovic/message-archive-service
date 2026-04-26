"""Liveness + readiness probes.

``/healthz`` is process-only (it returns 200 as soon as the event loop is
serving). ``/readyz`` checks the database — k8s-style separation so a
flaky DB doesn't make us get killed and restarted in a loop.
"""

from __future__ import annotations

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from app.deps import Repository

router = APIRouter(tags=["health"])


@router.get("/healthz", include_in_schema=False)
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz", include_in_schema=False)
async def readyz(repo: Repository) -> JSONResponse:
    try:
        await repo.ping()
    except Exception as exc:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "unavailable", "reason": str(exc)},
        )
    return JSONResponse(status_code=status.HTTP_200_OK, content={"status": "ready"})
