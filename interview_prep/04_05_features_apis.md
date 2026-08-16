# Phase 4 — Feature Walkthrough & Phase 5 — API Documentation

This document covers the end-to-end walkthrough of the core features and exhaustive API documentation for the PDFTalk system.

---

## 1. Feature: Registration & Verification

### Files Involved
*   `backend/app/routers/auth.py`
*   `backend/app/services/user_service.py`
*   `backend/app/services/email_verification.py`
*   `frontend/src/app/auth/register/page.tsx`

### Execution Order & Sequence
1.  Frontend submits email/password to `POST /api/auth/register`.
2.  Backend `auth.py` invokes `user_service.register`.
3.  Password is hashed (bcrypt). User row is created (`is_verified=False`).
4.  `email_verification.py` generates a cryptographically secure token, hashes it, stores the hash in `email_verifications`, and sends the raw token via Resend.
5.  User clicks the email link -> `GET /api/auth/verify-email?token=...`
6.  Token is verified; user row is updated to `is_verified=True`.

### Security & Failure Cases
*   **Security:** Registration is rate-limited (5/hour/IP) to prevent spam. Generic `202 Accepted` is always returned to prevent email enumeration. Passwords require strict complexity (8+ chars, upper, lower, symbol, number).
*   **Failure:** If Resend fails, the user is still created. They can click "Resend Verification Email" in the UI.

---

## 2. Feature: Document Processing Pipeline

### Files Involved
*   `backend/app/routers/documents.py`
*   `backend/app/workers/worker.py`
*   `backend/app/services/chunking.py`
*   `backend/app/services/embedding.py`

### Data Transformations
`Binary PDF -> String Text -> List[String] (Chunks) -> List[Vector[1536]]`

### Execution Order
1.  Client gets S3 presigned URL and uploads the file directly to S3.
2.  Client calls `POST /api/documents/confirm-upload`.
3.  Document status becomes `PENDING`. Job is pushed to Redis Queue.
4.  Celery/RQ Worker pops job -> fetches PDF from S3.
5.  Text is extracted via `PyMuPDF` / `pdfplumber`.
6.  Text is split into 1,000-character chunks with 200-character overlaps using `RecursiveCharacterTextSplitter`.
7.  Chunks are batched (e.g., 100 at a time) and sent to OpenAI `text-embedding-3-small`.
8.  Embeddings + Text are saved to Postgres `chunks` table. Document status becomes `READY`.

### Production Concerns
*   **Scalability:** Processing is completely decoupled from the web server. Adding more worker containers linearly scales processing throughput.
*   **Failure Recovery:** If OpenAI rate-limits, the worker job fails and is automatically retried by the queue manager with exponential backoff.

---

## 3. API Documentation

### `POST /auth/login`
**Service:** `user_service.py` | **DB Tables:** `users`, `refresh_tokens`
*   **Request:** `{"email": "user@example.com", "password": "..."}`
*   **Response (200 OK):** `{"access_token": "ey...", "token_type": "bearer", "expires_in": 900, "user": {...}}`
*   **Headers Set:** `Set-Cookie: refresh_token=...; HttpOnly; Secure; SameSite=Lax`
*   **Failure Cases:** 
    *   `401 Unauthorized` (Wrong credentials - generic error)
    *   `403 Forbidden` (Email not verified)
    *   `429 Too Many Requests` (Rate limit exceeded)

### `POST /auth/refresh`
**Service:** `tokens.py` | **DB Tables:** `refresh_tokens`
*   **Request:** Sends the `refresh_token` HttpOnly cookie.
*   **Response (200 OK):** `{"access_token": "ey...", ...}` + New `Set-Cookie` header.
*   **Failure Cases:** `401 Unauthorized` if cookie is missing or invalid.

### `POST /documents/initiate-upload`
**Service:** `document_service.py` | **DB Tables:** `documents`
*   **Request:** `{"filename": "test.pdf", "file_size_bytes": 1024000, "mime_type": "application/pdf"}`
*   **Authentication:** Requires valid Bearer JWT.
*   **Response (201 Created):** `{"document_id": "uuid", "upload_url": "https://s3.aws.com/..."}`
*   **Security:** Checks `file_size_bytes` against `_MAX_UPLOAD_BYTES` (50MB) and validates MIME type to prevent malicious uploads. Checks if user hit `MAX_DOCS_PER_USER`.

### `POST /documents/confirm-upload`
**Service:** `document_service.py` | **DB Tables:** `documents` | **Redis:** Enqueues job
*   **Request:** `{"document_id": "uuid"}`
*   **Response (202 Accepted):** `{"document_id": "uuid", "status": "PENDING"}`
*   **Flow:** Verifies S3 `HeadObject`, transitions status, pushes to RQ/Redis.

### `GET /chats/{chat_id}`
**Service:** `chats.py` | **DB Tables:** `chats`, `messages`
*   **Request:** Path param `chat_id`.
*   **Response (200 OK):** `{"id": "uuid", "title": "...", "messages": [{"role": "user", "content": "..."}]}`

### `POST /query`
**Service:** `llm.py`, `retrieval.py` | **External APIs:** OpenAI
*   **Request:** `{"chat_id": "uuid", "question": "What is the summary?"}`
*   **Response (200 OK):** `text/event-stream` (Server-Sent Events)
*   **Flow:** 
    1. Embed question. 
    2. pgvector similarity search against `chunks`.
    3. Stream OpenAI ChatCompletion chunks.
    4. Async DB save of the final generated message.
*   **Failure Cases:** `400 Bad Request` if chat doesn't exist. `502 Bad Gateway` if OpenAI is down.
