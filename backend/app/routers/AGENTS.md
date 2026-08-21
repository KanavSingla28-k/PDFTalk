# Routers AGENTS.md

Context for the API routing layer (`backend/app/routers`).

## Purpose

This directory contains FastAPI endpoint definitions. Routers are responsible for:
- Defining API paths and HTTP methods.
- Validating request and response schemas (via Pydantic models).
- Enforcing authentication via dependencies (`get_verified_user`).
- Enforcing rate limits via Sentinel dependencies (`upload_guard`, `query_guard`, etc.).
- Delegating actual business logic to `app.services`.

**Crucial Invariant**: Route handlers must NOT contain raw database access or complex business logic. They must delegate to `app.services`.

## Key Files

- `auth.py`: Authentication endpoints (register, login, refresh, logout, verify-email, reset-password). Implements secure HttpOnly cookies for refresh tokens.
- `documents.py`: Document upload (presigned and multipart), deletion, and status checks. Enqueues ingestion jobs via RQ.
- `query.py`: `POST /query/ask` — RAG endpoint returning Server-Sent Events (SSE) using `gpt-4o-mini`. Validates chats, retrieves chunks, builds prompts, and handles OpenAI API streaming.
- `chats.py`: CRUD operations for chat threads.
- `health.py`: Liveness and readiness probes.
- `internal.py`: Internal webhook endpoints (e.g., Alertmanager).

## Error Handling

Routers rely on global exception handlers in `app.exceptions.py` to catch typed exceptions raised by the service layer. Do not raise `HTTPException` directly unless it's a structural API error (e.g., 404 in a router that catches a `DocumentNotFoundError`).

## Related Context

- Parent context: `../AGENTS.md`
- Business logic: `../services/AGENTS.md`
