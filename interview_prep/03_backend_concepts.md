# Phase 3 — Backend Concepts Sheet

This document contains deep-dive, interview-quality explanations for the core backend concepts used in the PDFTalk repository.

---

## 1. Authentication (JWT + HTTPOnly Cookies)

### 1. What is it?
Authentication is the process of verifying who a user is. In this project, it is implemented using JSON Web Tokens (JWT) for stateless access validation, paired with a stateful Refresh Token stored in a secure cookie.

### 2. Why is it needed?
HTTP is a stateless protocol. Without authentication, the server doesn't know who is making the request, meaning it can't protect private resources (like a user's uploaded PDFs or chat history).

### 3. Where is it used in THIS project?
*   **Files:** `app/auth/tokens.py`, `app/auth/dependencies.py`, `app/routers/auth.py`
*   **Functions:** `login_user()`, `validate_and_rotate_refresh_token()`, `get_verified_user()`

### 4. How does THIS implementation work?
1. User submits email/password. FastAPI hashes the password and compares it to the DB.
2. If valid, FastAPI generates two things:
    *   **Access Token (JWT):** A 15-minute token returned in the JSON response body.
    *   **Refresh Token:** A random secure string stored in the database and returned to the client as an `HttpOnly`, `Secure`, `SameSite=Lax` cookie.
3. The frontend stores the JWT in React Memory and attaches it as a `Bearer` token to API calls.
4. When the JWT expires, the frontend calls `/auth/refresh`. The browser automatically attaches the `HttpOnly` cookie.
5. FastAPI verifies the cookie against the database, deletes the old refresh token (Token Rotation), and issues a new pair.

### 5. Request Lifecycle (Refresh Flow)
`Next.js` -> `GET /api/documents (Bearer JWT)` -> `FastAPI validates JWT: Expired` -> `401 Unauthorized` -> `Next.js calls POST /auth/refresh (Sends Cookie)` -> `FastAPI DB Lookup` -> `FastAPI deletes old token, inserts new` -> `Next.js retries GET /api/documents`.

### 6. Interview Questions
*   **Easy:** What is a JWT and how does it differ from a session cookie?
*   **Medium:** Why do we return the Access Token in the JSON body but the Refresh Token in an HttpOnly cookie?
*   **Hard:** How does Token Rotation protect against session hijacking?
*   **Staff:** How would you design a system to immediately revoke a stateless JWT across a distributed microservice architecture?

### 7. Sample Answer (Staff Level)
*"Stateless JWTs cannot be revoked natively because the server doesn't track them. To achieve immediate revocation without losing the performance benefits of statelessness, I would introduce a short TTL (e.g., 5 minutes) combined with a Redis-backed 'Denylist'. When an admin bans a user, their `user_id` is published to the Redis denylist. The API gateway checks this denylist in memory (using a Bloom filter to keep latency sub-millisecond) before forwarding the request. The user is blocked instantly, and once the 5-minute TTL expires, the token is naturally dead and can be purged from the denylist."*

### 8. Follow-up Questions
*   *"What happens if Redis goes down during validation?"* -> "Fail open for the JWT validation to maintain availability, but fail closed on the Refresh endpoint."

### 9. Production Discussion
*   **100 users:** Token validation is instantaneous. Postgres easily handles the refresh token lookups.
*   **100,000 users:** The database might see heavy read/write contention on the `refresh_tokens` table during rotation. We would introduce connection pooling (`PgBouncer`) to manage the DB connections.
*   **Millions of users:** We would migrate the `refresh_tokens` table entirely into a distributed Redis cluster to prevent Postgres write-locking bottlenecks.

### 10. Alternatives
*   **Session-based Auth:** (Storing session IDs in Redis). Discarded because it requires a network hop to Redis for every single API request, increasing latency.

### 11. Trade-offs
*   **Advantage:** Immune to CSRF (no cookies used for data requests) and XSS (refresh token is HttpOnly).
*   **Disadvantage:** Token rotation logic is complex to implement correctly on the frontend without race conditions.

### 12. Improvements (Staff Engineer Perspective)
Currently, if a user opens two tabs simultaneously when their token expires, both tabs might hit `/auth/refresh`. The first request consumes the token. The second request hits the API a millisecond later, finds no token, and gets a 401, logging the user out abruptly. I would implement a "Refresh Token Grace Period" in the database, allowing a consumed token to be valid for an extra 5 seconds to gracefully handle frontend race conditions.

---

## 2. Background Workers (Queue Processing)

### 1. What is it?
A system where long-running, resource-intensive tasks are offloaded from the main web server to separate background worker processes via a message broker.

### 2. Why is it needed?
When a user uploads a PDF, extracting the text, chunking it, and calling the OpenAI embedding API can take 30+ seconds. If done synchronously, the HTTP request would block a server thread, potentially timing out, and causing a bottleneck (Head-of-Line blocking) for other users.

### 3. Where is it used in THIS project?
*   **Files:** `app/workers/ingest.py`, `app/workers/queue_poller.py`, `app/workers/tasks.py`
*   **Functions:** `process_document()`, `enqueue_job()`

### 4. How does THIS implementation work?
1. When `/documents/confirm-upload` is called, the router publishes a JSON payload to a Redis List.
2. The HTTP request immediately returns `202 Accepted`.
3. A separate Python process (`worker.py`) constantly polls Redis.
4. The worker pops the message, downloads the PDF from S3, parses it, chunks it, and calls OpenAI.
5. It updates the Postgres document status to `READY`.

### 5. Request Lifecycle
`Client POST /confirm-upload` -> `FastAPI saves to DB` -> `FastAPI pushes to Redis` -> `FastAPI returns 202`. (Asynchronously): `Worker pops Redis` -> `Worker pulls S3` -> `Worker queries OpenAI` -> `Worker writes to DB`.

### 6. Interview Questions
*   **Easy:** Why not process the PDF in the API endpoint?
*   **Medium:** How do you handle a scenario where the worker crashes halfway through processing a document?
*   **Hard:** How do you ensure idempotency in your queue workers?
*   **Staff:** If OpenAI starts rate-limiting your workers, how do you prevent the queue from backing up and starving other resources?

### 7. Sample Answer (Hard Level)
*"Idempotency means a task can safely be executed multiple times without side effects. In this system, if a worker crashes after generating embeddings but before marking the document `READY`, a retry would duplicate the chunks. To fix this, the worker initiates a database transaction that first runs a `DELETE FROM chunks WHERE document_id = X`. Then it inserts the new chunks. Because this is wrapped in a single transaction, it guarantees that no matter how many times the job is retried, the database state remains consistent."*

### 8. Follow-up Questions
*   *"What if the Redis broker runs out of memory?"* -> Implement `maxmemory-policy` and monitor queue depth.

### 9. Production Discussion
*   **10,000 users:** A single worker will fall behind. We scale horizontally by deploying more worker containers. Because they compete for the Redis list via atomic `BLPOP`, they naturally load-balance.

### 11. Trade-offs
*   **Advantage:** API remains highly responsive and available regardless of backend processing latency.
*   **Disadvantage:** Eventual consistency. The frontend must poll or use WebSockets to know when the document is `READY`.

### 12. Improvements (Staff Engineer Perspective)
I would implement a Dead Letter Queue (DLQ). If a document fails processing 3 times (e.g., it's a corrupted PDF), the worker currently might just drop it or leave it in a `FAILED` state. A DLQ would capture the exact payload and traceback, allowing engineers to replay the exact message locally for debugging without asking the user to re-upload.

---

## 3. Retrieval-Augmented Generation (RAG) & Vector Databases

### 1. What is it?
RAG is an architecture that provides Large Language Models (LLMs) with custom, external data. A Vector Database is specialized storage designed to quickly find mathematical representations (vectors) of text that are semantically similar.

### 2. Why is it needed?
LLMs like GPT-4 are trained on public data and do not know the contents of a user's private PDFs. Furthermore, LLMs have strict context window limits. You cannot pass a 1,000-page PDF directly into the prompt.

### 3. Where is it used in THIS project?
*   **Files:** `app/services/embedding.py`, `app/services/retrieval.py`, `app/services/chunking.py`, `app/models/chunk.py`

### 4. How does THIS implementation work?
1. **Ingestion:** The PDF is split into overlapping 1,000-character chunks. Each chunk is sent to OpenAI's `text-embedding-3-small` API, returning a 1536-dimensional array of floats.
2. **Storage:** The array is stored in Postgres using the `pgvector` extension.
3. **Retrieval:** When a user asks a question, the question is embedded. Postgres uses the `<=>` (cosine distance) operator combined with an HNSW index to rapidly find the 5 most semantically similar chunks.
4. **Generation:** These 5 chunks are injected into the system prompt, and the LLM answers the user's question.

### 5. Request Lifecycle
`User Query` -> `OpenAI API (Embed Query)` -> `Postgres pgvector (Similarity Search)` -> `Build Prompt with chunks` -> `OpenAI API (Chat Completion)` -> `Stream response to user`.

### 6. Interview Questions
*   **Medium:** Why do we overlap chunks during the text extraction phase?
*   **Hard:** How does an HNSW (Hierarchical Navigable Small World) index work in pgvector?
*   **Staff:** Your semantic search is returning poor results because it's matching on common keywords rather than the actual meaning. How do you improve the retrieval pipeline?

### 7. Sample Answer (Staff Level)
*"Standard vector embeddings often struggle with precise keyword matching (e.g., finding a specific serial number) and can suffer from 'lost in the middle' syndrome. To improve retrieval, I would implement a Hybrid Search architecture. I would query both the vector index (Dense search for semantics) and a standard text index using Postgres `tsvector` / BM25 (Sparse search for exact keywords). Then, I would use a Cross-Encoder model or Reciprocal Rank Fusion (RRF) to re-rank the combined results before feeding them to the LLM."*

### 11. Trade-offs
*   **Advantage:** `pgvector` allows us to keep relational data (Users, Chats) and Vector data in the same ACID-compliant database, eliminating network hops to external systems like Pinecone.
*   **Disadvantage:** Vector indexes (HNSW) consume massive amounts of RAM.

### 12. Improvements (Staff Engineer Perspective)
I would implement "Contextual Compression". Even if we retrieve the top 5 chunks, they contain a lot of irrelevant noise. By passing the chunks through a smaller, faster local LLM to extract *only* the sentences relevant to the user's query before sending the final prompt to GPT-4, we save tokens, reduce latency, and improve the final answer quality.
