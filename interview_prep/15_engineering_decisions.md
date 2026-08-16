# Phase 15 — Engineering Decisions

This document explores the critical architecture and engineering decisions made in the PDFTalk repository. It is designed to prepare you for senior and staff-level system design interviews.

---

## 1. Presigned URLs for S3 Uploads (Instead of passing via FastAPI)

**The Decision:**
Instead of allowing users to upload a PDF directly to the FastAPI backend (using `UploadFile` / `multipart/form-data`) and then having FastAPI push it to S3, the system uses **Presigned URLs**.

**Why this decision?**
*   **Memory / CPU Exhaustion:** FastAPI is a single-threaded async framework. If 1,000 users upload 50MB PDFs simultaneously, the backend would need to stream 50GB of data, consuming immense RAM and I/O bandwidth.
*   **Cost:** Bandwidth into the application server costs money. Bandwidth directly to S3 is often cheaper and scales infinitely without increasing application server load.

**Alternatives Considered:**
*   **Direct Upload to FastAPI:** Easy to implement, but scales poorly.
*   **TUS Resumable Upload Protocol:** Great for gigabyte-scale files, but overkill for 50MB PDFs.

**Trade-offs:**
*   *Advantage:* Offloads 100% of the upload bandwidth and disk I/O from the application servers.
*   *Disadvantage:* Complexity. Requires a two-step flow (`initiate-upload` -> S3 -> `confirm-upload`) and state management (e.g., `PENDING_UPLOAD` status).
*   *Disadvantage:* Orphaned files. If a user uploads to S3 but closes the tab before hitting `confirm-upload`, S3 holds an orphaned file. (Solved via `s3_lifecycle.json` which deletes unconfirmed files).

**Interview Explanation:**
*"To handle large PDF uploads concurrently, I decoupled the upload path from the compute path. By issuing an S3 Presigned URL, the client's browser negotiates the TLS session and byte transfer directly with AWS. The application server only handles lightweight metadata requests (Init and Confirm), which are O(1) in memory regardless of file size. This prevents our API from becoming a bottleneck during traffic spikes."*

---

## 2. JWT Access Tokens + HTTPOnly Refresh Tokens

**The Decision:**
Authentication uses a stateless 15-minute JWT Access Token passed in the JSON body, and a stateful, long-lived Refresh Token stored in a `Secure, HttpOnly` cookie.

**Why this decision?**
*   **XSS Mitigation:** By placing the refresh token in an `HttpOnly` cookie, JavaScript cannot access it. Even if an attacker executes a Cross-Site Scripting (XSS) payload, they cannot steal the refresh token.
*   **CSRF Mitigation:** The Access Token is stored in memory and sent via the `Authorization: Bearer` header. This completely neutralizes Cross-Site Request Forgery (CSRF) because standard browser requests don't automatically attach the header.
*   **Stateless Scalability:** FastAPI validates the Access Token purely via cryptography. No database lookup is required for the 99% of requests (API calls). DB lookups only happen on the 1% (Refresh/Login).

**Alternatives Considered:**
*   **Session Cookies (Redis):** Simpler to revoke, but requires a Redis lookup on every single API request.
*   **Local Storage JWT:** Vulnerable to XSS. If XSS occurs, the attacker steals the permanent token.

**Trade-offs:**
*   *Advantage:* Optimal blend of security (XSS/CSRF protection) and performance (stateless validation).
*   *Limitation:* You cannot instantly revoke an Access Token. If an admin bans a user, the user can still use the API for up to 15 minutes until the token expires.

---

## 3. pgvector over Pinecone/Milvus

**The Decision:**
The embeddings are stored in PostgreSQL using the `pgvector` extension with an HNSW index, rather than using a dedicated Vector Database like Pinecone, Weaviate, or Qdrant.

**Why this decision?**
*   **Operational Simplicity:** PDFTalk already uses Postgres for relational data (Users, Chats, Documents). Adding `pgvector` means one less infrastructure component to monitor, back up, and secure.
*   **Relational Filtering:** We need to perform similarity searches *restricted to a specific user or document*. In `pgvector`, this is a simple SQL `WHERE user_id = X ORDER BY embedding <=> Y`. In Pinecone, this requires complex metadata filtering that can slow down retrieval.
*   **ACID Guarantees:** When a document is deleted, Postgres `CASCADE` automatically deletes its chunks and embeddings. With Pinecone, you risk split-brain scenarios where the DB deletes the document but the API call to Pinecone fails, leaving orphaned vectors.

**Alternatives Considered:**
*   **Pinecone:** Managed, infinite scale, but expensive and adds network latency/split-brain risk.

**Trade-offs:**
*   *Advantage:* ACID compliance, zero extra infrastructure, seamless relational joins.
*   *Limitation:* Postgres scales vertically well, but sharding vector data horizontally is notoriously difficult compared to purpose-built distributed vector databases.

---

## 4. Server-Sent Events (SSE) for LLM Responses

**The Decision:**
The chatbot uses Server-Sent Events (`StreamingResponse` in FastAPI) to stream tokens from the OpenAI API to the frontend in real-time.

**Why this decision?**
*   **Time To First Byte (TTFB):** RAG queries take 5-10 seconds to generate a full response. Without streaming, the user stares at a spinner for 10 seconds. With SSE, the user sees the first word in ~800ms, vastly improving perceived performance.

**Alternatives Considered:**
*   **WebSockets:** Allows bidirectional streaming. However, LLM text generation is inherently unidirectional (Server -> Client). WebSockets introduce heavy state-management overhead, load balancer complexities (sticky sessions), and connection dropping issues.
*   **Polling:** Extremely inefficient.

**Trade-offs:**
*   *Advantage:* Simple HTTP protocol, supported natively by standard load balancers, fast TTFB.
*   *Limitation:* Unidirectional.

**Interview Explanation:**
*"For the LLM chat interface, Time-to-First-Byte is the most critical UX metric. I chose Server-Sent Events over WebSockets because the data flow is strictly unidirectional. SSE operates over standard HTTP/1.1 or HTTP/2, meaning it passes seamlessly through our Nginx reverse proxy without requiring protocol upgrades or sticky sessions, while still delivering tokens to the UI instantly."*

---

## 5. Background Workers (Queue) for Document Ingestion

**The Decision:**
When a document is uploaded, text extraction and embedding generation run in a background queue worker, completely detached from the FastAPI request cycle.

**Why this decision?**
*   **Latency & Timeouts:** Processing a 50-page PDF can take minutes. HTTP connections would time out.
*   **Resilience:** If the OpenAI API rate limits the server during embedding generation, the background job can safely catch the exception, apply exponential backoff, and retry.
*   **Resource Isolation:** Chunking and embedding generation are CPU/Network intensive. Isolating them prevents the API web server from starving for CPU cycles.

**Interview Explanation:**
*"To guarantee high availability for the API, I implemented a Producer-Consumer pattern using Redis as a message broker. This isolates the computationally heavy PDF parsing from the synchronous web threads. If an external dependency like OpenAI goes down, the worker simply moves the task to a retry queue, ensuring zero data loss without impacting the user's ability to navigate the app."*
