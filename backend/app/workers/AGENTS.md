# Workers AGENTS.md

Context for the background task processing system (`backend/app/workers`).

## Purpose

Handles asynchronous background tasks using Redis Queue (RQ).

## Core Mechanisms

- **Queues**:
  - `ingest` queue: Heavy document ingestion tasks.
  - `default` queue: Light tasks like emails and cleanup jobs.
- **Entry Point**: `worker.py` (run via `Dockerfile.worker`).
- **Ingestion (`ingest.py`)**: The primary ingestion pipeline (Extract → Chunk → Embed → Store).
  - Uses an `_run_async` bridge via `asyncio.run()` to call the async service layer from the sync worker context.
  - Classifies errors as retryable vs. permanent. Retries occur at intervals `[60, 300, 900]`.
- **Failure Handling (`failure_handler.py`)**: When retries are exhausted, marks the document status as `FAILED` and writes a `JobLog` entry. Uses a lazily-created separate sync SQLAlchemy engine (`+psycopg`) since it runs in a sync context.
- **Tasks (`tasks.py`)**: Periodic cleanup tasks (e.g., removing stale `PENDING_UPLOAD` S3 orphans).

## Critical Invariants (DO NOT BREAK)

- **Worker Async Context**: Workers run sync code calling async services via `asyncio.run()`. **Each call creates a fresh event loop**. Do NOT share loop-bound pools (like async redis clients or aiosqlite connections) across loops.
- **OCR Parallelism**: Tesseract OCR is kept sequential (max workers = 1) in `docker-compose.yml` to prevent OOM kills on 2GB instances.

## Related Context

- Parent context: `../AGENTS.md`
- Ingestion services: `../services/AGENTS.md`
