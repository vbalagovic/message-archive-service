# Message Archive Service

[![CI](https://github.com/USER/REPO/actions/workflows/ci.yml/badge.svg)](https://github.com/USER/REPO/actions/workflows/ci.yml)
![Python 3.12](https://img.shields.io/badge/python-3.12-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-async-009485)
![Postgres 16](https://img.shields.io/badge/Postgres-16-336791)

A small REST service that archives chat messages exchanged between users and an
AI assistant. Built as a take-home assignment; written like production code.

---

## Table of contents

1. [Quickstart](#quickstart-under-a-minute)
2. [Architecture](#architecture)
3. [API](#api)
4. [Local development](#local-development)
5. [Configuration](#configuration)
6. [Architecture decisions (ADRs)](#architecture-decisions-adrs)
7. [Quality gates](#quality-gates)
8. [Security posture](#security-posture)
9. [Operational runbook](#operational-runbook)
10. [Documented deviations from the brief](#documented-deviations-from-the-brief)
11. [Optional: local LLM + chat UI](#optional-local-llm--chat-ui)
12. [What I'd add with more time](#what-id-add-with-more-time)

---

## Quickstart (under a minute)

```bash
git clone <repo> && cd ingassg
cp .env.example .env
make up          # builds the image, starts Postgres, applies migrations, waits for /readyz
```

Then:
- Swagger UI: <http://localhost:8000/docs>
- Health:  `curl http://localhost:8000/healthz`
- Sample data: `make seed`

Hit the API with the dev key from `.env`:

```bash
MID=$(uuidgen | tr '[:upper:]' '[:lower:]')
CID=$(uuidgen | tr '[:upper:]' '[:lower:]')

# Create
curl -X PUT "http://localhost:8000/api/v1/messages/$MID" \
  -H "X-API-Key: dev-key-change-me" \
  -H "Content-Type: application/json" \
  -d "{\"message_id\":\"$MID\",\"chat_id\":\"$CID\",\"content\":\"Hi!\",\"rating\":null,\"sent_at\":\"2026-04-26T10:00:00Z\",\"role\":\"user\"}"

# Rate
curl -X PATCH "http://localhost:8000/api/v1/messages/$MID" \
  -H "X-API-Key: dev-key-change-me" \
  -H "Content-Type: application/json" \
  -d '{"rating": true}'

# List
curl "http://localhost:8000/api/v1/messages?limit=10" -H "X-API-Key: dev-key-change-me"
```

There's also a comprehensive `test.sh` in the repo root that exercises every
endpoint plus all failure modes (`bash test.sh`).

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                     FastAPI (uvicorn)                    │
│                                                          │
│   Middleware:  request-id ─► structured JSON access log  │
│                rate limit (per-key)                      │
│                CORS (off by default)                     │
│   Errors:      consistent { "error": { code, message } } │
│   Auth:        X-API-Key (constant-time compare)         │
│                                                          │
│   Routes:      PUT  /api/v1/messages/{id}                │
│                PATCH /api/v1/messages/{id}               │
│                GET  /api/v1/messages                     │
│                GET  /healthz  /readyz  /metrics?         │
└──────────────────────────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────┐
│  Domain layer                                            │
│   schemas (Pydantic v2)  ◄──► repository (SA 2.0 async)  │
│                                  ▲                       │
└──────────────────────────────────┼───────────────────────┘
                                   ▼
                         ┌──────────────────┐
                         │ Postgres 16      │
                         │ messages table   │
                         │ + trigger        │
                         └──────────────────┘
```

Layered separation — handlers → domain → db. The repository is the **only**
place that touches SQLAlchemy; handlers stay thin and never see ORM models. See
`app/` for the layout.

```
app/
├── api/        # FastAPI routers (messages, health) — thin handlers
├── core/       # cross-cutting: auth, errors, logging, metrics, middleware,
│               # pagination, rate limit
├── db/         # async engine + Alembic migrations
├── domain/     # ORM models, Pydantic DTOs, repository
├── config.py   # Pydantic Settings (env-driven)
├── deps.py     # FastAPI dependency aliases
└── main.py     # app factory, lifespan
```

---

## API

| Method | Path                              | Body / Query                                            | Notes |
|--------|-----------------------------------|---------------------------------------------------------|-------|
| `PUT`    | `/api/v1/messages/{message_id}`   | full `MessageIn`                                        | Idempotent create-or-replace; **201** on create, **200** on replace. |
| `PATCH`  | `/api/v1/messages/{message_id}`   | partial: `content` and/or `rating`                       | **404** if not found, **422** on unknown field. |
| `GET`    | `/api/v1/messages`                | `chat_id`, `role`, `since`, `until`, `cursor`, `limit`  | Cursor pagination, `limit` ∈ [1, 200], default 50. Sort key is `(sent_at, message_id)`. |
| `GET`    | `/healthz`, `/readyz`, `/metrics` | —                                                        | Liveness, DB ping, optional Prometheus. |

Full schema in OpenAPI at `/docs` and `/openapi.json`.

**Error envelope** (every non-2xx):
```json
{ "error": { "code": "NOT_FOUND", "message": "...", "request_id": "..." } }
```

**Why `PUT` and not `POST`?** The brief's schema includes a client-supplied
`message_id`. With client-owned identity, `PUT /messages/{id}` is the correct
verb: it's idempotent on retry (a network blip can't create a duplicate),
which a `POST` is not. `PATCH` is added for the realistic partial-update flow
(setting `rating` later) without requiring the client to re-send the whole body.

---

## Local development

```bash
make install       # uv sync into .venv
make fmt           # ruff format + auto-fix
make lint          # ruff check
make typecheck     # mypy --strict
make test          # full suite (uses testcontainers, needs Docker)
make ci            # everything CI runs
```

Pre-commit hooks (optional but recommended):
```bash
uv run pre-commit install
```

Migrations:
```bash
make migrate                    # apply latest
make revision m="add foo"       # autogenerate new revision
make downgrade                  # step one back
```

---

## Configuration

All knobs live in environment variables. Full list in `.env.example`:

| Var                        | Default                                                 | Purpose |
|----------------------------|---------------------------------------------------------|---------|
| `DATABASE_URL`             | `postgresql+asyncpg://archive:archive@db:5432/archive`  | Async SA URL. **Must** use `+asyncpg`. |
| `API_KEYS`                 | `dev-key-change-me`                                     | Comma-separated allow-list. **Change in prod.** |
| `LOG_LEVEL`                | `INFO`                                                  | DEBUG/INFO/WARNING/ERROR/CRITICAL. |
| `ENABLE_METRICS`           | `false`                                                 | Enables `/metrics` (Prometheus). |
| `RATE_LIMIT_PER_MINUTE`    | `120`                                                   | Per-key (or per-IP for unauth) ceiling. |
| `MAX_CONTENT_LENGTH`       | `32768`                                                 | Bytes. Bodies past this are **422**. |
| `CORS_ORIGINS`             | `` (off)                                                | Comma-separated allowlist when enabled. |

---

## Architecture decisions (ADRs)

Compact rationale for every non-trivial choice — kept inline so reviewers
don't have to navigate.

### ADR-001 · FastAPI for the HTTP layer
**Decision:** FastAPI.
**Why:** Native async, Pydantic-driven validation, auto-generated OpenAPI/Swagger
UI, smallest cognitive load for skim-reading.
**Alternatives:** Flask (sync, manual schema), Litestar (less familiar to
reviewers). Django was forbidden by the brief.

### ADR-002 · SQLAlchemy 2.0 async + asyncpg
**Decision:** SA 2.0 with the async session API and the asyncpg driver.
**Why:** Type-safe `Mapped[...]` API, clean async story, canonical Alembic
migrations. asyncpg is the fastest Postgres driver for Python.
**Alternatives:** Tortoise/Piccolo (smaller ecosystems), raw asyncpg
(re-implement the wheel).

### ADR-003 · Alembic for schema migrations
**Decision:** Alembic, configured to read `DATABASE_URL` from the environment.
**Why:** Industry standard, integrates with SA metadata. The initial migration
is hand-written so enum + trigger creation are explicit.
**Alternatives:** yoyo, plain `Base.metadata.create_all` (only acceptable in tests).

### ADR-004 · Pydantic v2 DTOs (separate from ORM)
**Decision:** Pydantic v2 BaseModels for request/response shapes in
`app/domain/schemas.py`. ORM models live in `models.py` and are **never**
returned directly from handlers.
**Why:** Strict mode catches unknown fields and bad types at the boundary.
Separation means storage and wire shapes can change independently.
**Alternatives:** Marshmallow (older, slower); returning ORM directly (leaks columns).

### ADR-005 · API-key auth via `X-API-Key`
**Context:** The brief says "endpoints should be secured" but the component is
service-to-service — there is no end-user identity, no session.
**Decision:** API-key auth. Keys live in `API_KEYS` (CSV env var), are compared
in constant time, and never logged. A short SHA-256 fingerprint of the matched
key is logged so you can audit *which key did what* without exposing the secret.
**Why not JWT/OAuth?** Both imply a user identity model that does not exist here.
**Why not mTLS?** Operationally heavier than is justified for a take-home; would
revisit for real service-to-service deployment.
**Why not Basic auth?** Equivalent strength, weaker UX, and most clients leak
credentials in logs.

### ADR-006 · `PUT` for create-or-replace, `PATCH` for partial
**Decision:**
- `PUT /messages/{message_id}` — full create-or-replace, idempotent.
- `PATCH /messages/{message_id}` — partial update (typical use: set `rating`).

**Why:** The schema in the brief includes a client-supplied `message_id`. That
makes `PUT` the natural REST verb (idempotent on retry). `POST` would imply
server-assigned ids, which contradicts the schema. `PATCH` exists because the
realistic update flow is "user clicks thumbs-up later" — sending the full body
each time is wasteful and racy.

### ADR-007 · Structured JSON logging with structlog
**Decision:** structlog emitting one JSON object per log line, with a per-request
`request_id` propagated via `contextvars` and surfaced in both the
`X-Request-ID` response header and the error envelope.
**Why:** Trivially shippable to any log aggregator. Correlating a client-side
error to exact server logs is a single grep.

### ADR-008 · testcontainers + real Postgres for tests
**Decision:** Tests run against a real Postgres container started by
`testcontainers-python`, **not** SQLite or mocks.
**Why:** We use Postgres-specific features (UUID, ENUM, `INSERT ON CONFLICT`,
trigger). SQLite would silently behave differently. Mocks would lie. The
container starts once per session and tables are truncated between tests.
**Trade-off:** Tests need a Docker daemon — acceptable; CI provides one.

### ADR-009 · Cursor pagination, not offset
**Decision:** `GET /messages` paginates by an opaque base64 cursor
`(sent_at, message_id)`. `limit` ∈ [1, 200], default 50.
**Why:** Offset pagination silently skips/duplicates rows under concurrent
writes — for an archive that is constantly being appended to, that is a
correctness bug, not a performance one. Tie-breaking on `message_id` makes
the order total so two rows with identical `sent_at` cannot reorder across pages.
**Why opaque?** Clients should never inspect the cursor; doing so couples
them to its internal shape.

### ADR-010 · `uv` for dependency and venv management
**Decision:** `uv` (astral.sh) as the single tool for lockfile, dependency
resolution, virtualenv, and Python install. `pyproject.toml` + `uv.lock` are
the source of truth.
**Why:** Fast (10–100× pip), reproducible installs via `uv sync --frozen`,
one tool replaces pip / pip-tools / venv / pyenv. Used identically in the
Dockerfile and CI for byte-identical environments.
**Alternatives:** Poetry (slower, heavier), plain pip (no lockfile guarantee).

---

## Quality gates

CI runs on every push / PR (see `.github/workflows/ci.yml`):
- **Quality** — `ruff check`, `ruff format --check`, `mypy --strict`, `bandit`, `pip-audit`.
- **Tests** — `pytest` against a real Postgres service container, coverage **≥ 90 %**.
- **Image** — multi-stage build, Trivy scan, fails on HIGH/CRITICAL CVEs.

Local: `make ci`. Current state: **42 tests passing, 91.7 % coverage, mypy strict clean, ruff clean, bandit 0 issues**.

---

## Security posture

- **API-key auth** on every `/api/v1/*` route — constant-time compare; raw keys
  never logged, only their 8-character SHA-256 fingerprint.
- **Parameterised queries only** (SQLAlchemy) → SQL injection structurally impossible.
- **Pydantic strict mode** — unknown fields rejected (`extra="forbid"`), bad types
  rejected at the boundary.
- **No stack traces leaked** to clients; correlate via `X-Request-ID`.
- **Rate limiting** per key (slowapi); configurable.
- **Container hardening:** non-root user (uid 1001), `cap_drop: ALL`, `read_only`
  rootfs, `no-new-privileges`, tini as PID 1.
- **Image:** multi-stage slim base, Trivy-scanned in CI; `pip-audit` runs on every PR.

---

## Operational runbook

### Starting / stopping
- `make up`   — build and start the stack, waits for `/readyz`.
- `make down` — stop and remove containers + volumes (destructive locally only).
- `make logs` — tail API logs.

### Health & readiness
- `GET /healthz` — process-only liveness. If failing, the process is wedged; restart.
- `GET /readyz`  — checks the database. **503** means we cannot serve requests.
- `GET /metrics` — Prometheus exposition (only when `ENABLE_METRICS=true`).

### Rotating an API key
1. Generate: `python -c "import secrets; print(secrets.token_urlsafe(32))"`
2. Add to `API_KEYS` (keep the old one for overlap).
3. `docker compose up -d api` to roll the API container.
4. Once all clients have switched, remove the old key from `API_KEYS` and roll again.

### Migrations
- Apply: `make migrate` — also runs automatically in `docker/entrypoint.sh` on container start.
- New revision: `make revision m="add column foo"`. Always review the diff.
- Rollback one step: `make downgrade`. Test in staging first.

### Reading logs
Logs are JSON on stdout. Useful filters:
- `jq 'select(.event=="http_request")'`     — access log.
- `jq 'select(.level=="error")'`            — only errors.
- `jq 'select(.request_id=="…")'`           — all events for one request.

### Common errors
| Code | Status | Meaning |
|------|--------|---------|
| `UNAUTHORIZED`     | 401 | Missing or invalid `X-API-Key`. |
| `VALIDATION_ERROR` | 422 | Body or query failed validation. `details.errors` names the offending field. |
| `NOT_FOUND`        | 404 | PATCH against a nonexistent message id. |
| `RATE_LIMITED`     | 429 | Bucket exhausted; lower request rate or raise `RATE_LIMIT_PER_MINUTE`. |
| —                  | 503 | `/readyz` failed → DB unreachable. Check `db` container and `DATABASE_URL`. |

---

## Documented deviations from the brief

1. **`rating` is nullable.** The brief lists it as a required boolean, but a
   message has to exist before it can be rated. We accept `null` and treat
   "not yet rated" as the default. Trivial to flip back to `NOT NULL`.
2. **No `DELETE` endpoint.** Not in the brief; archives generally retain.
3. **Auth is API key, not JWT/OAuth.** The brief says "secured" without specifying;
   this component has no user identity model. See ADR-005.

---

## Optional: local LLM + chat UI

A tiny chat stack you can spin up alongside the archive — useful to *see* the
persistence working. It's a separate Compose **profile**, so default `make up`
does NOT pull a model or start any of it.

```bash
make llm-up          # starts: archive + ollama + chat BFF + UI
                     # first run pulls the configured model (~815 MB for gemma3:1b)
open http://localhost:8001
```

What you get:
- **Ollama** in a container (model volume persisted across restarts).
- **Chat BFF** at `http://localhost:8001` — `chat/` directory, FastAPI, streams via SSE.
- **UI** served by the BFF — sidebar of chats (derived from the archive),
  markdown rendering, thumbs-up/down (PATCHes through the BFF to the archive).
- Every user message and every AI reply lands in the `messages` table:
  ```bash
  curl -s -G http://localhost:8000/api/v1/messages \
    -H "X-API-Key: dev-key-change-me" --data-urlencode "limit=20" | jq
  ```

Switch model via `LLM_MODEL` in `.env`:
| Model | Size |
|-------|------|
| `gemma3:1b` (default) | ~815 MB |
| `gemma3:270m`         | ~290 MB |
| `qwen2.5:0.5b`        | ~500 MB |
| `llama3.2:1b`         | ~1.3 GB |

Other targets:
- `make llm-down`  — stop (keeps model volume)
- `make llm-logs`  — tail BFF + Ollama
- `make llm-purge` — stop **and** delete the model volume

> CPU-only inference inside Docker on Apple Silicon is slow — small models only.
> Native Ollama (`ollama serve` outside Docker) is much faster but isn't what
> the brief asked for.

---

## What I'd add with more time

- **Outbox pattern** + async publisher for downstream analytics consumers.
- **OpenTelemetry** tracing (logs already correlate via `request_id`).
- **Per-tenant API keys** with quotas and audit log.
- **Soft-delete + GDPR export** endpoint.
- **Hypothesis** property tests on the cursor encoder.
- **Locust** load profile and a published p95 number.
- **Stream-resilient persistence** in the chat BFF — currently if the SSE client
  disconnects mid-response, the AI message isn't archived (the streamer never
  reaches the upsert). Fix is `asyncio.shield` plus a tail-persist on disconnect.

---

## License

MIT.
