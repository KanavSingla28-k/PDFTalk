# Phase 6 to 9 — Data, Redis, Queue, and Storage Infrastructure

This document combines the documentation for the persistent data stores, caching layers, asynchronous queues, and object storage mechanisms used in PDFTalk.

---

## Phase 6: Database Documentation

The system uses PostgreSQL configured with the `pgvector` extension, managed via SQLAlchemy ORM and Alembic migrations.

### Models & Relationships

#### 1. `User` (`users`)
*   **Purpose:** Core identity.
*   **Fields:** `email`, `email_lower` (normalized for unique constraint), `password_hash`.
*   **Relationships:** 1:N with `Document`, `Chat`, `RefreshToken`.
*   **Security:** Passwords hashed with bcrypt.

#### 2. `Document` (`documents`)
*   **Purpose:** Tracks uploaded files and their ingestion state.
*   **Fields:** `s3_key`, `file_size_bytes`, `mime_type`, `status`.
*   **Status Enum:** `PENDING_UPLOAD`, `PENDING`, `PROCESSING`, `READY`, `FAILED`.
*   **Constraint:** Enforced via a SQL `CheckConstraint` on the `status` column to guarantee valid state transitions.
*   **Indexes:** `idx_documents_user_id` (used extensively when listing user dashboard files).

#### 3. `Chunk` (`chunks`)
*   **Purpose:** Stores the actual PDF text slices and their high-dimensional vector representations.
*   **Fields:** `text`, `token_count`, `embedding` (`Vector(1536)`).
*   **Critical Index:** `idx_chunks_embedding_hnsw` (Hierarchical Navigable Small World). This index allows `O(log N)` cosine distance similarity search instead of `O(N)` exact KNN.
*   **Optimization:** `user_id` is denormalized onto this table so vector queries can `WHERE user_id = X` without joining the `documents` table, vastly speeding up RAG queries.

#### 4. `Chat` (`chats`) & `Message` (`messages`)
*   **Purpose:** Stores LLM conversation history.
*   **Fields:** `document_ids` (JSONB) in Chat to link which PDFs this chat is querying. `role` (user/assistant) and `token_count` in Message.

### Connection Lifecycle
*   FastAPI uses `AsyncSession` with `asyncpg`.
*   Connection pooling is configured in `alembic.ini` and `app/db/session.py`.
*   All routes use FastAPI `Depends(get_db)` to acquire a session, ensuring it is automatically rolled back on exception and closed after the request completes.

---

## Phase 7: Redis Documentation

Redis is used for caching, rate limiting, and queue brokering.

### Redis Key Structures

1.  **Rate Limiting**
    *   **Key:** `rate_limit:{prefix}:{identifier}` (e.g., `rate_limit:login:192.168.1.1`).
    *   **Value:** Integer count.
    *   **Expiration:** Set to the window size (e.g., 60 seconds).
    *   **Implementation:** Handled via Lua script inside `RateLimiter` to guarantee atomicity and prevent race conditions.

2.  **Queue Backend**
    *   **Key:** `rq:queue:ingest` (Managed by RQ).
    *   **Lifecycle:** Pushed via `app/workers/queues.py`, popped by the worker.

### Production Scaling Considerations
*   Since Redis stores transient data (rate limits, queue items), losing Redis is not catastrophic for data integrity, but it will halt document ingestion and fail-open rate limiters.
*   For millions of users, Redis must be clustered (e.g., ElastiCache) to handle connection overhead and memory limits.

---

## Phase 8: Queue Documentation

PDFTalk uses Python RQ (Redis Queue) or Celery (depending on exact module config in `workers/queues.py`) for background task processing.

### Architecture
*   **Producer:** `document_service.confirm_upload()` pushes the `document_id` to the queue.
*   **Broker:** Redis list.
*   **Consumer:** A Docker container running `worker.py` (scaled via `docker-compose.yml`).

### Failure Recovery & Retries
*   **Retries:** If the worker crashes (e.g., OpenAI API 502), the job is caught by `failure_handler.py`.
*   **Job Log:** A row is written to the `job_logs` Postgres table with the full traceback.
*   **Idempotency:** The worker `process_document()` function is completely idempotent. If it fails midway, retrying it will start over cleanly, dropping partial chunks.

---

## Phase 9: Storage Documentation

All actual PDF bytes live in AWS S3.

### Presigned URL Architecture
1.  **Uploads:** The backend does *not* receive file bytes. It calls `boto3.client('s3').generate_presigned_url('put_object')`. The browser uploads directly to S3.
2.  **Downloads:** To read a file, the API generates a presigned GET URL valid for 15 minutes.
3.  **Security:** The S3 bucket is completely private. `PublicAccessBlock` is enabled. No objects can be read without a cryptographically signed URL from the FastAPI backend.

### S3 Lifecycle Policies
*   **File:** `infra/s3_lifecycle.json`
*   **Action:** Deletes objects older than 1 day if they have a specific tag (or if they are orphaned). If a user initiates an upload but closes the tab before hitting confirm, S3 automatically deletes the junk bytes to save money.
