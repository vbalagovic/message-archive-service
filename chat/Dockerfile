# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.5.14 /uv /usr/local/bin/uv

WORKDIR /build

COPY chat/pyproject.toml chat/README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-install-project

COPY chat ./chat
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync


FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/app"

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl tini \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --system --gid 1001 app \
 && useradd  --system --uid 1001 --gid app --no-create-home --shell /usr/sbin/nologin app

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY chat /app/chat
COPY ui /app/ui
RUN chown -R app:app /app

USER app
EXPOSE 8001

HEALTHCHECK --interval=10s --timeout=3s --retries=5 --start-period=10s \
  CMD curl -fsS http://127.0.0.1:8001/api/health || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "chat.main:app", "--host", "0.0.0.0", "--port", "8001"]
