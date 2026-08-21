# AGENTS.md

Guidance for AI coding agents working in this repository.

## Project Overview

**PDFTalk v2.0** is a production SaaS that lets users upload PDFs and chat with them through a Retrieval-Augmented Generation (RAG) pipeline:

1. **Upload** — Multipart or presigned S3 upload (max 50 MB; PDF, TXT, Markdown)
2. **Extract** — PyMuPDF text extraction; Tesseract OCR fallback for scanned pages
3. **Chunk** — 512-token chunks with 64-token overlap (cl100k_base tokenizer)
4. **Embed** — OpenAI `text-embedding-3-small` (1536-dim), L2-normalized vectors
5. **Store** — pgvector `vector(1536)` with HNSW index; dot product == cosine (`<=>`)
6. **Retrieve** — Top-k similarity search filtered by chat's document set
7. **Answer** — OpenAI `gpt-4o-mini` streaming with citation-aware prompt

Production: `https://pdftalk.kanavsingla.fyi` — AWS Lightsail ap-south-1, 2 vCPU / 2 GB / 60 GB SSD, Docker Compose.

## Tech Stack

- **Backend**: Python 3.12, FastAPI (async), SQLAlchemy 2 async + asyncpg, Alembic, pgvector (Postgres 15), Redis 7 + RQ, S3 presigned uploads, OpenAI, PyMuPDF, pytesseract, Resend email, structlog, Prometheus. Package manager: **uv**. Entry point: `backend/app/main.py` (**not** `backend/main.py`, which is a placeholder).
- **Frontend**: Next.js 15.5 (App Router), React 19.2, TypeScript 5, Tailwind CSS 4, pnpm 11.6, react-markdown (citations), react-dropzone, react-hook-form + zod, sonner, next-themes, jest + testing-library.
- **Infra**: Nginx reverse proxy, Docker Compose, GitHub Actions (CI + approval-gated deploy), Prometheus/Grafana/Alertmanager (on-demand profile).

## Repository Layout

```
PDFTalk/
├── backend/
│   ├── app/
│   │   ├── main.py               # FastAPI entry: lifespan, routers, CORS, middleware
│   │   ├── exceptions.py         # Typed exceptions → centralized HTTP error mapping
│   │   ├── core/
│   │   │   ├── config.py         # pydantic-settings; env file from ENV_FILE
│   │   │   └── sentinel.py       # Sentinel guard wiring (vendored rate limiter)
│   │   ├── routers/              # auth, documents, query, chats, health, internal
│   │   ├── services/             # document_service, retrieval, prompt, llm, extraction,
│   │   │                         #   chunking, embedding, file_validation, query_validation,
│   │   │                         #   chats, alerting, user_service, email_verification
│   │   ├── workers/              # RQ: ingest, worker, queues, tasks, queue_poller, failure_handler
│   │   ├── auth/                 # dependencies, tokens (JWT + refresh rotation), password
│   │   ├── models/               # SQLAlchemy models + Pydantic schemas
│   │   ├── utils/                # rate_limit, openai_client, metrics, s3_client, redis_client, logging, email
│   │   ├── middleware/           # security (HSTS/security headers), logging (request_id)
│   │   └── db/                   # session (async engine + get_db), base
│   ├── alembic/                  # migrations
│   ├── tests/                    # pytest; in-memory SQLite + fakeredis + moto
│   ├── vendor/                   # sentinel-0.1.0-py3-none-any.whl (vendored)
│   ├── pyproject.toml            # uv-managed deps, ruff (line-length 100), mypy strict
│   └── Dockerfile, Dockerfile.worker
├── frontend/
│   └── src/
│       ├── app/                  # App Router: auth pages, dashboard, admin
│       ├── components/           # UploadForm, chat UI, etc.
│       ├── contexts/             # AuthContext, ChatContext
│       ├── lib/                  # api.ts + typed clients (auth/documents/chats/query)
│       ├── middleware.ts         # route guard (refresh_token cookie presence)
│       └── env.ts                # zod-validated NEXT_PUBLIC_* env
├── infra/nginx/nginx.prod.conf
├── docker-compose.yml            # prod: memory budgets + observability profile
├── docker-compose.dev.yml
└── .github/workflows/ci.yml, deploy.yml
```

## Backend Architecture

