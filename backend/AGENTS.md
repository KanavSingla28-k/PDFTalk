# Backend AGENTS.md

Context for the FastAPI backend application.

## Purpose

This directory contains the Python backend, providing the API for PDFTalk, handling authentication, document ingestion (via RQ workers), vector storage (pgvector), and RAG queries (OpenAI).

## Backend Architecture

The backend follows a service-oriented structure:
- **API Layer**: `routers/` handles HTTP requests, dependency injection, and schema validation.
- **Service Layer**: `services/` contains business logic, orchestrating database calls, validation, and external APIs. Route handlers MUST delegate complex logic to services.
- **Data Access Layer**: `db/` handles database connections. `models/` defines SQLAlchemy ORM models.
- **Worker Layer**: `workers/` consumes tasks from Redis Queue (RQ) for heavy jobs like extraction, chunking, and embedding.

### External Dependencies
- **PostgreSQL (pgvector)**: Relational and vector database.
- **Redis**: Used for RQ, rate limiting (Sentinel), and caching.
- **OpenAI**: Used for embeddings (`text-embedding-3-small`) and LLM chat (`gpt-4o-mini`).
- **AWS S3**: Storage for uploaded documents.
- **Resend**: Transactional emails for verification.
- **PyMuPDF / pytesseract**: Used for PDF text extraction and OCR fallback.

## Conventions

- **Exceptions**: Never raise `HTTPException` directly from services. Use typed exceptions from `app/exceptions.py`. These are centrally mapped to HTTP responses.
- **Async vs Sync**: The API is async (`asyncpg`, `aiosqlite` for tests). The RQ workers are sync and use `psycopg[binary]`. Workers use an `_run_async` bridge via `asyncio.run()` to call async services. Each call creates a fresh event loop.
- **Database Sessions**: `get_db` commits on success and rolls back on error automatically.
- **Dependencies**: Managed via **uv** (`pyproject.toml`).
- **Formatting & Linting**: `ruff` with line-length 100, `mypy --strict`.

## Testing

- Located in `tests/`.
- Uses `pytest` with `asyncio_mode="auto"`.
- Uses an in-memory SQLite database (`aiosqlite`), `fakeredis`, and `moto` for S3.
- `conftest.py` sets environment variables *before* any application imports to prevent `pydantic-settings` from failing. Do not change this order.

## Directory Structure & Child Contexts

- `app/`: The main application package. See `app/AGENTS.md`.
- `alembic/`: Database migrations.
- `tests/`: Test suite.
- `scripts/`: Operational scripts (e.g., benchmarking).
- `Dockerfile` & `Dockerfile.worker`: Container definitions for API and Worker.

## Related Context
- Root Architecture: `../AGENTS.md`
