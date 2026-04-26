"""Request-scoped middleware: request id + access log."""

from __future__ import annotations

import time
import uuid

from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging import get_logger, request_id_ctx

REQUEST_ID_HEADER = "X-Request-ID"
logger = get_logger("http")


class RequestContextMiddleware:
    """Assign / propagate a request id and emit a single structured access log."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        incoming = request.headers.get(REQUEST_ID_HEADER)
        request_id = incoming or uuid.uuid4().hex
        token = request_id_ctx.set(request_id)
        start = time.perf_counter()
        status_holder: dict[str, int] = {"status": 0}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                headers: list[tuple[bytes, bytes]] = list(message.get("headers", []))
                headers.append((REQUEST_ID_HEADER.lower().encode(), request_id.encode()))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
            logger.info(
                "http_request",
                method=request.method,
                path=request.url.path,
                status=status_holder["status"],
                latency_ms=elapsed_ms,
                client=request.client.host if request.client else None,
            )
            request_id_ctx.reset(token)


def access_response_handler(response: Response, request_id: str) -> Response:
    response.headers[REQUEST_ID_HEADER] = request_id
    return response


__all__ = ["REQUEST_ID_HEADER", "RequestContextMiddleware", "access_response_handler"]