### Entry & Lifespan (`app/main.py`)
Lifespan: configures structlog, checks DB connectivity, pings Redis, loads Sentinel scripts. Registers routers, CORS, and middleware. Adds `X-Request-ID` and security headers; strips query strings from logs.

### Routers (`app/routers/`)
- `auth.py` — register (always 202, no enumeration leak), login (rate-limited), refresh (rotation), logout, verify-email, password reset.
- `documents.py` — list, multipart upload, presigned initiate/confirm upload, delete, metadata, admin override.
- `query.py` — `POST /query/ask` returns **SSE** (EventSource can't POST; client uses fetch + ReadableStream). Events: token data, `[DONE]`, `{"error":...}`, `{"type":"fallback"}`, `{"type":"meta","missing_document_ids":[...]}`.
- `chats.py` — CRUD + chat creation rate limit.
- `health.py` — liveness/readiness probes.
- `internal.py` — admin/internal endpoints (alerting webhook, metrics on internal only).

### Auth (`app/auth/`)
- JWT access tokens: 15 min, HS256, claims `sub/iat/exp/jti/type`.
- Opaque refresh tokens: SHA-256 hashed in DB, httpOnly cookie, **rotated on every use**.
- Two dependencies: `get_current_user()` (token only, no DB) and `get_verified_user()` (DB fetch + `is_active`/`is_verified`).
- Login flow in `services/user_service.py`: timing-safe dummy hash for unknown emails, 10 failed attempts → 15-min lockout, lockout/active status not leaked (all map to `InvalidCredentialsError` → 401; unverified → 403).
- **Known bug**: a non-UUID JWT `sub` causes an unhandled 500 at `backend/app/auth/dependencies.py:78`.

### Document Lifecycle
State machine (authoritative in `services/document_service.py` + `models/document.py`):

```
PENDING_UPLOAD → PENDING → PROCESSING → READY | FAILED
                              FAILED → PROCESSING  (retry)
```

Upload quota counts all non-FAILED statuses including `PENDING_UPLOAD` (intentional).

### Upload Flow
- Legacy multipart: `POST /documents/upload`.
- Presigned: `POST /documents/initiate-upload` → browser PUT to S3 → `POST /documents/confirm-upload` (HeadObject verify) → enqueue RQ ingest job.

### Workers (RQ)
- Queues: `ingest` (heavy; `default_timeout=600`, retries `[60, 300, 900]` via `RETRY_DELAYS`), `default` (email/light tasks).
- `workers/ingest.py`: extract → chunk → embed → store via `_run_async` bridge (sync worker context calls `asyncio.run()`), classifies errors as retryable vs permanent.
- `workers/failure_handler.py`: on retry exhaustion marks doc `FAILED` and writes a `JobLog` (attempt/error/traceback).
- `workers/tasks.py`: periodic cleanup (stale `PENDING_UPLOAD` S3 orphans, etc.).
- Uses a **separate sync engine** (`+psycopg`), created lazily in `failure_handler.py`.

### Services
- `document_service.py` — state transitions, quota, ownership checks.
- `retrieval.py` — pgvector similarity search filtered by chat's documents.
- `prompt.py` / `llm.py` — citation-aware prompt building and gpt-4o-mini streaming.
- `extraction.py` — PyMuPDF; Tesseract OCR fallback for scanned pages.
- `chunking.py` — CHUNK_SIZE=512, CHUNK_OVERLAP=64, cl100k_base (matches embedding + LLM tokenizer).
- `embedding.py` — OpenAI embeddings, L2-normalized.
- `file_validation.py` — MIME/extension/size (50 MB) validation.
- `query_validation.py`, `chats.py`, `alerting.py`, `user_service.py`, `email_verification.py`.

### Data Models (`app/models/`)
`User`, `Document` (+ `DocumentStatus`), `Chunk` (+ `EMBEDDING_DIMENSIONS`, HNSW index `idx_chunks_embedding_hnsw`, m=16, ef_construction=64, `vector_cosine_ops`), `Chat`, `Message` (+ `MessageRole`/`MessageStatus`), `RefreshToken`, `EmailVerification`, `JobLog`, `QueryRequest`. Pydantic schemas co-located with ORM models. Import order in `models/__init__.py` matters for relationship forward refs.

### DB Session (`app/db/session.py`)
Single async engine (pool_size=10, max_overflow=5, pool_pre_ping, pool_recycle=3600); `get_db` commits on success / rolls back on error. Workers use a separate lazy sync engine.

### Error Handling (`app/exceptions.py`)
Typed exception hierarchy mapped centrally to HTTP responses with shape `{"error": "CODE", "message": "..."}`. **Never** raise `HTTPException` from services — use typed exceptions.

### Config (`app/core/config.py`)
pydantic-settings; env file from `ENV_FILE` (default `.env.local`). `ENVIRONMENT` defaults to `"production"` (safe default — be explicit in dev). `JWT_SECRET_KEY` must be ≥ 32 chars. Key settings: `DATABASE_URL`, `REDIS_URL`, `S3_*`, `OPENAI_API_KEY`, `ADMIN_TOKEN`, `SENTINEL_REDIS_URL`, `ANONYMOUS_COOKIE_SECRET`, `PROMETHEUS_MULTIPROC_DIR`, `GRAFANA_*`, `APP_URL`.

### Rate Limiting
All rate limiting uses **Sentinel v1.2.0** (`sentinel-rate-limiter`, import `sentinel`) via `app/core/sentinel.py`. The self-built `RateLimiter` in `app/utils/rate_limit.py` has been removed.

**Seven policies** configured from env-driven settings:

| Policy ID | Endpoints | Identity | Algorithm | Limit | Window | Fail Mode |
|---|---|---|---|---|---|---|
| `pdftalk.auth.register` | `POST /auth/register` | anonymous (cookie + IP) | token_bucket | 5 | 1 hr | fail_open |
| `pdftalk.auth.resend` | `POST /auth/resend-verification` | anonymous | token_bucket | 5 | 1 hr | fail_open |
| `pdftalk.auth.login` | `POST /auth/login` | anonymous | token_bucket | 10 | 1 min | fail_open |
| `pdftalk.auth.reset` | `POST /auth/forgot-password` | anonymous | token_bucket | 3 | 1 hr | fail_open |
| `pdftalk.documents.upload` | `/upload` + `/initiate-upload` (shared) | tenant_jwt | sliding_window | 5 | 60 s | fail_open |
| `pdftalk.query.ask` | `POST /query/ask` | tenant_jwt | sliding_window | 20 | 60 s | fail_open |
| `pdftalk.chats.create` | `POST /chats` | tenant_jwt | sliding_window | 10 | 60 s | fail_open |

**Anonymous endpoints** use Sentinel's dual-bucket identity: HMAC-signed device cookie (`pdftalk_anon_id`, 30-day TTL) + trusted `request.client.host` IP — AND semantics. **Authenticated endpoints** use validated JWT `sub` (hashed to sha256).

**Failure semantics**: all policies are `fail_open` with per-process emergency limiter (`fallback_rate_per_process_micro`). Redis failure → capped pass-through, not unlimited. 20 ms socket timeout; circuit breaker (5 failures → OPEN 30 s).

**Sentinel Redis**: dedicated instance (`sentinel-redis` container), `maxmemory-policy noeviction` enforced at startup. Config built from env: `SENTINEL_REDIS_URL`, `ANONYMOUS_COOKIE_SECRET`, `JWT_SECRET_KEY`, `JWT_ALGORITHM`.

**Error contract preserved**: 429 → `RATE_LIMIT_EXCEEDED` + `Retry-After`; 503 → `RATE_LIMITER_UNAVAILABLE`. Adapter in `app/core/sentinel.py` converts Sentinel's `HTTPException` to PDFTalk typed exceptions.

**Observability**: `sentinel_decisions_total` (counter) + `sentinel_evaluate_latency_microseconds` (histogram) on `/metrics`; denial logs with `identity_mode`, `identity_hash`, `endpoint_id`, `decision_reason`, `latency_micro`, `breaker_state`.

### Metrics (`app/utils/metrics.py`)
Prometheus multiprocess mode. **All metrics are module-level singletons** — never instantiate inside functions (duplicate-registration ValueError). High-cardinality labels only on low-frequency metrics.

### Logging (`app/utils/logging.py`)
structlog. Scrubs keys: `password, password_hash, token, access_token, refresh_token, token_hash, email, email_lower, authorization, content`. `RequestLoggingMiddleware` adds `request_id` (from `X-Request-ID`) + summary line; query strings stripped.

## Frontend Architecture

### API Layer (`src/lib/`)
- `api.ts` — `apiRequest`/`apiFetch`, `ApiError` (code/message/status/retryAfter), differentiates 401 as `TOKEN_EXPIRED` vs `INVALID_TOKEN`, `credentials: 'include'` on `/auth/*`.
- `auth.api.ts` / `documents.api.ts` (presigned 3-phase upload) / `chats.api.ts` / `query.api.ts` (SSE reader).
- `env.ts` — zod-validates `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_APP_NAME`, `NEXT_PUBLIC_MAX_UPLOAD_MB`.

### Contexts
- `AuthContext.tsx` — in-memory access token + refresh timer; session restore.
- `ChatContext.tsx` — chat state + SSE streaming.

### Routing
App Router pages: auth (`/login`, `/register`, `/verify-email`, `/forgot-password`), dashboard, admin. `src/middleware.ts` guards routes based on `refresh_token` cookie presence only.

## Infra & Deployment

### Nginx (`infra/nginx/nginx.prod.conf`)
- Upstreams `api:8000` and `frontend:3000`.
- `limit_req_zone api_global` 30 req/s per IP.
- Blocks `/docs` and `/metrics` (metrics exposed on internal network only).
- Handles SSE proxying. **HSTS is set by nginx** — do not duplicate it in app middleware.

### Docker Compose (prod)
- Memory budgets: core total 1696M (postgres+redis+sentinel-redis+api+worker+frontend+nginx).
- **Observability (Prometheus/Grafana/Alertmanager) is NOT 24/7** — adds ~304M to the 2 GB budget. Start on demand with:
  `docker compose --profile observability up -d`
- ~10 alert rules; Alertmanager webhook → `POST /internal/alerts/webhook` → `services/alerting.py` → Resend email + Slack.
- Dev compose: Postgres on port 5433, Redis 6379, api 8000, sentinel-redis with `SENTINEL_REDIS_PASSWORD`.

### CI/CD (`.github/workflows/`)
- `ci.yml` — PRs to main: ruff, mypy, pytest (**coverage gate 61%**), Trivy. Services: pgvector `pg15` + `redis:7`.
- `deploy.yml` — push to main: build GHCR images → **approval-gated** SSH deploy to Lightsail. Concurrency group `deploy-production` (cancel-in-progress).

## Development Workflow

```bash
make dev        # .venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
make test       # pytest
make deploy     # placeholder — actual deploy via GitHub Actions
```

- Install: `uv sync` in `backend/`; `pnpm install` in `frontend/`.
- Backend linters: `ruff` (line-length 100), `mypy --strict`. Frontend: `next lint` / tsc / jest.
- Tests: pytest with `asyncio_mode=auto`; `integration` marker for tests needing real services. Fixtures in `tests/conftest.py`: in-memory SQLite sessions (fresh schema per test), fakeredis (autouse), moto for S3, mocked email queues, `verified_user` + `auth_headers`. **conftest sets env vars before any `app.*` import** — keep it that way or `Settings()` will fail at collection.

## Gotchas & Conventions

- Workers run sync code calling async services via `asyncio.run()` — each call creates a fresh loop; the async Redis client must create a per-loop pool (never share a loop-bound pool across loops).
- Never instantiate Prometheus metrics inside functions — module-level singletons only.
- Never raise `HTTPException` from services — use typed exceptions from `app/exceptions.py`.
- Upload quota counts `PENDING_UPLOAD` — a user can exhaust quota by starting uploads without confirming them.
- Don't add a second HSTS header in middleware — nginx owns it.
- Log scrubbing is on fixed key names — keep those keys consistent or extend `utils/logging.py`.
- `ENVIRONMENT` defaults to `"production"` — be explicit in local dev.
- Embeddings are L2-normalized so dot product equals cosine for pgvector `<=>`.
- Chunk size/overlap and tokenizer must stay consistent across `chunking.py`, the embedding model, and `gpt-4o-mini`.
- **Sentinel**: `SENTINEL_REDIS_URL` must include password (redis://:pwd@host). `ANONYMOUS_COOKIE_SECRET` min 32 chars, separate from `JWT_SECRET_KEY`. Sentinel Redis requires `noeviction` + bounded `maxmemory` — `assert_noeviction()` runs at startup. Anonymous cookie uses `request.client.host` (never `X-Forwarded-For`). Sentinel structured denial fields preserved via `_copy_stdlib_extras` in logging config.
