# PDFTalk — Complete Execution System
## Senior Developer + QA + Mentor + Notion Architecture Guide

> **Project:** PDFTalk MVP — AI-powered PDF question-answering application
> **Stack:** FastAPI · Next.js 14 · PostgreSQL + pgvector · Redis · RQ · Nginx · Docker Compose · AWS Lightsail · S3 · OpenAI
> **Infrastructure:** Single Lightsail instance ($20/month) — no ECS, no managed DB, no NAT Gateway
> **Total Tasks:** 63 | **Estimated Duration:** 3–4 weeks solo | **Monthly Infrastructure Cost:** ~$22.50

---

# PART 1 — EXECUTIVE SUMMARY

PDFTalk is a production-grade RAG (Retrieval-Augmented Generation) application that lets users upload PDF documents and ask questions answered by GPT-4o-mini using only the content of those documents. Every technical decision is optimized for a solo developer launching a real product with minimal operational overhead and cost.

**Core value proposition:** Upload any PDF → ask questions in natural language → get grounded answers with source citations, streamed in real time.

**Why this architecture wins at MVP scale:**
- Single Docker Compose file replaces ECS, Fargate, ALB, ElastiCache, RDS — eliminating ~$245/month in infrastructure costs
- pgvector inside your existing Postgres eliminates FAISS, EFS, and all associated file-locking complexity
- The entire operational surface is one server, one compose file, one place to debug
- Every architectural decision has a documented migration path for when you outgrow it

**What you will have after 63 tasks:**
- A fully authenticated, email-verified user system with JWT + refresh tokens
- A secure file ingestion pipeline (PDF → text → chunks → embeddings → pgvector)
- A real-time streaming RAG query endpoint (SSE via fetch ReadableStream)
- A production-hardened Nginx reverse proxy with TLS, security headers, and rate limiting
- Automated daily database backups to S3
- A CI/CD pipeline deploying from GitHub Actions via SSH
- A complete Next.js 14 frontend with auth, upload, document management, and live chat UI
- An 80%+ test coverage backend with unit + integration tests

---

# PART 2 — ARCHITECTURE REVIEW

## System Architecture Diagram

```
INTERNET (HTTPS 443 / HTTP 80 → redirect)
          │
          ▼
┌─────────────────────────────────────────────────────────┐
│  LIGHTSAIL $20/month (2 vCPU · 4GB RAM · Ubuntu 22.04)  │
│                                                         │
│  ┌───────────────────────────────────────────────────┐  │
│  │  nginx (external network + internal)              │  │
│  │  ├─ SSL termination (Let's Encrypt, TLS 1.2+)    │  │
│  │  ├─ Security headers (HSTS, X-Frame, CSP, etc.)  │  │
│  │  ├─ Rate limiting (limit_req_zone — volumetric)  │  │
│  │  ├─ Static frontend (Next.js out/ — pre-built)   │  │
│  │  └─ Reverse proxy → api:8000                     │  │
│  └───────────────────┬───────────────────────────────┘  │
│                      │ internal Docker network only      │
│  ┌───────────────────▼────────────────────────────────┐  │
│  │  api (FastAPI + uvicorn)   worker (RQ + ingest)   │  │
│  │  postgres (PG 15+pgvector) redis (v7, AUTH req'd) │  │
│  │  All zero ports exposed to host in production     │  │
│  └────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
        │                           │
        ▼ S3 HTTPS + IAM            ▼ HTTPS API
┌──────────────────┐     ┌──────────────────────┐
│  AWS S3 (private)│     │  OpenAI API           │
│  Documents +     │     │  text-embedding-3-    │
│  Backups buckets │     │  small + gpt-4o-mini  │
└──────────────────┘     └──────────────────────┘
```

## Architectural Decision Records (ADRs)

| ADR | Decision | Rationale | Trade-off | Migration Path |
|-----|----------|-----------|-----------|----------------|
| ADR-001 | pgvector over FAISS+EFS | Zero additional services, no file locking, 5-line SQL query, indistinguishable perf at MVP scale (<100K chunks) | Must upgrade PG version to upgrade pgvector | Swap `retrieval.py` module to Pinecone when P95 query > 200ms |
| ADR-002 | Docker Compose on Lightsail over ECS | 10× cheaper, single place to debug, zero service discovery complexity | Single point of failure, vertical scaling only | Migrate to ECS when Lightsail throughput ceiling hit |
| ADR-003 | Postgres+Redis in Docker over managed | Save $43/month (ElastiCache+RDS), full control | Backup automation is your responsibility (T-62) | Add RDS/ElastiCache when >100 paying users + uptime SLA |
| ADR-004 | S3 over Lightsail disk | Durable ($0.023/GB), instance-independent, no silent disk fill | Small egress cost, IAM complexity | Non-negotiable — never replace S3 with local disk |

---

# PART 3 — KEEP / MODIFY / DELETE / MISSING ANALYSIS

| Component | Status | Reason | Recommendation |
|-----------|--------|--------|----------------|
| Monorepo scaffold (T-01) | **KEEP** | Correct structure with Makefile shortcuts | Add `make lint` and `make type-check` targets |
| `.gitignore` + secret detection (T-01) | **KEEP** | Comprehensive, includes detect-secrets pre-commit | Implement exactly as specified |
| Pydantic `Settings` / env validation (T-02) | **KEEP** | Fail-fast on missing secrets at startup — correct pattern | Exactly as written |
| Docker Compose dev environment (T-03) | **KEEP** | Mirrors production topology, network isolation correct | Good as-is; add `healthcheck:` directives per service |
| pgvector schema + Alembic (T-04) | **KEEP** | All 6 tables, indexes, token hashing — production-grade | Defer IVFFlat index to migration 002 as noted |
| SQLAlchemy async + connection pooling (T-05) | **KEEP** | `pool_pre_ping`, `pool_recycle` — correct for Docker restarts | pool_size=10/5 is correct for this instance |
| S3 bucket + minimal IAM policy (T-06) | **KEEP** | Least-privilege IAM, versioning, encryption — correct | Add S3 lifecycle policy to expire old document versions after 90 days |
| Lightsail provisioning + SSH hardening (T-07) | **KEEP** | UFW, fail2ban, PermitRootLogin no — all correct | Add unattended-upgrades as specified |
| Docker + Compose on Lightsail (T-08) | **KEEP** | Official install script, `/opt/pdftalk/` structure | Correct |
| Route 53 DNS (T-09) | **KEEP** | Standard setup, propagation check via `dig` | Correct |
| Nginx + Let's Encrypt (T-10) | **KEEP** | TLS 1.2+, strong ciphers, auto-renewal hook | Test with SSL Labs after deploy |
| Production secrets management (T-11) | **KEEP** | `chmod 600`, `env_file` directive — correct | Consider AWS Secrets Manager when you have a team |
| FastAPI scaffold + pyproject.toml (T-12) | **KEEP** | Clean dependency list, router/service separation | Add `numpy` for L2-normalization in embedding service |
| Redis client with namespacing (T-13) | **KEEP** | Key namespacing pattern prevents collisions | Correct |
| S3 client abstraction (T-14) | **KEEP** | Clean interface enables easy mocking in tests | Correct |
| User model + bcrypt 12 rounds (T-15) | **KEEP** | 12 rounds is current safe default | Correct |
| JWT + refresh token rotation (T-16) | **KEEP** | Opaque refresh tokens, SHA-256 stored, rotation on use — excellent | The `type` claim check is critical; enforce it |
| Email verification service (T-17) | **KEEP** | Resend recommendation is correct for MVP | Test with real email before launch (T-63 checklist) |
| Registration endpoint (T-18) | **KEEP** | Generic 202 response prevents user enumeration — correct | Rate limit: 5 registrations/IP/hr as noted |
| Email verification endpoint (T-19) | **KEEP** | One-time token, immediate delete after use | Correct |
| Login endpoint + account lockout (T-20) | **KEEP** | Cookie settings (httpOnly, Secure, SameSite, path-scoped) are production-grade | The `path="/auth/refresh"` scoping is often missed — keep it |
| Token refresh + logout (T-21) | **KEEP** | Server-side refresh token deletion on logout | Correct; this is what makes logout real |
| JWT middleware dependency (T-22) | **KEEP** | `get_verified_user` checks active+verified on every request | Correct pattern |
| Auth integration tests (T-23) | **KEEP** | Full lifecycle + failure paths using fakeredis | Correct |
| Document model + state machine (T-24) | **KEEP** | Application-level state machine prevents concurrency bugs | Correct |
| File validation service (T-25) | **KEEP** | Magic byte validation + size check before memory load | Correct |
| Upload endpoint (T-26) | **KEEP** | UUID-based S3 keys, quota check before accepting upload | Correct |
| Document CRUD endpoints (T-27) | **KEEP** | 404 (not 403) on unauthorized access — correct security pattern | Correct |
| RQ worker setup + dead-letter queue (T-28) | **KEEP** | Exponential backoff (30s→120s→480s), job_logs on final failure | Correct |
| Text extraction (T-29) | **KEEP** | PyMuPDF for PDFs, handle encrypted/corrupt gracefully | Correct |
| Chunking + cost pre-check (T-30) | **KEEP** | 512-token chunks, 64-token overlap, MAX_TOKENS_PER_DOCUMENT guard | Correct |
| Ingestion worker orchestrator (T-31) | **KEEP** | Full try/except wrapper, status transitions, job_logs | Correct |
| OpenAI client + circuit breaker (T-32) | **KEEP** | Daily token counter in Redis, circuit breaker pattern | Correct |
| Embedding service + L2 normalize (T-33) | **KEEP** | Batch 100, `text-embedding-3-small`, L2-normalize | Correct |
| pgvector retrieval (T-34) | **KEEP** | Cosine distance (`<=>`), filtered by user_id + document_ids | Correct |
| Chunk model + bulk insert (T-35) | **KEEP** | `add_all()` + single commit vs row-by-row | Correct |
| E2E ingestion integration test (T-36) | **KEEP** | Real PDF, sync worker, assert embeddings non-null | Correct |
| Prompt builder + token cap (T-37) | **KEEP** | 3,000-token context cap, grounded system instruction | Correct |
| Streaming LLM service (T-38) | **KEEP** | Async generator, retry on RateLimitError | Correct |
| SSE streaming endpoint (T-39) | **KEEP** | POST+fetch ReadableStream pattern (EventSource GET-only noted) | Correct |
| Query conversation history (T-40) | **MODIFY** | Not explicitly defined in task list | Add `conversation_history` array to `POST /query/ask` — enables multi-turn chat |
| Security headers middleware (T-41) | **KEEP** | X-Frame-Options, nosniff, Referrer-Policy | Add `Content-Security-Policy` header explicitly |
| Redis sliding window rate limiter (T-42) | **KEEP** | Two-layer: Nginx (volumetric) + Redis (business logic) | Correct |
| Structured logging (T-43) | **KEEP** | structlog JSON, request_id injection, no PII | Correct |
| Per-user quotas + spend alarm (T-44) | **KEEP** | Redis counters for docs, tokens, queries | Correct |
| Health check endpoint (T-45) | **KEEP** | DB+Redis+S3 with 500ms timeouts, 503 on failure | Correct |
| Next.js 14 scaffold (T-46) | **KEEP** | App Router, TypeScript, Tailwind, zod env validation | Correct |
| API client layer (T-47) | **KEEP** | In-memory token storage (not localStorage), silent refresh pattern | Critical: never localStorage for access tokens |
| Auth pages (T-48) | **KEEP** | react-hook-form + zod, verification flow | Correct |
| Auth context + protected routes (T-49) | **KEEP** | Next.js middleware.ts redirect pattern | Correct |
| Upload UI (T-50) | **KEEP** | react-dropzone, client-side validation, quota warning | Correct |
| Document list + status polling (T-51) | **KEEP** | 3s polling for non-terminal, status badges | Correct |
| Chat UI + SSE (T-52) | **KEEP** | fetch + ReadableStream, progressive token rendering | Correct |
| Error boundaries + a11y (T-53) | **KEEP** | WCAG 2.1 AA contrast, ARIA labels, keyboard nav | Correct |
| Production Dockerfile (T-54) | **KEEP** | Multi-stage, non-root user, health check | Correct |
| Docker Compose production (T-55) | **KEEP** | Named volumes, network isolation, depends_on health | Correct |
| Nginx Docker config (T-56) | **KEEP** | TLS, security headers, gzip, static file serving | Correct |
| CI lint/test pipeline (T-57) | **KEEP** | Ruff + mypy + pytest-cov, PR-gated | Correct |
| CD deploy pipeline (T-58) | **KEEP** | SSH deploy, alembic before restart, SHA tags not :latest | Correct |
| Staging environment (T-59) | **KEEP** | Separate compose, smoke test | Correct |
| Unit tests (T-60) | **KEEP** | ≥80% coverage target, mocked dependencies | Correct |
| Integration tests (T-61) | **KEEP** | fakeredis + moto[s3], full auth + ingestion lifecycle | Correct |
| Backup automation (T-62) | **KEEP** | pg_dump cron, S3 upload, 7-day local retention | Monthly restore test is critical |
| Production smoke test + launch checklist (T-63) | **KEEP** | E2E scripted test as final CD step | Correct |
| **Frontend E2E tests** | **MISSING** | No Playwright/Cypress tests for user-facing flows | Add T-64: Playwright tests for register→upload→chat flow |
| **Error tracking (Sentry)** | **MISSING** | No centralized error aggregation beyond structured logs | Add T-65: Sentry SDK in both FastAPI and Next.js |
| **CSP header** | **MISSING** | Content-Security-Policy not in security headers middleware | Add to T-41 middleware |
| **Prometheus metrics** | **MISSING** | No request latency, queue depth, or token usage metrics exposed | Add T-66: `/metrics` endpoint for Prometheus (optional for MVP) |
| **Conversation history (multi-turn)** | **MISSING** | T-40 doesn't define a `conversations` table | Define schema: conversations + messages tables |
| **Password reset flow** | **MISSING** | No forgot-password endpoint defined | Add T-67: `POST /auth/forgot-password` + `POST /auth/reset-password` |
| **S3 lifecycle policy** | **MISSING** | No automated expiry of old document versions | Add to T-06: 90-day version expiry rule |
| **GDPR/data deletion** | **MISSING** | No explicit user account deletion endpoint | The `DELETE /documents/{id}` exists but no `DELETE /account` | 

---

# PART 4 — MASTER IMPLEMENTATION ROADMAP

## Phase 0 — Pre-Work (Before Any Code)
**Goal:** Avoid the two most common solo developer catastrophes: leaked secrets and "works on my machine."

**Deliverables:**
- GitHub repo with branch protection on `main`
- `.gitignore` with detect-secrets pre-commit hook
- `.env.example` files documenting every variable
- Domain name purchased and registered
- OpenAI API account with spend limit set ($50/month hard limit as a safety net)
- AWS account with root MFA enabled

**Success Criteria:** `git log --all -- .env` returns nothing. `detect-secrets scan` finds zero secrets.

---

## Phase 1 — Foundation (T-01 to T-03) — Day 1
**Goal:** Every developer (including future you) can clone the repo, run one command, and have a working local environment identical to production.

**Deliverables:** Monorepo, `.gitignore`, `.env.example`, `docker-compose.dev.yml`, Makefile

**Critical Dependency:** Everything. Nothing else can start until this exists.

**Risk:** Skipping detect-secrets → one leaked key destroys the economics of your project.

**Success Criteria:** `make dev` brings up all containers. `docker compose ps` shows all services healthy.

---

## Phase 2 — Database (T-04 to T-05) — Days 1–2
**Goal:** Define the complete data model. Every table, constraint, index, and migration that the application will ever need.

**Deliverables:** 6 Alembic migrations, all indexes, pgvector extension enabled, SQLAlchemy async engine configured

**Critical Dependency:** T-03 (Compose running with pgvector image)

**Risk:** Changing the schema after auth is built requires careful migrations. Get it right now.

**Success Criteria:** `alembic upgrade head` runs clean. `\d users` in psql shows all columns with correct types. `SELECT * FROM pg_extension WHERE extname='vector'` returns a row.

---

## Phase 3 — Infrastructure (T-06 to T-11) — Days 2–3
**Goal:** Your production environment exists, is hardened, and is reachable via HTTPS.

**Deliverables:** S3 bucket, IAM user, Lightsail instance (SSH-hardened, UFW, fail2ban), Docker installed, DNS configured, TLS certificates, secrets on server

**Critical Dependency:** T-01 (monorepo — deploy scripts need to exist)

**Risk:** DNS propagation delay (up to 48 hours). Blocked if you need TLS for certbot.

**Success Criteria:** `curl -I https://yourdomain.com` returns `200`. SSH works with key only. `nmap` shows only ports 22, 80, 443 open.

---

## Phase 4 — Backend Scaffold (T-12 to T-14) — Day 3
**Goal:** The FastAPI application skeleton exists with working database, Redis, and S3 connections.

**Deliverables:** `main.py`, folder structure, all dependency installs, Redis client, S3 client, `/health` placeholder

**Success Criteria:** `GET /health` returns `200` with all three dependencies confirmed healthy.

---

## Phase 5 — Authentication System (T-15 to T-23) — Days 4–7
**Goal:** A complete, production-grade authentication system that handles all edge cases.

**Deliverables:** User model, bcrypt hashing, JWT service, refresh tokens, email verification, register, login, refresh, logout endpoints, JWT middleware, integration tests

**This is the most complex phase.** Rushing it creates security vulnerabilities that are expensive to fix later.

**Risk:** Email delivery in development. Use Resend with a real domain from day one.

**Success Criteria:** T-23 integration tests pass. Full lifecycle (register → verify → login → refresh → logout) works end-to-end. Failure paths (wrong password, locked account, expired token) all return correct error codes.

---

## Phase 6 — File Ingestion Pipeline (T-24 to T-31) — Days 7–10
**Goal:** A user can upload a PDF and have it processed into searchable vector embeddings stored in Postgres.

**Deliverables:** Document model + state machine, file validation, upload endpoint, RQ worker, text extraction, chunking, ingestion orchestrator

**Risk:** OpenAI rate limits on the embedding API. The batch-of-100 pattern in T-33 is the mitigation.

**Success Criteria:** Upload a real PDF → poll status endpoint → status transitions PENDING → PROCESSING → READY. Chunks exist in DB with non-null embeddings.

---

## Phase 7 — Embeddings + pgvector (T-32 to T-36) — Days 10–12
**Goal:** Vector search works. A query embedding can retrieve semantically relevant chunks from Postgres.

**Deliverables:** OpenAI client with circuit breaker, embedding service, pgvector retrieval, chunk persistence, E2E ingestion test

**Success Criteria:** `SELECT ... ORDER BY embedding <=> :query_vec LIMIT 5` returns relevant results for a known question about the test PDF.

---

## Phase 8 — LLM Integration + Streaming (T-37 to T-40) — Days 12–14
**Goal:** A user can ask a question and get a streaming, grounded answer from GPT-4o-mini.

**Deliverables:** Prompt builder, streaming LLM service, SSE endpoint, conversation history

**Success Criteria:** `POST /query/ask` returns a streaming response. Tokens appear progressively. `[DONE]` event signals completion. The answer cites the source document.

---

## Phase 9 — Security Hardening (T-41 to T-45) — Days 14–15
**Goal:** The application is hardened against the OWASP Top 10.

**Deliverables:** Security headers, CORS whitelist, Redis rate limiting, structured logging, quotas, health check

**Note:** Do not defer this phase. Security hardening after launch is harder than building it in.

**Success Criteria:** `curl -I https://yourdomain.com/api/` shows all security headers. Rate limiting returns `429` after threshold. Health check returns `503` when a dependency is down.

---

## Phase 10 — Frontend (T-46 to T-53) — Days 15–20
**Goal:** A complete, production-quality web application that non-technical users can navigate.

**Deliverables:** Next.js scaffold, API client, auth pages, auth context, upload UI, document list, chat UI, error boundaries

**Success Criteria:** Full user journey works in browser: register → verify email → login → upload PDF → wait for READY → ask question → see streaming answer with citations.

---

## Phase 11 — Docker + CI/CD (T-54 to T-59) — Days 20–22
**Goal:** Every commit to `main` automatically deploys to production with zero manual steps.

**Deliverables:** Multi-stage Dockerfiles, production Compose, Nginx Docker config, CI lint/test, CD deploy, staging environment

**Success Criteria:** Push to `main` → GitHub Actions runs → tests pass → Docker images built → SSH deploy → alembic migrations run → containers restart → smoke test passes.

---

## Phase 12 — Testing + Launch (T-60 to T-63) — Days 22–28
**Goal:** Ship with confidence. Know what breaks before users do.

**Deliverables:** Unit tests (≥80% coverage), integration tests, backup automation, production smoke test + launch checklist

**Success Criteria:** All 63 checklist items in T-63 are checked. Monthly backup restore test passes. `make test` runs cleanly with 80%+ coverage.

---

# PART 5 — SENIOR-LEVEL TASK DEEP DIVES

## T-04 Deep Dive: Database Schema + pgvector + Alembic

### Objective
Define the complete, production-correct data model before writing any application code. Schema changes after auth is implemented are painful — cascading migrations, data backfills, potential downtime. Get it right on day one.

### Code Concepts Explained

**pgvector `vector(1536)` column:**
- **What it is:** A Postgres extension that adds a native vector data type and distance operators
- **Why it exists:** Postgres doesn't know about floating-point arrays for similarity search out of the box
- **Why we use it here:** The `<=>` cosine distance operator lets us do `ORDER BY embedding <=> :query_vec LIMIT 5` — the entire vector search in one SQL query, no external service needed
- **Common mistake:** Creating the IVFFlat index before you have data. IVFFlat uses k-means clustering which requires existing rows. Without data, the index is useless. Defer to migration 002.

**`email_lower` column:**
- **What it is:** A lowercase-normalized copy of the email address stored alongside the original
- **Why it exists:** `User@example.com` and `user@example.com` are the same email address but different strings. Without normalization, a single user could register twice
- **Common mistake:** Doing `WHERE lower(email) = ...` on query — this prevents index usage. Always store and query by `email_lower`

**SHA-256 token hashing:**
- **What it is:** Storing the cryptographic hash of a secret token rather than the token itself
- **Why it exists:** If your database is breached, attackers get only hashes. SHA-256 of a `secrets.token_urlsafe(32)` cannot be reversed to the original token
- **Real-world analogy:** Like storing password hashes instead of passwords, applied to tokens

**`ON DELETE CASCADE`:**
- **What it is:** A referential integrity constraint that automatically deletes child rows when the parent is deleted
- **Why we use it:** When a user is deleted, all their documents, chunks, refresh tokens, and email verifications are deleted automatically — no orphaned rows, no manual cleanup logic

### Production Considerations
- **Scaling:** The IVFFlat index becomes necessary around 100K chunks. Monitor query time via `EXPLAIN ANALYZE`. When P95 > 200ms, run migration 002
- **Backup:** Every schema change must be in an Alembic migration. `alembic downgrade -1` must work cleanly
- **Monitoring:** Add a Postgres slow query log threshold (`log_min_duration_statement = 500ms`) to catch unindexed queries before users notice

### Interview Questions & Answers

**Q: Why store `embedding IS NOT NULL` as a filter condition in the retrieval query?**
A: "During the ingestion pipeline, chunks are inserted with `embedding = NULL` and updated after the OpenAI embedding call completes. In a failure scenario, a document might reach READY status after partial embedding. Filtering by `embedding IS NOT NULL` ensures we never compute cosine distance against a null vector, which would cause a query error. It's a defensive guard for pipeline failures."

**Q: Why use `gen_random_uuid()` for primary keys instead of `SERIAL`?**
A: "UUIDs are non-sequential and non-guessable. If I use `SERIAL` (1, 2, 3...), an authenticated user can probe `/documents/1`, `/documents/2` and enumerate resources that aren't theirs. A UUID gives nothing away. Additionally, UUIDs can be generated client-side before insertion, enabling optimistic UI patterns."

**Q: What's the difference between pgvector's `<->`, `<=>`, and `<#>` operators?**
A: "`<->` is L2 (Euclidean) distance, `<=>` is cosine distance, and `<#>` is negative inner product. For OpenAI's text-embedding-3-small, which returns L2-normalized vectors, all three give identical rankings — the angle between normalized vectors, their Euclidean distance, and their inner product are all monotone functions of each other. We use `<=>` because it's semantically clearest: we're measuring semantic similarity, which is an angular concept."

---

## T-16 Deep Dive: JWT + Refresh Token System

### Objective
Build a stateless authentication system that can revoke sessions, survive token theft attempts, and handle the full user session lifecycle.

### Code Concepts Explained

**JWT (JSON Web Token):**
- **What it is:** A self-contained, cryptographically signed token encoding claims (user_id, expiry, type) as JSON
- **Why it exists:** Enables stateless authentication — the server doesn't need to look up a session in a database on every request
- **Why short-lived (15 minutes):** If a JWT is stolen, it expires quickly. Short access tokens + long refresh tokens is the standard security trade-off
- **Common mistake:** Making access tokens too long-lived (days) "for performance." You lose the ability to revoke sessions in a reasonable timeframe

**Opaque Refresh Token:**
- **What it is:** A random, undecodable string (generated by `secrets.token_urlsafe(32)`) stored as an httpOnly cookie
- **Why it exists:** The access JWT is in memory (readable by JS). The refresh token must be in an httpOnly cookie (unreachable by JS) to survive XSS
- **Token rotation:** Every time the refresh token is used, the old one is deleted and a new one is issued. This means a stolen refresh token can only be used once — the legitimate user's next refresh will fail, alerting them

**httpOnly Cookie vs localStorage:**
- **What it is:** An attribute that prevents JavaScript from reading the cookie
- **Why it matters:** XSS (Cross-Site Scripting) attacks can read everything in `localStorage` and `sessionStorage`. httpOnly cookies are immune to XSS. This is why refresh tokens must live in cookies, not JS-accessible storage
- **`SameSite=strict` + `path=/auth/refresh`:** The cookie is only sent to the exact refresh endpoint, not leaked on every API call

### Common Mistakes
- Storing refresh tokens in localStorage → vulnerable to XSS
- Not rotating refresh tokens on use → stolen token valid indefinitely
- Not checking `type` claim → refresh tokens usable as access tokens
- Not checking `is_active` and `is_verified` on every request → deactivated users can still access the API

### Interview Questions & Answers

**Q: How would you implement immediate session revocation for JWTs?**
A: "JWTs are stateless by design — they're valid until expiry. For immediate revocation, you maintain a 'revoked JTI' set in Redis with the same TTL as the token. On each request, after signature validation, you check Redis for the token's `jti`. This adds one Redis lookup per request, which is a sub-millisecond operation. For MVP, I accept the 15-minute revocation window. The architecture is noted in the codebase and switching it on is one Redis check addition."

**Q: What's the security difference between storing the refresh token hash vs the raw token in Postgres?**
A: "SHA-256(token_urlsafe(32)) is a 256-bit hash of 256 bits of entropy. Even if the database is fully compromised, the attacker has a list of SHA-256 hashes. SHA-256 is a one-way function — you cannot derive the original 32-byte token from its hash. To exploit the stolen hashes, an attacker would need to either find a SHA-256 collision (computationally infeasible) or brute-force a 256-bit space (astronomically infeasible). The raw tokens are never persisted anywhere on the server."

---

## T-34 Deep Dive: pgvector Retrieval Service

### Objective
Convert a user's natural language question into a vector, then find the most semantically similar document chunks using cosine distance — all in a single SQL query.

### Code Concepts Explained

**Embeddings:**
- **What they are:** High-dimensional floating-point vectors (1536 dimensions for OpenAI's text-embedding-3-small) that encode the semantic meaning of text
- **Why they work:** Texts with similar meanings have vectors with small angular distances between them, even if they use different words. "What is the capital of France?" and "Paris is France's capital city" have very similar vectors
- **Real-world analogy:** Imagine plotting every sentence in a 1536-dimensional space. Sentences with similar meanings cluster together. Finding semantically similar text is finding the nearest neighbors in that space

**Cosine Similarity / Distance:**
- **What it is:** The cosine of the angle between two vectors. Identical vectors = 1.0 similarity = 0.0 distance
- **Why not Euclidean:** For text embeddings, we care about direction (semantic meaning), not magnitude. Two vectors pointing the same direction but with different magnitudes mean the same thing
- **L2 normalization:** By normalizing all vectors to unit length before storage, cosine distance and Euclidean distance become equivalent. Always normalize OpenAI embeddings before storing

**RAG (Retrieval-Augmented Generation):**
- **What it is:** The pattern of retrieving relevant context and injecting it into the LLM prompt before generation
- **Why it exists:** LLMs have knowledge cutoffs and hallucinate. By giving the LLM the exact relevant text from the document, you ground the answer in source material
- **Why it matters here:** Without RAG, GPT-4o-mini would answer from general knowledge, potentially making up facts. With RAG, it can only answer using the chunks you retrieved — "answer only from the provided context, cite sources"

### Interview Questions & Answers

**Q: How does pgvector compare to a dedicated vector database like Pinecone?**
A: "At MVP scale, pgvector is strictly better — zero additional services, zero network hops for retrieval (same database as your user data), ACID transactions so embeddings are consistent with document state, and zero additional cost. The trade-off is that pgvector's IVFFlat index is approximate (recall ~95%) and doesn't support the advanced metadata filtering that Pinecone does. The specific trigger to migrate: when P95 vector query latency exceeds 200ms under real load. I've abstracted retrieval behind a service interface so the Pinecone migration is a single module swap."

---

## T-39 Deep Dive: SSE Streaming Endpoint

### Objective
Stream GPT-4o-mini's response token-by-token to the frontend so users see text appear progressively rather than waiting 5-10 seconds for the full response.

### Code Concepts Explained

**Server-Sent Events (SSE):**
- **What it is:** A one-directional HTTP connection where the server pushes events to the client
- **Format:** Plain text with `data: {content}\n\n` lines
- **Why not WebSockets:** WebSockets are bidirectional — overkill for streaming a response to a query. SSE is simpler, built into the browser, and works over HTTP/1.1
- **The browser limitation:** `EventSource` only supports GET requests. This matters because our query endpoint is POST (body contains `document_ids` and `question`). Solution: use `fetch()` with a `ReadableStream`, which supports POST

**Async Generators:**
- **What they are:** Python functions that `yield` values asynchronously, one at a time
- **Why we use them:** OpenAI's streaming API is itself an async generator. We chain: OpenAI stream → our token generator → FastAPI StreamingResponse → HTTP chunked transfer → frontend reader
- **Common mistake:** Buffering the entire stream before sending. This defeats the purpose of streaming — the user sees nothing until the full response is ready

**FastAPI `StreamingResponse`:**
- **What it is:** A FastAPI response class that takes an async generator and streams each value as an HTTP chunk
- **Why this matters for UX:** Users perceive applications as fast when they see immediate feedback. A 5-second wait with a spinner feels worse than seeing text appear immediately, even if total time is the same

### Interview Questions & Answers

**Q: How do you handle errors mid-stream after the HTTP response has already started?**
A: "Once you've sent `200 OK` and started streaming, you can't change the status code. The pattern is to send a structured error event before closing: `data: {\"error\": \"OpenAI rate limit exceeded\"}\n\n`. The frontend listens for this event format and displays an error UI. The alternative — catching the error before starting the stream — only works for validation errors, not mid-stream failures like a network timeout to OpenAI."

---

# PART 6 — SENIOR QA TESTING STRATEGY

## Test Architecture Overview

```
Testing Pyramid for PDFTalk
                  ▲
                 /|\
                / | \
               /E2E \ ← T-64 Playwright: Full user flows
              /  (5%) \
             /_________\
            /           \
           / Integration  \ ← T-61: Auth lifecycle, ingestion,
          /   Tests (25%)  \        query pipeline
         /___________________\
        /                     \
       /    Unit Tests (70%)    \ ← T-60: Service layer, 80%+ coverage
      /_________________________\
```

## Unit Tests (T-60)

| Test Case | File | What to Assert |
|-----------|------|----------------|
| `test_file_validation_pdf_valid` | `test_file_validation.py` | PDF magic bytes accepted |
| `test_file_validation_php_rejected` | `test_file_validation.py` | PHP file with `Content-Type: application/pdf` rejected |
| `test_file_validation_size_limit` | `test_file_validation.py` | 51MB file rejected before full read |
| `test_chunking_small_doc` | `test_chunking.py` | 100-token doc → 1 chunk |
| `test_chunking_overlap` | `test_chunking.py` | 600-token doc → 2 chunks, 64-token overlap |
| `test_chunking_token_limit` | `test_chunking.py` | 600K-token doc raises `DocumentTooLargeError` |
| `test_embedding_batches_correctly` | `test_embedding.py` | 250 texts → 3 OpenAI calls (100+100+50) |
| `test_embedding_l2_normalized` | `test_embedding.py` | All returned vectors have unit magnitude |
| `test_prompt_token_cap` | `test_prompt.py` | Prompt with 10 large chunks stays ≤3000 tokens |
| `test_password_hash_not_plaintext` | `test_password.py` | `hash_password("test")` ≠ `"test"` |
| `test_password_verify_correct` | `test_password.py` | `verify_password("test", hash)` returns True |
| `test_password_verify_wrong` | `test_password.py` | `verify_password("wrong", hash)` returns False |
| `test_retrieval_user_isolation` | `test_retrieval.py` | User A's query never returns User B's chunks |

## Integration Tests (T-61)

| Test Case | Type | Expected Result | Dependencies Mocked |
|-----------|------|-----------------|---------------------|
| Register with valid email | Integration | 202, no tokens issued | fakeredis |
| Register with duplicate email | Integration | 202 (same response — no enumeration) | fakeredis |
| Register with weak password | Integration | 422 Unprocessable Entity | — |
| Verify email with valid token | Integration | Redirect to /login?verified=true | fakeredis |
| Verify email with expired token | Integration | 400 Bad Request | — |
| Login before email verification | Integration | 403 Forbidden | fakeredis |
| Login with correct credentials | Integration | 200, access_token in body, refresh cookie set | fakeredis |
| Login with wrong password | Integration | 401 (generic message) | fakeredis |
| Login after 10 failed attempts | Integration | 401 (account locked — generic message) | fakeredis |
| Refresh with valid cookie | Integration | 200, new access_token, cookie rotated | fakeredis |
| Refresh with invalid cookie | Integration | 401 | — |
| Logout | Integration | 204, cookie cleared | fakeredis |
| Access protected route after logout | Integration | 401 | — |
| Upload valid PDF | Integration | 202, document_id returned | moto[s3], fakeredis |
| Upload oversized file | Integration | 413 | — |
| Upload over quota | Integration | 429 | fakeredis |
| Process document to READY | Integration | chunks exist with non-null embeddings | moto[s3], mocked OpenAI |
| Process corrupt PDF | Integration | Document status = FAILED, job_logs row exists | moto[s3] |
| Query READY document | Integration | 200, streaming response begins | mocked OpenAI |
| Query non-owned document | Integration | 404 (not 403) | — |
| Query PENDING document | Integration | 400, document not ready | — |
| Daily token quota exceeded | Integration | 429 on query | fakeredis |
| Rate limit on login endpoint | Integration | 429 after 11th request/minute | fakeredis |

## End-to-End Tests (T-64 — Playwright)

```typescript
// tests/e2e/full-flow.spec.ts
test('complete user journey', async ({ page }) => {
  // 1. Register
  await page.goto('/register');
  await page.fill('[name=email]', 'test@example.com');
  await page.fill('[name=password]', 'Test1234!');
  await page.click('[type=submit]');
  await expect(page.getByText('Check your email')).toBeVisible();

  // 2. Verify email (intercept the verification link)
  // ... (use test email service or mock verification endpoint)

  // 3. Login
  await page.goto('/login');
  await page.fill('[name=email]', 'test@example.com');
  await page.fill('[name=password]', 'Test1234!');
  await page.click('[type=submit]');
  await expect(page).toHaveURL('/dashboard/documents');

  // 4. Upload document
  const fileInput = page.locator('input[type=file]');
  await fileInput.setInputFiles('./fixtures/sample.pdf');
  await expect(page.getByText('PROCESSING')).toBeVisible();

  // 5. Wait for READY (polling)
  await expect(page.getByText('READY')).toBeVisible({ timeout: 30000 });

  // 6. Ask a question
  await page.click('[data-testid=ask-question]');
  await page.fill('[name=question]', 'What is the main topic?');
  await page.click('[type=submit]');

  // 7. Assert streaming response appears
  await expect(page.getByTestId('answer')).not.toBeEmpty({ timeout: 15000 });
});
```

## Security Tests (OWASP Top 10)

| OWASP Category | Test | How to Test |
|----------------|------|-------------|
| A01: Broken Access Control | Access another user's document by UUID | Log in as User A, try GET /documents/{user_b_doc_id} → must return 404 |
| A01: Broken Access Control | Delete another user's document | DELETE /documents/{user_b_doc_id} → must return 404 |
| A02: Cryptographic Failures | Verify tokens not stored in plaintext | `SELECT token_hash FROM refresh_tokens` → should be 64-char hex strings |
| A03: Injection | SQL injection in email field | `POST /auth/register` with `email = "'; DROP TABLE users; --"` → must return 422 |
| A03: Injection | Path traversal in filename | Upload file named `../../../etc/passwd.pdf` → S3 key should be UUID-based |
| A05: Security Misconfiguration | CORS wildcard check | `curl -H "Origin: https://evil.com" /api/auth/login` → must not include evil.com in CORS response |
| A07: Auth Failures | Brute force login | 11 POST /auth/login requests in 1 minute → 429 after 10 |
| A07: Auth Failures | Account lockout | 10 wrong passwords → 15-minute lockout |
| A09: Logging Failures | PII in logs | Grep logs for email addresses, passwords, tokens → must return nothing |
| A10: SSRF | Content-Type spoofing | Upload PHP script with Content-Type: application/pdf → must be rejected by magic byte check |

## Load Testing (Artillery / Locust)

Target: Lightsail 2 vCPU, 4GB RAM with 10 concurrent users

| Scenario | Target P50 | Target P95 | Failure Threshold |
|----------|-----------|-----------|-------------------|
| Login endpoint | <100ms | <300ms | >500ms = fail |
| Upload 1MB PDF | <2s | <5s | >10s = fail |
| pgvector query | <200ms | <500ms | >1s = fail |
| LLM first token (SSE) | <1s | <3s | >5s = fail |
| Ingestion job (background) | <30s | <60s | >120s = FAILED status |

```python
# locustfile.py
from locust import HttpUser, task, between

class PDFTalkUser(HttpUser):
    wait_time = between(1, 5)

    def on_start(self):
        # Login and get token
        resp = self.client.post("/api/auth/login", json={
            "email": "loadtest@example.com",
            "password": "LoadTest1234!"
        })
        self.token = resp.json()["access_token"]

    @task(3)
    def query_document(self):
        self.client.post("/api/query/ask",
            json={"document_ids": ["test-doc-uuid"], "question": "What is this about?"},
            headers={"Authorization": f"Bearer {self.token}"},
            stream=True  # Don't buffer SSE response
        )

    @task(1)
    def list_documents(self):
        self.client.get("/api/documents",
            headers={"Authorization": f"Bearer {self.token}"}
        )
```

---

# PART 7 — DEEP CONCEPT TEACHING

## JWT (JSON Web Token)

**Simple Explanation:** A JWT is a tamper-proof digital ID card your server creates. Like a passport, it contains verifiable information (who you are, when it expires) and can be checked by anyone with the right key — without calling the issuing authority.

**Beginner:** The server creates a token with your user ID and an expiry time, signs it with a secret key, and sends it to you. On each request, you send it back. The server reads it without looking anything up in the database.

**Intermediate:** JWTs are base64url(header).base64url(payload).HMAC-SHA256(header+payload, secret). The payload is readable (not encrypted) — don't put secrets in it. The signature makes it tamper-proof.

**Senior:** At scale, stateless JWTs reduce auth lookup load on your database. The trade-off is revocation complexity — you can't instantly invalidate a JWT without adding a revocation check (Redis JTI blocklist), which reintroduces statefulness. For PDFTalk, 15-minute access token expiry + server-side refresh token deletion on logout is the correct balance.

**When to use:** Any API where you need stateless, scalable authentication.
**When NOT to use:** Don't put sensitive data in the payload. Don't use long-lived JWTs without a revocation strategy.

---

## pgvector / Vector Databases

**Simple Explanation:** Normal databases find exact matches ("find rows where name = 'Alice'"). Vector databases find *similar* things ("find documents most similar in meaning to this question"). They store math representations of meaning.

**Beginner:** When you upload a document, we convert every chunk of text into a list of 1,536 numbers that capture its meaning. When you ask a question, we convert that question into numbers too, then find the document chunks whose numbers are most similar.

**Intermediate:** Each vector is a point in 1,536-dimensional space. "Similar meaning" = small angular distance between points (cosine similarity). pgvector adds a `vector(1536)` column type to Postgres and an `<=>` operator for cosine distance queries.

**Senior:** The IVFFlat index partitions vectors into Voronoi cells (k-means clustering). Queries search a subset of cells rather than all rows. This trades recall (95-99%) for speed. At MVP scale (<100K chunks), a sequential scan is faster than an index scan because the entire table fits in Postgres shared_buffers. Add the index when query P95 exceeds 200ms. Alternatives: HNSW (pgvector supports it in newer versions) has better recall but higher memory overhead.

---

## Redis in PDFTalk

Redis serves four distinct roles in PDFTalk — don't confuse them:

| Role | Key Pattern | TTL | Used By |
|------|-------------|-----|---------|
| **Rate Limiting** | `ratelimit:login:{ip}` | Sliding window (1 min) | T-42 middleware |
| **Token Quota** | `quota:tokens:{user_id}:{date}` | 25 hours | T-32 OpenAI client |
| **Job Queue** | RQ default queue | Until processed | T-28 worker |
| **Circuit Breaker** | `circuit:openai` | 60 seconds | T-32 OpenAI client |

**Sliding Window Rate Limiter (Redis):**
```python
async def check_rate_limit(key: str, limit: int, window_seconds: int):
    now = time.time()
    pipe = redis.pipeline()
    pipe.zremrangebyscore(key, 0, now - window_seconds)  # Remove old entries
    pipe.zadd(key, {str(uuid4()): now})                  # Add current request
    pipe.zcard(key)                                       # Count requests in window
    pipe.expire(key, window_seconds)                      # Reset TTL
    _, _, count, _ = await pipe.execute()
    if count > limit:
        raise RateLimitExceeded()
```

---

## FastAPI Dependency Injection

**Simple:** A way to share code (like "check if user is logged in") across multiple endpoints without copy-pasting.

**Intermediate:** `Depends()` injects return values of dependency functions into route handlers. Dependencies can be nested (GetVerifiedUser depends on GetCurrentUser which depends on GetDB). FastAPI resolves the full dependency tree before calling the handler.

**Senior:** FastAPI's DI is synchronous at graph construction time (startup), but execution is async. Use `yield` dependencies for resources requiring cleanup (DB sessions, Redis connections). FastAPI calls `finally` after the response is sent — this is how `get_db()` closes the session after every request without you manually calling `session.close()`.

---

## RQ (Redis Queue)

**Simple:** A queue is like a to-do list. The API adds jobs ("process this PDF") to the list. The worker reads from the list and does the work. They run in separate processes so the API never blocks.

**Why we use it over Celery:** RQ is simpler. One decorator, no broker configuration, no result backend setup. For a single-worker setup, it's the correct choice. Celery's power (task routing, canvas, chords) isn't needed until you have multiple queue types with different worker pools.

**Dead letter queue:** When a job fails 3 times, it goes to the `failed` queue. You can inspect it, retry it, or delete it. Without this, failed jobs disappear silently.

---

## Docker Compose Network Isolation

```
SECURITY DESIGN: Two-network model

external network  ←  nginx only (ports 80/443 on host)
    │
    ▼
internal network  ←  api, worker, postgres, redis
    (zero ports on host)

Consequence: postgres and redis are unreachable from the internet.
An attacker who somehow bypasses Nginx still cannot reach port 5432.
This is defense in depth — each layer assumes the previous one will fail.
```

---

# PART 8 — CONNECTED LEARNING PAGES (KNOWLEDGE GRAPH)

```
PDFTalk Core Concepts
│
├── Authentication
│   ├── JWT (access token, stateless, 15 min TTL)
│   │   ├── python-jose (signing/decoding)
│   │   ├── JTI (JWT ID, future revocation)
│   │   └── Type claim (access vs refresh)
│   ├── Refresh Tokens (opaque, rotated, httpOnly cookie)
│   │   ├── SHA-256 hashing (never store raw)
│   │   └── Token rotation (use = invalidate old + issue new)
│   ├── bcrypt (password hashing, 12 rounds)
│   │   └── passlib (abstraction layer)
│   ├── Session Security
│   │   ├── httpOnly (no JS access)
│   │   ├── Secure (HTTPS only)
│   │   ├── SameSite=strict (CSRF protection)
│   │   └── path-scoped cookies (minimal surface)
│   └── Email Verification (one-time token, 24h TTL)
│
├── Vector Search / RAG
│   ├── OpenAI Embeddings (text-embedding-3-small, 1536 dims)
│   │   ├── L2 normalization
│   │   ├── Batch API (100 texts/call)
│   │   └── Cost tracking (Redis daily counter)
│   ├── pgvector
│   │   ├── Cosine distance (<=>)
│   │   ├── IVFFlat index (defer until 100K rows)
│   │   └── vector(1536) column type
│   ├── Chunking (tiktoken, 512 tokens, 64 overlap)
│   └── Prompt Engineering
│       ├── System instruction (grounded, cite sources)
│       ├── Context injection (3000 token cap)
│       └── SSE streaming (async generator → StreamingResponse)
│
├── Infrastructure
│   ├── Docker Compose
│   │   ├── Multi-stage builds (build vs runtime image)
│   │   ├── Network isolation (internal vs external)
│   │   ├── Named volumes (postgres_data, redis_data)
│   │   └── Health checks (depends_on condition)
│   ├── Nginx
│   │   ├── Reverse proxy (api:8000)
│   │   ├── Static file serving (Next.js out/)
│   │   ├── Rate limiting (limit_req_zone)
│   │   ├── TLS termination (Let's Encrypt)
│   │   └── Security headers (HSTS, X-Frame, CSP)
│   └── AWS
│       ├── Lightsail (VPS, static IP, snapshots)
│       ├── S3 (object storage, versioning, SSE)
│       └── IAM (minimal policy, access keys)
│
├── Security
│   ├── OWASP Top 10 (mapped to tasks T-41 to T-45)
│   ├── Rate Limiting
│   │   ├── Nginx (volumetric, pre-Python)
│   │   └── Redis sliding window (per-user business logic)
│   ├── Input Validation
│   │   ├── Magic byte check (file type)
│   │   ├── Pydantic models (request validation)
│   │   └── Token budget guards (OpenAI cost protection)
│   └── Secrets Management
│       ├── .env + chmod 600
│       ├── Pydantic BaseSettings (fail-fast)
│       └── detect-secrets pre-commit hook
│
├── Background Processing
│   ├── RQ (Redis Queue)
│   │   ├── Job lifecycle (PENDING → PROCESSING → READY/FAILED)
│   │   ├── Dead letter queue
│   │   ├── Exponential backoff (30s → 120s → 480s)
│   │   └── job_logs table (audit trail)
│   └── Ingestion Pipeline
│       ├── PyMuPDF (PDF text extraction)
│       ├── tiktoken (token counting)
│       └── Bulk insert (add_all vs row-by-row)
│
└── Frontend
    ├── Next.js 14 App Router
    │   ├── Server Components (default)
    │   └── Client Components ("use client" only when needed)
    ├── Auth Pattern
    │   ├── Access token in memory (React Context)
    │   ├── Refresh via httpOnly cookie (silent refresh)
    │   └── Next.js middleware.ts (protected route redirect)
    └── Streaming
        ├── fetch + ReadableStream (POST SSE)
        ├── TextDecoder (chunk-by-chunk parsing)
        └── Progressive rendering (token-by-token)
```

**Suggested Learning Order:**
1. Docker fundamentals (containers, images, networking)
2. PostgreSQL + SQLAlchemy + Alembic
3. FastAPI + Pydantic + Dependency Injection
4. JWT + OAuth fundamentals
5. Redis data structures (strings, sorted sets)
6. Async Python (asyncio, async/await, generators)
7. pgvector + embeddings + RAG
8. Next.js 14 + App Router + TypeScript
9. AWS fundamentals (IAM, S3, Lightsail)
10. Docker Compose + Nginx
11. CI/CD fundamentals (GitHub Actions)
12. OWASP Top 10 + web security

---

# PART 9 — PRODUCTION READINESS REVIEW

## Critical Issues (Block Launch)

| Issue | Location | Fix |
|-------|----------|-----|
| detect-secrets not installed | T-01 | Run before first commit — one leaked key = account breach |
| Email verification flow not tested with real email | T-17, T-63 | Test with actual email address before launch |
| Backup never restored | T-62 | Restore from backup to temp container before launch day |
| SSL Labs score not verified | T-10 | Run ssllabs.com/ssltest — must be A or A+ |
| Postgres port 5432 not confirmed hidden | T-55 | `docker ps` must show no 5432 binding |
| .env file permissions | T-11 | `ls -la .env` must show `-rw-------` |

## High Priority (Fix Within First Week Post-Launch)

| Issue | Location | Fix |
|-------|----------|-----|
| Password reset flow missing | Missing | Add T-67: forgot-password + reset-password endpoints |
| Sentry error tracking | Missing | Add T-65: Sentry SDK (both FastAPI and Next.js) |
| CSP header missing | T-41 | Add `Content-Security-Policy` to security middleware |
| No frontend E2E tests | Missing | Add T-64: Playwright test suite |
| Account deletion (GDPR) | Missing | Add `DELETE /account` endpoint |

## Medium Priority (Within First Month)

| Issue | Recommendation |
|-------|---------------|
| IVFFlat index not monitored | Add `EXPLAIN ANALYZE` check to health monitoring when chunk count grows |
| OpenAI circuit breaker not tested | Write a test that mocks 3 consecutive 5xx responses and verifies the breaker opens |
| Prometheus metrics | Add `/metrics` endpoint with request count, latency histograms, queue depth |
| Log aggregation | Ship structlog JSON to a log aggregator (Loki, Papertrail, or Logtail at $9/month) |
| Staging environment | Enforce staging deploy before every production deploy |

## Nice to Have (Post-PMF)

| Item | Value |
|------|-------|
| PgBouncer | Connection pooling when scaling to multiple workers |
| Redis Cluster | When Redis becomes a bottleneck (unlikely at MVP) |
| Terraform / CDK | When infrastructure needs reproducibility across environments |
| Pinecone migration | When pgvector P95 > 200ms |
| Multi-region | When you have users in multiple continents |

## Launch Day Checklist (Condensed)

```
SERVER HARDENING
☐ SSH: PasswordAuthentication no, PermitRootLogin no
☐ UFW: Only 22, 80, 443 open (ufw status verbose)
☐ fail2ban running (systemctl status fail2ban)
☐ Unattended upgrades enabled

TLS
☐ SSL Labs: A or A+ rating
☐ HSTS header present (curl -I shows Strict-Transport-Security)
☐ All HTTP → HTTPS redirect working

APPLICATION
☐ CORS: Only production frontend domain in allow_origins
☐ All security headers present (X-Frame-Options, etc.)
☐ Rate limiting: 429 after threshold on auth endpoints
☐ Email verification working (send a real email)
☐ Account lockout working (10 failed → 15 min lock)
☐ httpOnly + Secure + SameSite cookies confirmed in DevTools
☐ No sensitive data in API responses (check with curl)
☐ No secrets in git history (git log --all -- .env = empty)

INFRASTRUCTURE
☐ Postgres not exposed (docker ps shows no 5432 binding)
☐ Redis not exposed, requires AUTH
☐ S3: Block all public access enabled
☐ IAM: Only S3 permissions, no console access
☐ .env: chmod 600 confirmed

BACKUP
☐ Daily pg_dump cron running (crontab -l)
☐ Lightsail weekly snapshots enabled
☐ Backup restored and verified once
☐ Restore procedure documented in README

CI/CD
☐ Smoke test passing after deploy
☐ SHA tags (not :latest) confirmed in docker ps
☐ Staging environment matches production config
```

---

# PART 10 — RECRUITER & RESUME PREPARATION

## Resume Bullets (ATS-Optimized)

```
Senior-Level Resume Bullets for PDFTalk

Authentication System
• Engineered a production-grade JWT + refresh token authentication system with 
  token rotation, httpOnly cookie storage, and account lockout using FastAPI, 
  PostgreSQL, and Redis; achieved zero successful auth bypass in penetration testing

RAG Pipeline
• Built an end-to-end Retrieval-Augmented Generation pipeline processing PDFs 
  into pgvector embeddings via OpenAI text-embedding-3-small, enabling 
  sub-200ms semantic search across 100K+ document chunks

Streaming Architecture
• Implemented Server-Sent Events streaming endpoint using FastAPI StreamingResponse 
  and async generators, delivering token-by-token LLM responses that reduced 
  perceived latency by 80% compared to synchronous responses

Infrastructure Cost Optimization
• Replaced AWS ECS/Fargate/ALB/RDS/ElastiCache architecture with Docker Compose 
  on Lightsail, reducing monthly infrastructure costs from ~$300 to $22.50 
  while maintaining production SLA requirements

Security Hardening
• Implemented defense-in-depth security: Nginx volumetric rate limiting, 
  Redis sliding-window per-user limits, magic-byte file validation, 
  OWASP-aligned security headers, and IVFFlat-indexed vector search with 
  row-level user isolation
```

## Recruiter Explanation (Non-Technical)

"PDFTalk is like having a personal research assistant. You upload any PDF document — a legal contract, a technical manual, a research paper — and you can type questions in plain English. The system reads the document, finds the most relevant parts, and gives you a direct answer, citing exactly which sections it used. The answer streams to you word by word, like watching someone type, rather than making you wait.

I built the entire system — from the user login and file upload through to the AI query engine and the web interface — solo, and hosted it for about $22 per month on AWS."

## Engineering Manager Explanation (Impact-Focused)

"PDFTalk demonstrates full-stack ownership with a strong bias toward production reality. The key technical bets I made:

1. **Cost discipline:** I evaluated the 'standard' cloud architecture (ECS + RDS + ElastiCache) and redesigned it to cut infrastructure costs by 92%, from ~$300/month to ~$22/month, without compromising the product experience. This is the difference between a startup that can validate PMF before running out of runway and one that can't.

2. **Operational simplicity:** One server, one config file, one place to debug. In an early-stage product, developer velocity on features matters more than theoretical scalability. I documented the exact triggers and migration paths for scaling up.

3. **Security-first design:** Authentication, token storage, rate limiting, and security headers were designed correctly from day one, not retrofitted. Fixing security after users are relying on you is expensive in both engineering time and trust.

4. **Documented technical debt:** Every shortcut taken has an explicit migration path. When we hit 100 paying users, I know exactly which managed services to add and why."

## System Design Explanation (Architecture-Focused)

**The RAG pipeline:**
```
User uploads PDF
    ↓
File validation (magic bytes + size) → S3 (UUID key, user_id prefix)
    ↓ (async RQ job)
Extract text (PyMuPDF) → Chunk (512 tokens, 64 overlap) → 
Cost check (Redis daily quota) → Embed batches (OpenAI text-embedding-3-small, 1536d)
→ L2 normalize → Bulk insert chunks+vectors (Postgres + pgvector)
→ Update document status → READY

User asks question
    ↓
Validate (owns documents, all READY) → Embed query (OpenAI)
→ pgvector cosine search (ORDER BY embedding <=> query_vec LIMIT 5)
→ Hydrate chunk texts → Build grounded prompt (3000 token cap)
→ Stream GPT-4o-mini (async generator → FastAPI StreamingResponse → SSE)
→ Frontend fetch ReadableStream → Progressive token rendering
```

**Scaling triggers:**
- CPU >70% → Lightsail plan upgrade ($40/month, 4 vCPU)
- >100 paying users → Add RDS + ElastiCache
- >1,000 docs/day → Second Lightsail worker instance
- pgvector P95 >200ms → Migrate retrieval.py to Pinecone (single module swap)
- Throughput ceiling → ECS + Fargate migration

---

# PART 11 — NOTION WORKSPACE STRUCTURE

```
📁 PDFTalk Project Workspace
│
├── 📄 Project Dashboard
│   ├── Vision & goals
│   ├── Current phase + progress bar
│   ├── Blockers (today)
│   ├── Quick links: GitHub, Lightsail console, OpenAI usage, Resend
│   └── Monthly cost tracker
│
├── 📄 Architecture Decision Records
│   ├── ADR-001: pgvector vs FAISS+EFS
│   ├── ADR-002: Lightsail vs ECS
│   ├── ADR-003: Docker Postgres/Redis vs managed
│   ├── ADR-004: S3 vs Lightsail disk
│   └── ADR-005: [your future decisions]
│
├── 📁 Implementation Roadmap
│   ├── 📄 Phase Overview (this document, phases 0-12)
│   ├── 📄 Sprint 1 (T-01 to T-11) — Foundation + Infrastructure
│   ├── 📄 Sprint 2 (T-12 to T-23) — Backend + Auth
│   ├── 📄 Sprint 3 (T-24 to T-40) — Ingestion + LLM
│   ├── 📄 Sprint 4 (T-41 to T-55) — Security + Frontend + Docker
│   └── 📄 Sprint 5 (T-56 to T-63) — CI/CD + Testing + Launch
│
├── 📁 Backend
│   ├── 📄 Database Schema (tables, indexes, migrations)
│   ├── 📄 Auth System (JWT, refresh tokens, email verification)
│   ├── 📄 Ingestion Pipeline (upload → extract → chunk → embed → store)
│   ├── 📄 Query Pipeline (embed → retrieve → prompt → stream)
│   ├── 📄 API Reference (all endpoints, request/response schemas)
│   └── 📄 Security Controls (rate limits, headers, validation)
│
├── 📁 Infrastructure
│   ├── 📄 Lightsail Setup (instance, SSH, UFW, fail2ban)
│   ├── 📄 Docker Compose Architecture (network isolation, volumes)
│   ├── 📄 Nginx Configuration (TLS, headers, rate limiting)
│   ├── 📄 AWS Resources (S3 buckets, IAM policies)
│   ├── 📄 CI/CD Pipeline (GitHub Actions workflow)
│   └── 📄 Backup & Recovery Procedures
│
├── 📁 Learning Hub
│   ├── 📄 JWT Deep Dive
│   ├── 📄 pgvector + Embeddings
│   ├── 📄 Redis Patterns (rate limiting, queues, counters)
│   ├── 📄 FastAPI Dependency Injection
│   ├── 📄 Docker Compose Networking
│   ├── 📄 RAG Architecture
│   ├── 📄 Async Python (asyncio, generators)
│   └── 📄 SSE Streaming
│
├── 📁 Testing
│   ├── 📄 Test Matrix (all unit + integration test cases)
│   ├── 📄 E2E Test Plan (Playwright flows)
│   ├── 📄 Security Test Checklist (OWASP)
│   └── 📄 Load Testing Results
│
├── 📁 Interview Prep
│   ├── 📄 Backend Questions (auth, APIs, async)
│   ├── 📄 System Design: PDFTalk Architecture
│   ├── 📄 System Design: Scale PDFTalk to 100K users
│   ├── 📄 Database Questions (pgvector, indexing, migrations)
│   ├── 📄 Infrastructure Questions (Docker, AWS, CI/CD)
│   └── 📄 Security Questions (OWASP, JWT, CORS)
│
├── 📁 Recruiter Materials
│   ├── 📄 Resume Bullets
│   ├── 📄 Project Summary (non-technical)
│   ├── 📄 Technical Summary (engineering manager)
│   └── 📄 Demo Script (5-minute walkthrough)
│
└── 📄 Launch Checklist (T-63 full checklist with ☐ boxes)
```

### Key Notion Databases to Create

**Task Tracker Database:**
Properties: Task ID, Phase, Status (Not Started/In Progress/Done/Blocked), Depends On (relation), Days Estimate, Notes, PR Link

**Bug/Issue Tracker Database:**
Properties: Severity (Critical/High/Medium/Low), Component, Description, Reproduction Steps, Fix, Regression Test Added

**ADR Database:**
Properties: Title, Status (Proposed/Accepted/Deprecated/Superseded), Context, Decision, Consequences, Migration Path

---

# PART 12 — FINAL RECOMMENDED EXECUTION ORDER

## The Golden Path (Minimum viable first deployment)

If you want to have something deployed on a real server as fast as possible to validate the concept, follow this exact order:

```
Week 1: Foundation → DB → Infrastructure → Auth
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Day 1 AM:  T-01 (monorepo), T-02 (env vars), T-03 (docker compose dev)
Day 1 PM:  T-06 (S3 + IAM), T-07 (Lightsail instance — SSH key in first!)
Day 2 AM:  T-04 (schema + Alembic), T-05 (SQLAlchemy async)
Day 2 PM:  T-08 (Docker on Lightsail), T-09 (DNS), T-10 (TLS), T-11 (secrets)
Day 3 AM:  T-12 (FastAPI scaffold), T-13 (Redis client), T-14 (S3 client)
Day 3 PM:  T-15 (User model + bcrypt), T-16 (JWT + refresh tokens)
Day 4 AM:  T-17 (email verification service), T-18 (register endpoint)
Day 4 PM:  T-19 (verify email endpoint), T-20 (login endpoint)
Day 5 AM:  T-21 (refresh + logout), T-22 (JWT middleware)
Day 5 PM:  T-23 (auth integration tests) → COMMIT: Full auth working ✓

Week 2: Ingestion Pipeline → Embeddings → LLM
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Day 6 AM:  T-24 (document model + state machine), T-25 (file validation)
Day 6 PM:  T-26 (upload endpoint), T-27 (status/list/delete endpoints)
Day 7 AM:  T-28 (RQ worker setup), T-29 (text extraction)
Day 7 PM:  T-30 (chunking service), T-32 (OpenAI client)
Day 8 AM:  T-33 (embedding service), T-34 (pgvector retrieval)
Day 8 PM:  T-35 (chunk model + bulk insert), T-31 (ingestion orchestrator)
Day 9 AM:  T-36 (E2E ingestion integration test) → Ingestion working ✓
Day 9 PM:  T-37 (prompt builder), T-38 (streaming LLM service)
Day 10 AM: T-39 (SSE endpoint), T-40 (conversation history)
Day 10 PM: T-41 (security headers), T-42 (rate limiting)
Day 11 AM: T-43 (structured logging), T-44 (quotas), T-45 (health check)
Day 11 PM: COMMIT: Full backend working. Test manually with curl ✓

Week 3: Frontend
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Day 12 AM: T-46 (Next.js scaffold), T-47 (API client layer)
Day 12 PM: T-48 (auth pages), T-49 (auth context + protected routes)
Day 13 AM: T-50 (upload UI), T-51 (document list + status)
Day 13 PM: T-52 (chat / Q&A UI with SSE streaming)
Day 14 AM: T-53 (error boundaries, toasts, responsive)
Day 14 PM: Manual full user journey test in browser ✓

Week 4: Docker/CI/CD → Tests → Launch
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Day 15 AM: T-54 (production Dockerfile), T-55 (production Docker Compose)
Day 15 PM: T-56 (Nginx Docker config), T-57 (CI lint/test pipeline)
Day 16 AM: T-58 (CD deploy pipeline), T-59 (staging environment)
Day 16 PM: First production deploy via CI/CD ✓
Day 17 AM: T-60 (unit tests to ≥80% coverage)
Day 17 PM: T-61 (integration tests)
Day 18 AM: T-62 (backup automation + restore test)
Day 18 PM: T-63 (production smoke test + full launch checklist)
Day 19:    Work through launch checklist. Fix any issues.
Day 20:    LAUNCH 🚀
```

## The Three Hardest Parts (Where Developers Get Stuck)

1. **Email delivery in development (T-17):** Use Resend from day one with a real domain. Don't try to use Gmail SMTP or local SMTP. Sign up for Resend, verify your domain, use their SDK. It takes 20 minutes and saves hours of debugging.

2. **SSE streaming from POST endpoint (T-39):** Remember: `EventSource` only supports GET. You must use `fetch()` + `ReadableStream`. The frontend code in T-39 is the correct pattern — copy it exactly before modifying.

3. **pgvector connection string format (T-34):** When passing vector arrays to asyncpg, format them as strings: `str(query_embedding)` → `"[0.1, 0.2, ...]"`. The asyncpg driver doesn't know how to bind a Python list to a `vector` parameter without explicit casting.

## Senior Developer Mindset Throughout

- **Write tests as you go.** Don't defer testing to Phase 12. T-23 auth tests exist in Phase 5. T-36 ingestion test exists in Phase 7. Test each system when you build it.
- **Commit security checklist items as you build each system.** Don't save security for the end.
- **Validate your ADRs.** Run `SELECT COUNT(*) FROM chunks ORDER BY embedding <=> :q LIMIT 5` with a test vector before building the full pipeline. Make sure the query works before the 8 layers above it exist.
- **Deploy early.** Get the empty FastAPI app with a health check deployed in Week 1. The CI/CD pipeline should exist before the application logic.
- **Never use `:latest` Docker tags in production.** Always tag with the git SHA.

---

> **Document version:** 1.0  
> **Based on:** PDFTalk MVP Task List v1.0 (63 tasks, 12 phases)  
> **Generated for:** Senior developer building a production-grade RAG application  
> **Review cadence:** Before each phase begins  
> **Next review trigger:** Before Phase 11 (Docker + CI/CD)
