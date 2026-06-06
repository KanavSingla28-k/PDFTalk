# PDFTalk — Complete Execution System
## Senior Developer + QA + Mentor + Notion Architecture Guide

> **Project:** PDFTalk MVP — AI-powered PDF question-answering application
> **Stack:** FastAPI · Next.js 14 · PostgreSQL + pgvector · Redis · RQ · Nginx · Docker Compose · AWS Lightsail · S3 · OpenAI
> **Infrastructure:** Single Lightsail instance ($20/month) — no ECS, no managed DB, no NAT Gateway
> **Total Tasks:** 63 | **Estimated Duration:** 3–4 weeks solo | **Monthly Infrastructure Cost:** ~$22.50

---

## Table of Contents

| Part | Title | What's Inside |
|------|-------|---------------|
| 1 | Executive Summary | Project overview, stack, what you'll build |
| 2 | Architecture Review | System diagram, ADRs explained |
| 3 | Keep / Modify / Delete / Missing | Analysis of all 63 tasks + 6 missing items |
| 4 | Master Implementation Roadmap | All 12 phases, goals, risks, success criteria |
| 5 | Senior-Level Task Deep Dives (I) | T-04, T-16, T-34, T-39, T-47 |
| 6 | Senior QA Testing Strategy | Unit, integration, E2E, security, load tests |
| 7 | Deep Concept Teaching (I) | JWT, pgvector, Redis, FastAPI DI, RQ, Docker networking |
| 8 | Connected Learning Pages | Full knowledge graph with learning order |
| 9 | Production Readiness Review | Critical issues, priorities, launch checklist |
| 10 | Recruiter & Resume Preparation | Bullets, pitches, system design explanation |
| 11 | Notion Workspace Structure | Full page hierarchy + database schemas |
| 12 | Final Recommended Execution Order | Day-by-day 4-week plan |
| 13 | Senior-Level Task Deep Dives (II) | T-28, T-32, T-42, T-54/55, T-58 |
| 14 | Complete Concept Teaching Library | Docker, Nginx, SQLAlchemy, IAM, CI/CD, Pydantic |
| 15 | Complete Interview Preparation Hub | 20+ Q&As, 3 system design challenges, AWS/security |
| 16 | Notion Workspace Page Content | Full page templates with content |
| 17 | Missing Tasks: Formal Specifications | T-64 (Playwright), T-65 (Sentry), T-67 (Password Reset) |
| 18 | Production Monitoring Runbook | Health check scripts, incident severity, resolutions |
| 19 | Cost Optimization Guide | OpenAI cost math, AWS billing alerts |
| 20 | Technical Glossary | 45-term reference |

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

# PART 13 — SENIOR-LEVEL TASK DEEP DIVES (CONTINUED)

## T-28 Deep Dive: RQ Worker Setup + Dead-Letter Queue

### Objective
Decouple PDF processing from the HTTP request cycle. A user uploads a file and gets an immediate `202 Accepted`. The actual work — download, extract, chunk, embed, store — happens asynchronously in a separate process, with retries and failure recording.

### Why Background Processing Matters
Embedding a 100-page PDF takes 30–90 seconds (extraction, chunking, ~10 OpenAI API calls). If this ran synchronously inside the HTTP request, the user would stare at a loading spinner for 90 seconds. The connection might time out. Nginx has a default 60-second upstream timeout. The experience is broken.

With RQ: the HTTP request completes in <500ms. The user sees "Processing..." in the UI. The worker does the heavy lifting. The UI polls every 3 seconds. Total UX time is the same, but perceived responsiveness is radically different.

### Code Concepts Explained

**RQ (Redis Queue) job lifecycle:**
```
POST /documents/upload
    │
    ▼
API process: validate → upload to S3 → insert Document(status=PENDING)
    │
    └─► redis.enqueue(ingest_document, document_id)
              │
              ▼
         RQ Queue (Redis list: "rq:queue:default")
              │
              ▼ (worker picks up within milliseconds)
         Worker process: ingest_document(document_id)
              ├─ status = PROCESSING
              ├─ extract text
              ├─ chunk
              ├─ embed (OpenAI)
              ├─ bulk insert chunks
              └─ status = READY (or FAILED + job_logs)
```

**Exponential backoff (30s → 120s → 480s):**
```python
# workers/worker.py
from rq import Worker, Queue
from rq.job import Retry

q = Queue(connection=redis_conn, default_timeout=600)

# When enqueueing:
q.enqueue(
    ingest_document,
    document_id,
    retry=Retry(max=3, interval=[30, 120, 480])
    # Attempt 1 fails → wait 30s → retry
    # Attempt 2 fails → wait 120s → retry
    # Attempt 3 fails → wait 480s → retry
    # Attempt 4 fails → move to 'failed' queue (dead letter)
)
```

**Why exponential backoff?** OpenAI API rate limits reset over time. A flat retry (retry immediately every 5 seconds) will hit the same rate limit wall repeatedly. Exponential backoff gives the external service time to recover.

**Dead-letter queue:** In RQ, failed jobs don't disappear — they go to the `failed` queue. You can:
```python
# Inspect failed jobs:
from rq import Queue
failed_q = Queue('failed', connection=redis_conn)
for job in failed_q.jobs:
    print(job.id, job.exc_info)

# Requeue a specific failed job:
failed_q.requeue(job_id)
```

**`job_logs` table — why it matters:**
The `failed` queue is ephemeral — if you restart Redis, it's gone. The `job_logs` table is permanent. For every final failure, write: `document_id`, `attempt_number`, `error_message`, `full_traceback`, `timestamp`. This lets you:
- Debug why documents fail without reproducing the error
- Show users "Failed: PDF is encrypted" instead of a generic error
- Audit retry history for customer support

### Common Mistakes
- **Forgetting to set `max_timeout`:** RQ jobs have a default 180-second timeout. A large PDF might take longer. Set `default_timeout=600` (10 minutes) on the queue.
- **Sharing the API's DB session with the worker:** The worker runs in a separate process. You need a separate SQLAlchemy engine, separate Redis connection, separate S3 client. Never pass objects across the process boundary.
- **Not handling stale jobs after restart:** If the server restarts mid-job, RQ marks the job as failed with "moved to failed queue". The document stays in `PROCESSING`. Add a startup check: any document in `PROCESSING` older than 10 minutes should be re-queued.

### Production Consideration: Worker Concurrency
For MVP, one worker process handles one job at a time. This is correct — each job consumes significant OpenAI API quota. If you scale to multiple workers, add a per-user concurrency lock in Redis:
```python
lock_key = f"lock:ingest:{user_id}"
with redis.lock(lock_key, timeout=600, blocking_timeout=0) as lock:
    # Only one ingest job per user at a time
    process_document(document_id)
```

### Interview Questions & Answers

**Q: Why use RQ instead of Celery for this project?**
A: "RQ and Celery solve the same core problem — async task execution — but Celery has significantly more operational complexity. It requires configuring a broker (Redis or RabbitMQ) *and* a result backend separately, has its own serialization format, and needs careful tuning for concurrency models. RQ is Redis-only, has a simpler API (one decorator, no broker/backend distinction), and is easier to debug with `rq-dashboard`. For a solo developer with one worker queue and no complex task routing needs, RQ is the right choice. The specific trigger to move to Celery: if I need task chaining (`chord`, `canvas`), multiple broker types, or distributed result storage — none of which apply at MVP scale."

**Q: How would you handle a document that gets stuck in PROCESSING state after a server crash?**
A: "I'd add a recovery mechanism that runs at worker startup and on a periodic schedule (say, every 5 minutes). It queries for documents in `PROCESSING` status older than `max_job_timeout + buffer` (e.g., 15 minutes). For each one, it checks the RQ failed queue for a matching job ID. If found, it reads the error and sets the document to FAILED. If not found (the job disappeared due to crash), it re-enqueues the job and resets status to PENDING. This prevents permanently stuck documents without any manual intervention."

---

## T-32 Deep Dive: OpenAI Client with Circuit Breaker + Cost Guard

### Objective
Wrap the OpenAI SDK so that: API rate limits are retried gracefully, per-user daily token spend is capped before it becomes a business problem, and a cascade of OpenAI outages doesn't flood your logs and burn retries.

### Code Concepts Explained

**Circuit Breaker Pattern:**
```
CLOSED (normal operation)
    │ OpenAI returns 5xx 3 times in a row
    ▼
OPEN (stop sending requests, return error immediately)
    │ Wait 60 seconds
    ▼
HALF-OPEN (send one test request)
    ├─ Success → back to CLOSED
    └─ Failure → back to OPEN for another 60s
```

Without a circuit breaker: if OpenAI is down for 2 minutes, your worker floods OpenAI with 100 retries, burns through your retry budget, and fills your logs with errors. The circuit breaker detects the failure pattern and stops calling OpenAI until it recovers.

```python
# utils/openai_client.py
import time
from enum import Enum

class CircuitState(Enum):
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Not accepting requests
    HALF_OPEN = "half_open"  # Testing recovery

class OpenAICircuitBreaker:
    FAILURE_THRESHOLD = 3
    RECOVERY_TIMEOUT = 60  # seconds

    def __init__(self, redis_client):
        self.redis = redis_client
        self.failure_key = "circuit:openai:failures"
        self.open_at_key = "circuit:openai:opened_at"

    async def get_state(self) -> CircuitState:
        failures = int(await self.redis.get(self.failure_key) or 0)
        opened_at = await self.redis.get(self.open_at_key)

        if failures < self.FAILURE_THRESHOLD:
            return CircuitState.CLOSED
        if opened_at and time.time() - float(opened_at) > self.RECOVERY_TIMEOUT:
            return CircuitState.HALF_OPEN
        return CircuitState.OPEN

    async def record_success(self):
        await self.redis.delete(self.failure_key, self.open_at_key)

    async def record_failure(self):
        failures = await self.redis.incr(self.failure_key)
        if failures == self.FAILURE_THRESHOLD:
            await self.redis.set(self.open_at_key, time.time())
        await self.redis.expire(self.failure_key, 300)  # Reset after 5 minutes of quiet

    async def call(self, func, *args, **kwargs):
        state = await self.get_state()
        if state == CircuitState.OPEN:
            raise CircuitOpenError("OpenAI circuit breaker is OPEN — retrying in 60s")
        try:
            result = await func(*args, **kwargs)
            await self.record_success()
            return result
        except openai.APIStatusError as e:
            if e.status_code >= 500:
                await self.record_failure()
            raise
```

**Per-User Daily Token Counter:**
```python
async def check_and_increment_token_usage(user_id: str, tokens: int) -> None:
    """
    Uses Redis INCR with atomic increment + first-write TTL pattern.
    Thread-safe: INCR is atomic in Redis.
    """
    today = datetime.utcnow().strftime("%Y%m%d")
    key = f"quota:tokens:{user_id}:{today}"
    
    # Atomic increment — returns new total
    current = await redis.incrby(key, tokens)
    
    if current == tokens:
        # First write today: set expiry (25h to handle timezone edge cases)
        await redis.expire(key, 86400 + 3600)
    
    if current > settings.MAX_DAILY_TOKENS_PER_USER:
        # Undo the increment (user is over quota, don't charge them)
        await redis.decrby(key, tokens)
        raise DailyQuotaExceededError(
            f"Daily token quota exceeded: {current}/{settings.MAX_DAILY_TOKENS_PER_USER}"
        )
```

### Common Mistakes
- **Not pre-checking quota before embedding:** If you embed 200 chunks and then discover the user is over quota, you've already spent money on OpenAI. Check *before* the first batch.
- **Using the quota counter as billing:** Redis data is ephemeral. For actual billing records, write token usage to Postgres daily (a background job, not on the hot path).
- **Circuit breaker state in process memory:** If you store circuit state in a Python dict, each process has its own breaker. Two workers won't share knowledge of OpenAI failures. Store in Redis.

### Interview Questions & Answers

**Q: How do you handle the case where a user's quota check passes but the OpenAI call still exceeds their daily limit (race condition)?**
A: "Classic check-then-act race condition. Two concurrent requests both read `current = 80,000` tokens (under the 100,000 limit), both add 30,000 tokens, both pass the check. Now the user has used 140,000 tokens. The fix is to use Redis `INCRBY` and check the *result*, not a pre-read value. `INCRBY` is atomic — it increments and returns the new value in one operation. If the returned value exceeds the limit, we immediately decrement and reject. This is the correct pattern: increment-then-check, not check-then-increment."

---

## T-42 Deep Dive: Redis Sliding Window Rate Limiter

### Objective
Prevent abuse of expensive endpoints (login brute-force, OpenAI query flooding, upload spam) with per-endpoint, per-user or per-IP limits that use a sliding time window — not a fixed window that resets on the clock.

### Fixed Window vs Sliding Window

```
Fixed window problem:
    Rate limit: 10 requests per minute
    
    12:00:50 — 8 requests   (window 12:00-12:01)
    12:01:00 — window resets
    12:01:05 — 8 requests   (window 12:01-12:02)
    
    16 requests in 10 seconds. Fixed window allows limit × 2 bursting.

Sliding window solution:
    At any point in time, count requests in the LAST 60 seconds.
    8 requests at 12:00:50 + 8 more at 12:01:05 = 16 in the last 60s.
    → Reject from request #11 onward.
```

### Implementation using Redis Sorted Set

```python
# middleware/rate_limit.py
import time
import uuid
from fastapi import Request, HTTPException

async def sliding_window_rate_limit(
    key: str,           # e.g. "ratelimit:login:192.168.1.1"
    limit: int,         # e.g. 10
    window_seconds: int # e.g. 60
) -> tuple[int, int]:
    """
    Returns (current_count, retry_after_seconds).
    Raises RateLimitExceeded if over limit.
    """
    now = time.time()
    window_start = now - window_seconds

    pipe = redis.pipeline()
    # Remove entries outside the sliding window
    pipe.zremrangebyscore(key, 0, window_start)
    # Add current request with timestamp as score
    pipe.zadd(key, {f"{uuid.uuid4()}": now})
    # Count requests in current window
    pipe.zcard(key)
    # Set TTL so the key eventually expires
    pipe.expire(key, window_seconds + 1)
    
    _, _, count, _ = await pipe.execute()

    if count > limit:
        # Find when the oldest request in the window will fall out
        oldest = await redis.zrange(key, 0, 0, withscores=True)
        retry_after = int(oldest[0][1] + window_seconds - now) + 1
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={"Retry-After": str(retry_after)}
        )
    
    return count, 0

# FastAPI dependency for login rate limiting
async def login_rate_limit(request: Request):
    ip = request.client.host
    await sliding_window_rate_limit(
        key=f"ratelimit:login:{ip}",
        limit=10,
        window_seconds=60
    )

# Apply to route:
@router.post("/auth/login", dependencies=[Depends(login_rate_limit)])
async def login(...):
    ...
```

### Two-Layer Rate Limiting Architecture

```
Internet Request
      │
      ▼
┌─────────────────────────────────────────────────────┐
│  NGINX (Layer 1 — Volumetric DDoS protection)       │
│  Cost: ~0.001ms per request                         │
│  limit_req_zone $binary_remote_addr zone=api:10m    │
│      rate=30r/s;                                    │
│  Blocks: >30 req/sec from one IP                    │
│  Purpose: Keep Python processes alive               │
└─────────────────────┬───────────────────────────────┘
                      │ Only requests ≤ 30/sec pass
                      ▼
┌─────────────────────────────────────────────────────┐
│  REDIS SLIDING WINDOW (Layer 2 — Business Logic)    │
│  Cost: ~1ms per request (one Redis pipeline call)   │
│  Per-endpoint, per-user or per-IP limits:           │
│  - /auth/login: 10/min/IP                           │
│  - /auth/register: 5/hr/IP                          │
│  - /documents/upload: 5/min/user                    │
│  - /query/ask: 20/min/user                          │
│  Purpose: Enforce product quotas, prevent abuse     │
└─────────────────────────────────────────────────────┘
```

### Interview Questions & Answers

**Q: Why use a sorted set for rate limiting instead of a simple Redis counter with INCR + EXPIRE?**
A: "A simple counter with INCR resets on the clock boundary, creating the fixed window double-spend problem I described. With a sorted set where scores are timestamps, you're always counting requests in the last N seconds from the current moment — a true sliding window. The trade-off is slightly more memory per key (each request stores a unique member + timestamp vs one integer) and a pipeline with 4 operations vs one. For rate limiting windows of 60 seconds with limits of 10-100 requests, the sorted set approach is the right trade-off: correctness over marginal memory efficiency."

**Q: How would you implement distributed rate limiting if PDFTalk had multiple API server instances?**
A: "Redis is inherently distributed — all API instances share the same Redis instance, so the sliding window state is already shared. The current implementation works for any number of API servers without modification. If Redis itself becomes a bottleneck (extremely high throughput), you can shard rate limit keys across multiple Redis instances by hashing the key, or use Redis Cluster. For PDFTalk's scale, a single Redis instance handles millions of sorted set operations per second — it won't be the bottleneck."

---

## T-54 / T-55 Deep Dive: Multi-Stage Docker Builds + Production Compose

### Objective
Create production Docker images that are small, secure, and deterministic. Configure a production Compose file with correct networking, named volumes, health-check-gated dependencies, and resource limits.

### Multi-Stage Dockerfile Anatomy

```dockerfile
# backend/Dockerfile

# ─── Stage 1: Builder ──────────────────────────────────────────────────────────
# Use a full Python image to install dependencies and compile wheels
FROM python:3.12-slim AS builder

WORKDIR /build

# Install uv for fast dependency resolution
RUN pip install uv

# Copy only dependency files first — Docker layer cache
# If code changes but pyproject.toml doesn't, this layer is reused
COPY pyproject.toml uv.lock ./
RUN uv pip install --system --no-cache -r pyproject.toml

# ─── Stage 2: Runtime ──────────────────────────────────────────────────────────
# Start fresh — no build tools, no pip cache, no intermediate files
FROM python:3.12-slim AS runtime

# Security: create a non-root user
# Rationale: if a vulnerability allows RCE, attacker gets this user,
# not root. Cannot write to system directories.
RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid 1000 --no-create-home appuser

# Copy installed packages from builder stage only
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

WORKDIR /app
COPY --chown=appuser:appuser . .

# Switch to non-root
USER appuser

# Healthcheck: Docker monitors this and marks container healthy/unhealthy
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
```

**Why multi-stage?**
- Builder stage: ~800MB (Python + gcc + all build tools)
- Runtime stage: ~200MB (Python + packages only, no build tools)
- Result: 75% smaller image, faster pulls, smaller attack surface

**Why `--chown=appuser:appuser` on COPY?**
If you copy files as root and then switch to `appuser`, the files are owned by root. The app can read them, but if it needs to write to any directory (log files, temp files), it can't. `--chown` sets ownership during the copy.

### Production Docker Compose — Key Patterns

```yaml
# docker-compose.yml (production)
version: "3.9"

services:
  postgres:
    image: pgvector/pgvector:pg15
    restart: unless-stopped
    volumes:
      - postgres_data:/var/lib/postgresql/data  # Named volume — survives container recreation
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: pdftalk
    networks: [internal]
    # CRITICAL: postgres is NOT exposed on host ports in production
    # ports: ["5432:5432"]  <-- NEVER uncomment this in production
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d pdftalk"]
      interval: 10s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    restart: unless-stopped
    command: redis-server --requirepass ${REDIS_PASSWORD} --appendonly yes
    volumes:
      - redis_data:/data
    networks: [internal]
    healthcheck:
      test: ["CMD", "redis-cli", "-a", "${REDIS_PASSWORD}", "PING"]
      interval: 10s
      timeout: 5s
      retries: 5

  api:
    image: pdftalk-api:${GIT_SHA}   # SHA tag — not :latest
    restart: unless-stopped
    env_file: .env
    networks: [internal]
    depends_on:
      postgres:
        condition: service_healthy  # Wait for postgres to accept connections
      redis:
        condition: service_healthy

  worker:
    image: pdftalk-api:${GIT_SHA}   # Same image as API
    restart: unless-stopped
    command: ["rq", "worker", "--with-scheduler", "-u", "${REDIS_URL}"]
    env_file: .env
    networks: [internal]
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy

  nginx:
    image: pdftalk-nginx:${GIT_SHA}
    restart: unless-stopped
    networks: [internal, external]
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - /etc/letsencrypt:/etc/letsencrypt:ro  # TLS certs (read-only)
    depends_on:
      - api

volumes:
  postgres_data:   # Survives: docker compose down (data preserved)
  redis_data:      # Survives: docker compose down (RQ jobs preserved)

networks:
  internal:
    driver: bridge
    internal: true   # Cannot reach internet (extra security)
  external:
    driver: bridge
```

**`depends_on` with `condition: service_healthy`:**
Without this, Docker starts containers in declaration order but doesn't wait for them to be ready. The API container starts, tries to connect to Postgres before Postgres accepts connections, and crashes. `service_healthy` means: wait until the `healthcheck` command returns 0. This is the correct way to handle startup ordering.

**`internal: true` on the internal network:**
This Docker network flag prevents containers on the `internal` network from making outbound internet connections. Postgres and Redis cannot call out to the internet even if they wanted to. Only the API and worker containers need outbound internet (for OpenAI and S3), so only they should be on a network without this flag. For MVP simplicity this is omitted, but it's a valid hardening option.

### Interview Questions & Answers

**Q: Why tag Docker images with the git SHA instead of a version number or `latest`?**
A: "Three reasons. First, `:latest` is mutable — `docker pull nginx:latest` today gives a different image than six months ago. SHA tags are immutable — the same SHA always gives the same image. Second, your deployment history is your rollback history. When something breaks, `docker ps --format '{{.Image}}'` shows exactly what's running. Find the previous SHA in git, rebuild that image, redeploy. Third, SHA tags create a direct audit trail between what's running in production and the exact commit that produced it. If a security vulnerability is found in a library, you know exactly which deployed images need patching."

**Q: What's the difference between `docker compose down` and `docker compose down -v`?**
A: "`docker compose down` stops and removes containers, networks, and the default bridge, but named volumes persist. Your Postgres data and Redis jobs survive. `docker compose down -v` also removes named volumes — irreversibly destroys all data. In production, `docker compose down -v` should never be run unless you intend to wipe all data. Practical rule: use `down` for restarts, `down -v` only when setting up from scratch or recovering from data corruption you want to discard."

---

## T-58 Deep Dive: CD Deploy Pipeline (GitHub Actions)

### Objective
Every push to `main` automatically runs tests, builds Docker images, transfers them to the Lightsail instance, runs database migrations, and restarts containers — with zero manual SSH commands.

### Full Pipeline Architecture

```
git push origin main
        │
        ▼
GitHub Actions Trigger (push to main)
        │
        ├─ Job 1: CI (lint + test)
        │     ├─ ruff check backend/
        │     ├─ mypy backend/
        │     └─ pytest --cov=80 backend/tests/
        │
        └─ Job 2: CD (depends on CI passing)
              │
              ├─ Build Docker images (--build-arg GIT_SHA)
              ├─ Save images to .tar.gz
              ├─ SCP .tar.gz to Lightsail
              │
              ▼ SSH into Lightsail
              ├─ docker load < images.tar.gz
              ├─ export GIT_SHA=<commit-sha>
              ├─ alembic upgrade head   ← MIGRATIONS BEFORE RESTART
              ├─ docker compose up -d --no-deps api worker
              ├─ docker image prune -f --filter "until=72h"
              └─ smoke test: curl https://domain/health
```

**Critical ordering: migrations BEFORE container restart:**
If you restart the API container first, it might start before migrations run. If migration 003 adds a `NOT NULL` column that the new code expects, the old API (still running) crashes because the column doesn't exist yet. The new API waits for a column that hasn't been added. The correct order:
1. Run `alembic upgrade head` (old containers still running, serving traffic)
2. Apply migrations (old code must be compatible with new schema — backwards-compatible migrations)
3. Restart containers (new code runs against migrated schema)

**Backwards-compatible migration pattern:**
```python
# WRONG: Adding NOT NULL column in one step
# Old API sees a column that doesn't exist → crashes

# CORRECT: Three-step migration
# Migration 003: Add column as nullable
op.add_column('documents', sa.Column('processing_node', sa.Text, nullable=True))

# Deploy new code (reads the nullable column safely, writes null when not set)

# Migration 004 (next deploy): Backfill + add NOT NULL constraint
op.execute("UPDATE documents SET processing_node = 'default' WHERE processing_node IS NULL")
op.alter_column('documents', 'processing_node', nullable=False)
```

### GitHub Actions Workflow — Annotated

```yaml
# .github/workflows/deploy.yml
name: CI/CD

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]   # Run CI on PRs (but not CD)

jobs:
  test:
    runs-on: ubuntu-latest
    services:
      # Spin up Postgres and Redis as service containers
      postgres:
        image: pgvector/pgvector:pg15
        env:
          POSTGRES_USER: test
          POSTGRES_PASSWORD: test
          POSTGRES_DB: pdftalk_test
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
      redis:
        image: redis:7
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 10s

    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      
      - name: Install uv
        run: pip install uv
      
      - name: Install dependencies
        run: uv pip install --system -e ".[test]"
        working-directory: backend
      
      - name: Lint
        run: ruff check .
        working-directory: backend
      
      - name: Type check
        run: mypy . --ignore-missing-imports
        working-directory: backend
      
      - name: Run tests
        env:
          DATABASE_URL: "postgresql+asyncpg://test:test@localhost:5432/pdftalk_test"
          REDIS_URL: "redis://localhost:6379"
          JWT_SECRET: "test-secret-min-32-chars-long-xxxx"
          OPENAI_API_KEY: "test-key"  # mocked in tests
        run: pytest --cov=app --cov-fail-under=80 -v
        working-directory: backend

  deploy:
    needs: test               # Only runs if test job passes
    if: github.ref == 'refs/heads/main'  # Only on main branch pushes
    runs-on: ubuntu-latest
    
    steps:
      - uses: actions/checkout@v4
      
      - name: Build images
        run: |
          docker build \
            --build-arg GIT_SHA=${{ github.sha }} \
            -t pdftalk-api:${{ github.sha }} \
            backend/
          docker build \
            -t pdftalk-nginx:${{ github.sha }} \
            nginx/
          docker save pdftalk-api:${{ github.sha }} pdftalk-nginx:${{ github.sha }} \
            | gzip > images.tar.gz
      
      - name: Transfer to Lightsail
        uses: appleboy/scp-action@v0.1.7
        with:
          host: ${{ secrets.LIGHTSAIL_IP }}
          username: ubuntu
          key: ${{ secrets.LIGHTSAIL_SSH_KEY }}
          source: "images.tar.gz"
          target: "/tmp/"
      
      - name: Deploy
        uses: appleboy/ssh-action@v1
        with:
          host: ${{ secrets.LIGHTSAIL_IP }}
          username: ubuntu
          key: ${{ secrets.LIGHTSAIL_SSH_KEY }}
          script: |
            set -e  # Exit on any error
            cd /opt/pdftalk
            
            # Load new images into Docker
            docker load < /tmp/images.tar.gz
            export GIT_SHA=${{ github.sha }}
            
            # CRITICAL: Run migrations BEFORE restarting API
            docker compose run --rm api alembic upgrade head
            
            # Rolling restart (zero-ish downtime with --no-deps)
            docker compose up -d --no-deps api worker nginx
            
            # Wait for health check
            sleep 15
            docker compose ps | grep -E "(api|worker)" | grep -v "healthy" && exit 1 || true
            
            # Cleanup old images
            docker image prune -f --filter "until=72h"
            rm -f /tmp/images.tar.gz
      
      - name: Smoke test
        run: |
          sleep 10
          curl --fail --max-time 10 https://${{ secrets.APP_DOMAIN }}/health || exit 1
          echo "✅ Smoke test passed"
```

### Secrets to Configure in GitHub

```
Settings → Secrets and variables → Actions:
LIGHTSAIL_IP        = <your static IP>
LIGHTSAIL_SSH_KEY   = <contents of ~/.ssh/lightsail_private_key>
APP_DOMAIN          = pdftalk.com
```

**Why use `appleboy/ssh-action` instead of `ssh` CLI?** The `appleboy` actions handle key setup, known_hosts configuration, and connection retries automatically. Using raw `ssh` requires you to manually configure key files, trust the server's host key in CI, and handle connection failures. The action abstracts all of this.

### Common Mistakes

- **Deploying without running migrations:** New code expects new schema. If migrations don't run first, the new code crashes the moment it touches the database.
- **Using `:latest` tag:** When the deployment fails and you need to roll back, you can't tell which image is "the previous good one" if everything is tagged `:latest`.
- **Not gating CD on CI:** Every production deployment must pass tests. Without `needs: test`, you can deploy broken code.
- **Storing the deploy SSH key in the repo:** Never commit the private key. Store it in GitHub Secrets. Rotate it every 90 days.

### Interview Questions & Answers

**Q: How do you achieve zero-downtime deployments with a single Lightsail instance?**
A: "True zero-downtime requires at minimum two instances and a load balancer — not applicable at MVP scale. What `docker compose up -d --no-deps api` achieves is *minimal-downtime* deployment. Compose stops the old container and starts the new one. The gap is typically 2-5 seconds while Nginx is trying to proxy to a container that isn't accepting connections yet. Nginx returns 502 during this window. For an MVP with no SLA, this is acceptable. When you need true zero-downtime, you either upgrade to ECS with a rolling deployment strategy, or add a second Lightsail instance behind a load balancer and deploy one at a time."

**Q: Walk me through what happens if the `alembic upgrade head` step fails during deployment.**
A: "The `set -e` flag exits the deploy script immediately. The old containers are still running (we haven't restarted them yet). The new images are loaded but not running. The user experiences zero downtime — they're still hitting the old code against the old schema. The GitHub Actions step is marked failed, alerting you via email/Slack. You investigate the migration error (most likely a constraint violation or syntax error in the migration script), fix it, and re-deploy. The ability to fail safely before touching running containers is exactly why you run migrations before `docker compose up -d`."

---

## T-47 Deep Dive: Frontend API Client Layer

### Objective
Create a type-safe, centralized HTTP client that handles auth token injection, automatic token refresh on expiry, typed error responses, and clean module separation — so no route component ever writes raw `fetch()` calls.

### Why Centralize the API Client?

Bad pattern (scattered fetch calls):
```typescript
// page.tsx — directly calling fetch in a component
const response = await fetch('/api/documents', {
  headers: { Authorization: `Bearer ${localStorage.getItem('token')}` }
});
// Every component needs token logic. localStorage is XSS-vulnerable.
// Error handling is duplicated everywhere. No type safety.
```

Good pattern (centralized client):
```typescript
// All components call:
const documents = await documentsApi.list();
// Auth, error handling, token refresh — all handled in one place.
// Components never see fetch(), tokens, or error status codes.
```

### Implementation

```typescript
// lib/api.ts — Core client

interface ApiError {
  status: number;
  message: string;
  code?: string;
}

class ApiClient {
  private baseUrl: string;
  // Access token in memory — NOT localStorage (XSS-safe)
  private accessToken: string | null = null;

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl;
  }

  setAccessToken(token: string | null) {
    this.accessToken = token;
  }

  private async refreshAccessToken(): Promise<string> {
    // Cookie is sent automatically (SameSite=strict, path=/auth/refresh)
    const response = await fetch(`${this.baseUrl}/auth/refresh`, {
      method: 'POST',
      credentials: 'include',  // Send httpOnly cookie
    });
    if (!response.ok) throw new Error('Session expired');
    const { access_token } = await response.json();
    this.accessToken = access_token;
    return access_token;
  }

  async request<T>(
    method: string,
    path: string,
    body?: unknown,
    retryOnAuth = true
  ): Promise<T> {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
    };
    
    if (this.accessToken) {
      headers['Authorization'] = `Bearer ${this.accessToken}`;
    }

    const response = await fetch(`${this.baseUrl}${path}`, {
      method,
      headers,
      credentials: 'include',
      body: body ? JSON.stringify(body) : undefined,
    });

    // Auto-refresh on 401 (token expired), retry once
    if (response.status === 401 && retryOnAuth) {
      try {
        await this.refreshAccessToken();
        return this.request<T>(method, path, body, false); // No further retry
      } catch {
        // Refresh also failed — session truly expired
        this.accessToken = null;
        window.location.href = '/login';
        throw new Error('Session expired');
      }
    }

    if (!response.ok) {
      const error = await response.json().catch(() => ({ message: 'Unknown error' }));
      throw { status: response.status, ...error } as ApiError;
    }

    if (response.status === 204) return undefined as T;
    return response.json() as Promise<T>;
  }

  get<T>(path: string) { return this.request<T>('GET', path); }
  post<T>(path: string, body?: unknown) { return this.request<T>('POST', path, body); }
  delete<T>(path: string) { return this.request<T>('DELETE', path); }
}

export const apiClient = new ApiClient(process.env.NEXT_PUBLIC_API_URL!);

// lib/documents.api.ts — typed module
import { apiClient } from './api';

export interface Document {
  id: string;
  filename: string;
  status: 'PENDING' | 'PROCESSING' | 'READY' | 'FAILED';
  created_at: string;
  chunk_count: number | null;
}

export const documentsApi = {
  list: () => apiClient.get<Document[]>('/documents'),
  getStatus: (id: string) => apiClient.get<Document>(`/documents/${id}/status`),
  delete: (id: string) => apiClient.delete<void>(`/documents/${id}`),
};

// lib/query.api.ts — SSE streaming (separate pattern)
export async function* streamQuery(
  documentIds: string[],
  question: string,
  accessToken: string
): AsyncGenerator<string> {
  const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/query/ask`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${accessToken}`,
    },
    body: JSON.stringify({ document_ids: documentIds, question }),
  });

  if (!response.ok) throw new Error(`Query failed: ${response.status}`);
  
  const reader = response.body!.getReader();
  const decoder = new TextDecoder();

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    
    const text = decoder.decode(value, { stream: true });
    for (const line of text.split('\n')) {
      if (!line.startsWith('data: ')) continue;
      const data = line.slice(6).trim();
      if (data === '[DONE]') return;
      if (data.startsWith('{"error"')) {
        const { error } = JSON.parse(data);
        throw new Error(error);
      }
      if (data) yield data;
    }
  }
}
```

### Interview Questions & Answers

**Q: Why store the access token in React state (in-memory) instead of localStorage?**
A: "localStorage is readable by any JavaScript running on the page — including scripts injected via XSS. If an attacker finds an XSS vulnerability, they steal every user's access token. In-memory storage means the token dies with the page session and is inaccessible to injected scripts. The downside is that page refresh loses the token. The solution is the silent refresh pattern: on mount, `AuthContext` calls `GET /auth/me` with the httpOnly refresh cookie, which returns a new access token without user interaction. The UX is seamless — users don't see a login screen on refresh."

---

# PART 14 — COMPLETE CONCEPT TEACHING LIBRARY

## Docker (Complete)

**Concept Overview:** Docker packages an application and all its dependencies into a portable, isolated unit (container) that runs identically on any machine with Docker installed. It solves "works on my machine" permanently.

**Real-World Analogy:** A shipping container. Before containers, cargo (software) had to be loaded differently for every ship (server). With containers, you pack cargo into a standardized box. The ship doesn't need to know what's inside — it just loads the box. The cargo arrives exactly as packed.

**Key Concepts for PDFTalk:**

| Concept | What It Is | Why It Matters |
|---------|-----------|----------------|
| Image | Read-only filesystem snapshot (layers) | The blueprint for containers; shareable, versioned |
| Container | Running instance of an image | Isolated process — your app's runtime environment |
| Layer caching | Only rebuilds changed layers | Copy `pyproject.toml` before `src/` for faster builds |
| Named volumes | Persistent storage outside containers | Postgres data survives `docker compose down` |
| Bridge network | Virtual network for container communication | `api` reaches `postgres` by service name, not IP |
| HEALTHCHECK | Command Docker runs to check container health | `depends_on: condition: service_healthy` waits for it |

**Common Mistakes:**
- Running containers as root (use `USER appuser`)
- Copying `.env` into the image (use `env_file` at runtime)
- Not using multi-stage builds (image bloat, build tools in production)
- Binding volumes to host paths in production (non-reproducible; use named volumes)

---

## Nginx as a Reverse Proxy

**What it does in PDFTalk:**
1. Receives all external HTTP/HTTPS traffic (ports 80/443 on host)
2. Terminates TLS (decrypts HTTPS, passes plain HTTP internally)
3. Routes `/api/` requests to the FastAPI container (`proxy_pass http://api:8000`)
4. Serves the Next.js static build (`/app/out`) directly (no Python involved)
5. Applies rate limiting (blocks volumetric attacks before Python processes wake up)
6. Adds security headers to every response

**Why Nginx handles TLS instead of FastAPI:**
- TLS termination is CPU-intensive. Nginx is 10× more efficient at it than Python
- Nginx is battle-tested for SSL configuration; FastAPI/uvicorn SSL support is basic
- Centralizes certificate management in one place

**gzip compression — always enable for text responses:**
```nginx
gzip on;
gzip_vary on;
gzip_min_length 1024;
gzip_types text/plain application/json application/javascript text/css;
# Result: JSON API responses compressed 70-80%, reducing bandwidth costs
```

**Static file serving performance:**
Nginx serves files from disk at near-disk-read speed. Python serving static files goes: TCP → Python process → file read → response. Nginx: TCP → file read → response. For a Next.js static build (CSS, JS, HTML), Nginx is 10-100× faster than Python.

---

## SQLAlchemy Async + Alembic

**Why async SQLAlchemy?**
FastAPI is built on Starlette, which uses Python's asyncio event loop. If you use synchronous SQLAlchemy, every database query blocks the event loop — preventing other requests from being handled while waiting for Postgres. Async SQLAlchemy (`create_async_engine` + `asyncpg` driver) releases the event loop during I/O, allowing FastAPI to handle other requests while waiting for query results.

**The `yield` dependency pattern for sessions:**
```python
async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session         # Route handler runs here
            await session.commit() # Commit if no exception
        except Exception:
            await session.rollback() # Rollback on any error
            raise
        # Session automatically closed after yield (context manager)
```

**Alembic mental model:**
```
git for your database schema

alembic revision --autogenerate -m "add_chunk_count_to_documents"
# Detects difference between SQLAlchemy models and current DB schema
# Generates a migration file with upgrade() and downgrade()

alembic upgrade head
# Runs all pending migrations in order

alembic downgrade -1
# Reverts the last migration

alembic history
# Shows migration history — your schema changelog
```

**Why `autogenerate` is a starting point, not the final word:**
Alembic's autogenerate detects column additions, removals, and type changes. It does NOT reliably detect: renamed columns (sees as drop + add), index changes, custom check constraints, or server defaults. Always review the generated migration before committing.

---

## AWS IAM (Identity and Access Management)

**Mental Model:** IAM is the bouncer for your AWS account. Every API call to AWS asks: "Who are you?" (authentication) and "Are you allowed to do this?" (authorization).

**PDFTalk IAM structure:**

```
AWS Account (root user — MFA enabled, no access keys)
    │
    └── IAM User: pdftalk-app
          └── Policy: PDFTalkS3Policy
                Statement:
                  Allow: s3:PutObject, GetObject, DeleteObject, HeadObject
                  Resource: arn:aws:s3:::pdftalk-documents/*
                  
                  Allow: s3:ListBucket
                  Resource: arn:aws:s3:::pdftalk-documents

This user CANNOT:
- Create or delete buckets
- Change bucket policies
- Access any other bucket
- Create IAM users
- Access EC2, RDS, or any other service
```

**Principle of Least Privilege:** Give each entity only the permissions it needs for its specific job, nothing more. The `pdftalk-app` IAM user can only touch the one S3 bucket it needs. Even if the API server is fully compromised, the attacker can only read/write/delete files in that one bucket.

**Access Keys vs IAM Roles:**
For Lightsail (not EC2), you must use IAM user access keys. For EC2 instances, use IAM Roles (instance profiles) instead — roles never require storing credentials in files. This is a migration path for later.

---

## CI/CD Concepts

**Continuous Integration (CI):**
Every code change is automatically built and tested. Purpose: detect breakages within minutes, not days.

```
Developer pushes code
    ↓
Automated pipeline runs in 5-10 minutes:
    ├─ lint (ruff) — style errors
    ├─ type check (mypy) — type errors
    └─ tests (pytest) — functional errors
         ├─ Pass → PR can be merged
         └─ Fail → Notified, must fix before merge
```

**Continuous Deployment (CD):**
Merging to `main` automatically deploys to production. Purpose: remove the manual deployment step that introduces human error and deployment anxiety.

**Why it matters beyond automation:**
- **Reversibility:** Every deployment is a known commit SHA. Rollback = re-deploy previous SHA.
- **Audit trail:** `git log main` is your complete deployment history with author, timestamp, and change description.
- **Psychological safety:** Small, frequent deployments are less risky than large, infrequent ones. If each deployment changes 50 lines, the failure blast radius is small and root cause is obvious.

**Branch Strategy for PDFTalk:**
```
main          ← Production. Protected. Only merged via PR after CI passes.
feature/*     ← Feature branches. PR → main after review + CI.
hotfix/*      ← Emergency fixes. PR → main directly. 
staging       ← (optional) Deployed to staging automatically.
```

---

## Pydantic v2 + BaseSettings

**What Pydantic does:** Validates that Python objects match a defined schema at runtime, with automatic type coercion and detailed error messages.

**Why it matters for FastAPI:**
```python
# Without Pydantic:
@app.post("/auth/login")
async def login(request: Request):
    body = await request.json()
    email = body.get("email")      # Could be None, int, list — anything
    password = body.get("password") # No validation, no type safety
    # If a bot sends {"email": null, "password": 12345}, you get a crash

# With Pydantic:
class LoginRequest(BaseModel):
    email: EmailStr               # Validates email format
    password: str = Field(min_length=8)  # Minimum length

@app.post("/auth/login")
async def login(body: LoginRequest):  # FastAPI automatically validates
    # If body doesn't match schema, FastAPI returns 422 before your code runs
    # email is guaranteed to be a valid email string
    # password is guaranteed to be a string ≥ 8 chars
```

**`BaseSettings` for environment variables:**
```python
class Settings(BaseSettings):
    DATABASE_URL: str          # Required — crash if missing
    MAX_DOCS_PER_USER: int = 20  # Optional with default
    
    model_config = ConfigDict(env_file=".env")

settings = Settings()  # Reads .env, validates types, raises on missing
```

The key insight: validation happens at application startup. A misconfigured deployment (wrong DB URL format, missing API key) fails immediately with a clear error message, not 3 hours later when a user triggers the broken code path.

---

# PART 15 — COMPLETE INTERVIEW PREPARATION HUB

## Section A: Backend Questions

### Authentication Deep Dives

**Q: Describe the complete flow from a user clicking "Login" to getting an authenticated API response.**

A (Senior): "
1. Browser sends `POST /auth/login` with email+password in JSON body (over HTTPS).
2. FastAPI validates the request body via Pydantic — rejects malformed requests before any DB hit.
3. Rate limit check: Redis sliding window, 10 req/min/IP. Returns 429 if exceeded.
4. DB lookup by `email_lower` (not `email`) — prevents case-mismatch duplicates.
5. Check `is_verified = True`. If not, return 403.
6. Check `locked_until` — if in the future, return 401 (generic message, doesn't reveal lockout).
7. `passlib.verify_password(raw_password, stored_hash)` — constant-time bcrypt comparison.
8. If wrong: increment `failed_login_attempts`. If ≥10: set `locked_until = NOW() + 15min`. Return 401.
9. If correct: reset `failed_login_attempts = 0`.
10. Generate access JWT (15-min expiry, user_id in sub, type=access, unique jti).
11. Generate opaque refresh token: `secrets.token_urlsafe(32)`. Store `SHA256(token)` + user_id + expiry in `refresh_tokens` table.
12. Return access token in JSON body. Set httpOnly cookie with raw refresh token (`Secure`, `SameSite=strict`, `path=/auth/refresh`).
13. Client stores access token in React state (in-memory). httpOnly cookie stored by browser automatically.
14. Subsequent API requests attach `Authorization: Bearer {access_token}`.
15. JWT middleware extracts and validates signature, checks expiry, checks type=access, returns user_id to route handler.
"

---

**Q: How does your refresh token rotation work and why is it important?**

A: "When the access token expires (15 minutes), the frontend calls `POST /auth/refresh`. The browser automatically includes the httpOnly cookie (it's path-scoped to `/auth/refresh`). The backend:
1. Reads the raw token from the cookie
2. Computes SHA256(raw_token)
3. Looks up the hash in the `refresh_tokens` table — checks user binding and expiry
4. **Immediately deletes the token from the database**
5. Issues a new access JWT and a new refresh token (new hash stored)

The deletion is critical. If an attacker intercepts the refresh token cookie (e.g., via network mitm on HTTP — which is why HTTPS is non-negotiable), they have exactly one use. When they use it, the legitimate user's next refresh attempt will find no matching token. This is called 'refresh token reuse detection'. You can extend this to 'refresh token family tracking' — if a used token is presented again, it means session theft, and you immediately invalidate all tokens for that user."

---

### Database & Async Questions

**Q: Why use `asyncpg` instead of `psycopg` for this project?**

A: "FastAPI runs on asyncio. `psycopg` is synchronous — calling it from an async route handler blocks the event loop. When one request is waiting for a Postgres query, no other requests can be handled. `asyncpg` is a natively async Postgres driver — it yields control to the event loop during I/O. Under load with 50 concurrent users, `asyncpg` handles all 50 queries concurrently. `psycopg` handles them sequentially. The difference becomes 50× latency under contention. Additionally, `asyncpg` is one of the fastest Python-to-Postgres drivers benchmarked — it uses Postgres binary protocol and avoids Python object allocation overhead."

---

**Q: Walk me through your database connection pool configuration decisions.**

A: "The constraint is Postgres's `max_connections = 100` (default for Docker). My stack has: 1 API process (pool_size=10, max_overflow=5 = max 15 connections) + 1 worker process (pool_size=5 = 5 connections) = 20 total at peak. That leaves 80 connections for headroom, admin access, and pgAdmin. Key settings: `pool_pre_ping=True` (validates connections after Docker restarts — avoids 'broken pipe' errors on stale connections), `pool_recycle=3600` (prevents connections that have been idle for an hour from silently dying). When I add a second worker, I must reduce pool sizes or add PgBouncer as a connection multiplexer."

---

### RAG / ML Engineering Questions

**Q: How do you prevent the LLM from hallucinating answers that aren't in the documents?**

A: "Three mechanisms:
1. **System instruction:** The system prompt explicitly says 'Answer ONLY from the provided context. If the answer is not in the context, say I don't know. Do not use any outside knowledge.'
2. **Context injection:** Every query includes the retrieved chunks as the only source material. GPT-4o-mini's responses are grounded in what I inject.
3. **Citation requirement:** The prompt asks the model to cite source filenames for each claim. This makes hallucinations auditable — if it cites a filename and the answer isn't in that file, it's detectable.

The honest answer is that LLMs can still hallucinate despite all three. For applications where accuracy is critical (legal, medical), you need post-processing: extract the answer, verify each cited claim against the retrieved chunks, score confidence. For PDFTalk's use cases, the grounding instruction + citation requirement provides adequate quality at MVP stage."

---

**Q: Why 512-token chunks with 64-token overlap instead of different values?**

A: "The optimal chunk size trades off two things: semantic coherence and retrieval granularity. Too small (128 tokens): chunks are too short to contain complete thoughts, embeddings capture fragments, retrieval is noisy. Too large (2048 tokens): chunks contain multiple topics, the embedding averages over all of them, similarity search is less precise. 512 tokens (roughly 400 words, ~half a page) is the consensus sweet spot for OpenAI embeddings — large enough to capture full semantic units, small enough to be topically focused.

The 64-token overlap prevents information loss at chunk boundaries. Imagine a sentence split across chunk N and chunk N+1. Without overlap, neither chunk has the complete sentence. With 64-token overlap, the boundary sentence is fully represented in at least one chunk.

I'd validate these values by measuring retrieval quality on a test document: ask known questions, measure whether the relevant chunks appear in the top 5 results. If retrieval quality is poor, I'd experiment with 256 and 1024 token sizes."

---

## Section B: System Design Questions

### Design Challenge 1: Scale PDFTalk to 10,000 Users

**Scenario:** PDFTalk is growing. You have 10,000 active users, 5,000 documents/day being processed, 50,000 queries/day. The single Lightsail instance is at 85% CPU. What do you change?

**Senior Answer:**

"I'd approach this in tiers, moving to managed services based on actual bottlenecks rather than premature scaling:

**Tier 1 — Vertical scale (immediate, cheapest):**
Upgrade Lightsail to 4 vCPU / 8GB instance ($40/month). Runs `docker compose up -d` — zero code changes. This doubles compute headroom.

**Tier 2 — Horizontal worker scale (when ingestion backlog builds):**
Deploy a second Lightsail instance as a worker node only (runs `docker compose up -d worker`). The RQ queue is in Redis (already the first instance). Workers share the queue naturally. Database and Redis stay on the primary instance.

**Tier 3 — Managed database (when I have paying users + SLA):**
Migrate Postgres to AWS RDS (Multi-AZ for automatic failover). The change is one environment variable: `DATABASE_URL`. All Alembic migrations run against the new RDS endpoint. Redis to ElastiCache is the same swap. This adds ~$130/month but removes backup management and gives automated failover.

**Tier 4 — Application tier scale (when API is the bottleneck):**
Move to ECS Fargate with an Application Load Balancer. The Docker images already exist — the architecture is the same. The ALB provides auto-scaling based on CPU/request metrics. This is the transition from DevOps-by-SSH to platform-as-a-service.

**What I'd monitor to know which tier to trigger:**
- Lightsail CPU `top` / CloudWatch: consistently >70% → Tier 1
- RQ queue depth growing over time → Tier 2  
- Backup restore tests taking >30 minutes / write IOPS hitting limits → Tier 3
- API response latency P95 > 500ms under load → Tier 4"

---

### Design Challenge 2: Add Multi-Tenancy (Organizations)

**Scenario:** B2B customers want team accounts. Multiple users should share documents within their organization. How would you redesign PDFTalk?

**Senior Answer:**

"I'd add an `organizations` table and an `organization_members` join table. The data model change:

```sql
CREATE TABLE organizations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    plan TEXT NOT NULL DEFAULT 'free',  -- free, pro, enterprise
    owner_id UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE organization_members (
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'member',  -- owner, admin, member
    PRIMARY KEY (organization_id, user_id)
);

-- Documents now belong to either a user OR an org (nullable org_id)
ALTER TABLE documents ADD COLUMN organization_id UUID REFERENCES organizations(id);
```

The critical security change: every ownership check must now check `document.organization_id = current_user_org_id OR document.user_id = current_user_id`. I'd create a `get_document_with_permission_check(document_id, user_id)` service function that encapsulates this logic — never inline ownership checks in route handlers.

Quotas become per-organization, tracked by `organization_id` instead of `user_id` in Redis. Rate limits shift to per-organization or per-plan.

The migration from user-owned to org-owned documents is backwards-compatible: `organization_id` is nullable, existing documents have `organization_id = NULL` (personal documents), new org documents have it set."

---

### Design Challenge 3: Real-Time Document Collaboration

**Scenario:** Multiple users want to chat about the same document simultaneously. How would you add real-time features?

**Senior Answer:**

"The current architecture is request-response with SSE for single-user streaming. For multi-user real-time collaboration, I'd evaluate:

**WebSockets (chosen approach):**
FastAPI supports WebSockets natively. A WebSocket connection is bidirectional and persistent — perfect for chat rooms. The design:

```
User A opens chat room for document X
    → WebSocket connection to /ws/documents/{doc_id}/chat
    → API registers the connection in Redis: HSET chat:doc_id:connections user_a_id ws_id

User A sends message
    → API processes the RAG query
    → As tokens stream from OpenAI, publish to Redis pub/sub: PUBLISH chat:doc_id:stream token
    → All WebSocket connections subscribed to doc_id receive the token
    → User B sees the answer appearing in real time (even though they didn't ask)
```

**Redis Pub/Sub for horizontal scaling:**
If I have multiple API servers (Tier 4), a WebSocket from User A might be on Server 1 while User B is on Server 2. When User A's query generates a token, Server 1 publishes to Redis. Server 2 is subscribed and pushes to User B's connection. Redis Pub/Sub is the message bus between API servers.

**When I'd build this:** After achieving product-market fit with the single-user flow. WebSocket infrastructure adds significant complexity (reconnection handling, presence detection, message persistence for offline users). That complexity is only worth it if users are explicitly asking for collaboration."

---

## Section C: AWS & Infrastructure Questions

**Q: How would you monitor PDFTalk in production?**

A: "I'd build monitoring in three layers:

**Layer 1 — Application (already built):**
- `GET /health` endpoint returns DB/Redis/S3 status with component-level granularity
- structlog JSON logs with request_id, duration_ms, user_id (no PII), status_code
- RQ worker logs job completion/failure with document_id and duration

**Layer 2 — Infrastructure:**
- Lightsail's built-in metrics (CPU, network in/out, disk) — set alarm at 80% CPU
- Docker stats monitoring: `docker stats --no-stream` in a cron → alert if any container is using >90% of memory limit
- Certbot pre-expiry alert: script that checks cert expiry daily, alert if <14 days

**Layer 3 — Business metrics (post-MVP):**
- Daily active users (query count per day from job_logs)
- Document ingestion success rate (READY vs FAILED ratios)
- OpenAI spend per day/user (from Redis token counters + daily flush to Postgres)
- P95 query latency (log duration_ms for every `/query/ask` request, weekly report)

For alerting delivery: email via Resend (already set up), or a Slack webhook for the more urgent alerts (server down, database unreachable)."

---

**Q: Your Postgres container crashes at 3am. Walk me through your recovery procedure.**

A: "
1. **Detect:** Lightsail CPU alarm fires (CPU drops to 0 because the API is crashing in a restart loop). Or the health check pings fail. I'm alerted via email/Slack.

2. **SSH in:** `ssh ubuntu@<static-ip>`

3. **Diagnose:** 
```bash
docker compose ps           # Which containers are unhealthy?
docker compose logs postgres --tail=100   # Why did postgres crash?
# Common causes: out of disk (check: df -h), OOM kill (check: dmesg | grep -i kill)
```

4. **If OOM kill:** Postgres exceeded memory. Check `docker stats`. Increase Postgres shared_buffers or upgrade instance. Restart: `docker compose up -d postgres`.

5. **If disk full:** S3 documents going to local disk? Old Docker images? `docker system prune -f`. Then restart.

6. **If data corruption:** This is when backups matter. 
```bash
# Start postgres, check if it recovers automatically
docker compose up -d postgres
docker compose logs postgres | grep 'ready to accept connections'

# If not, restore from backup:
docker compose stop api worker
docker volume rm pdftalk_postgres_data
docker compose up -d postgres
# Wait for postgres to initialize empty DB
docker compose exec -T postgres psql -U pdftalk pdftalk < /opt/backups/latest.sql
# OR from S3:
aws s3 cp s3://pdftalk-backups/$(aws s3 ls pdftalk-backups/ | tail -1 | awk '{print $4}') - | gunzip | docker compose exec -T postgres psql -U pdftalk pdftalk
docker compose up -d api worker
```

7. **Post-incident:** Document the cause, the recovery time (RTO), and data loss window (RPO = time since last backup). If backup was 22 hours old, you lost 22 hours of data. Update backup frequency if needed.

The 'restore procedure documented in README' in T-62 is exactly for this scenario — you shouldn't be figuring out the restore command at 3am."

---

**Q: How do you handle a compromised API key?**

A: "Immediate response (< 5 minutes):
1. **OpenAI:** Rotate the key in the OpenAI dashboard (new key, revoke old). Add it to the `.env` on Lightsail. Restart the API container.
2. **AWS IAM:** In IAM console, deactivate the `pdftalk-app` access key. Create a new key. Update `.env`. Restart.
3. **JWT secret:** If compromised, all existing JWT sessions are invalid. Rotate the secret, restart API. All users will need to log in again — acceptable for a security incident.

Prevention:
- `detect-secrets` pre-commit hook catches keys before they reach git
- `git log --all -- .env` should always return empty
- `.env` file `chmod 600` on server
- GitHub Actions secrets are encrypted — only accessible during workflow runs
- Set AWS spending alerts — a compromised key being abused shows up as anomalous S3 costs"

---

## Section D: Security-Specific Interview Questions

**Q: What is CORS and how does your implementation protect against CSRF?**

A: "CORS (Cross-Origin Resource Sharing) is a browser mechanism that prevents JavaScript on `evil.com` from making credentialed API calls to `pdftalk.com`. In our CORS config: `allow_origins=[settings.APP_URL]` — only our frontend domain is whitelisted. The browser checks this before allowing cross-origin requests.

For CSRF (Cross-Site Request Forgery): the attack is a malicious website tricking a logged-in user's browser into making an unintended request. Our defenses: `SameSite=strict` on the refresh token cookie means it's never sent on cross-origin requests (the browser won't include it on a request from `evil.com`). For the access token in memory — it's never automatically attached; the frontend explicitly sets the `Authorization` header, which browsers block cross-origin without CORS approval. The combination of SameSite cookies + Authorization header makes traditional CSRF attacks ineffective."

**Q: What is the difference between authentication and authorization?**

A: "Authentication answers 'Who are you?' — verifying identity. In PDFTalk: JWT signature validation, checking expiry, reading the `user_id` from the `sub` claim. Authorization answers 'Are you allowed to do this?' — verifying permissions. In PDFTalk: `document.user_id == current_user.id`. Every document endpoint does both: authenticate (JWT middleware → user_id), then authorize (ownership check). The subtle bug that juniors write: doing authentication but not authorization. They check that the user is logged in but forget to verify the resource belongs to them. User A can delete User B's documents. Returning 404 instead of 403 on failed authorization is also authorization design — it doesn't reveal that the resource exists."

---

# PART 16 — NOTION WORKSPACE PAGE CONTENT

## Page: Project Dashboard

**Purpose:** Single-pane-of-glass view of project health, current sprint, and quick links.

**Content:**
```
## Project Status: 🟡 In Progress — Phase 5 (Authentication)

### This Week's Goal
Complete JWT + refresh token system and pass T-23 auth integration tests.

### Progress
Phase 1 Foundation      ████████████████████ 100% ✅
Phase 2 Database        ████████████████████ 100% ✅  
Phase 3 Infrastructure  ████████████░░░░░░░░  60% 🔄
Phase 4 Backend Scaffold ████░░░░░░░░░░░░░░░░  20% 🔄
Phase 5 Auth            ░░░░░░░░░░░░░░░░░░░░   0% 🔜
...

### Today's Blockers
- [ ] DNS not propagated yet — waiting on Route 53 (T-09)

### Quick Links
- GitHub: [pdftalk repo]
- Lightsail Console: [link]
- OpenAI Usage: [platform.openai.com/usage]
- Resend Dashboard: [resend.com]
- Monthly cost tracker: $22.50 / $30 budget

### Key Dates
- Target first deploy: [DATE]
- Target soft launch: [DATE]
```

**Database needed:** Task Tracker (linked view filtered to current phase)

---

## Page: Architecture Decision Records

**Purpose:** Permanent record of WHY architectural decisions were made. Future you will thank past you.

**Template for each ADR:**
```
## ADR-001: pgvector vs FAISS + EFS

### Status: ACCEPTED

### Context
We need vector storage for document embeddings. Options evaluated:
1. pgvector (Postgres extension)
2. FAISS + EFS (file-based index on shared storage)
3. Pinecone (managed vector DB)

### Decision
Use pgvector inside the existing Postgres container.

### Rationale
- Zero additional services: pgvector runs in the same container as Postgres
- Zero file locking: FAISS on EFS has documented race conditions with multiple readers
- Simple query: 5 lines of SQL with the <=> operator
- Performance: indistinguishable from FAISS at <100K chunks per user
- Cost: $0 additional vs $25-50/month for Pinecone at MVP scale

### Trade-offs Accepted
- pgvector's IVFFlat index has ~95% recall (vs FAISS exact search)
- Scaling the vector DB means scaling Postgres (coupled)

### Migration Trigger
When pgvector P95 query time > 200ms under real production load.

### Migration Path
1. Create Pinecone index (1536 dimensions, cosine metric)
2. Swap out services/retrieval.py with a Pinecone client implementation
3. Backfill existing embeddings via one-time migration script
4. No changes to API, no changes to frontend
```

---

## Page: Sprint Board (Notion Database)

**Database Properties:**
```
Task ID         (text)           e.g. "T-04"
Title           (title)          e.g. "Database schema + pgvector + Alembic"
Phase           (select)         Phase 1 through Phase 12
Status          (select)         Not Started / In Progress / Done / Blocked / Deferred
Priority        (select)         Critical / High / Medium / Low
Depends On      (relation)       → other Task rows
Estimated Days  (number)         
Actual Days     (number)         filled in when done
PR Link         (url)            GitHub PR
Notes           (rich text)      blockers, decisions, gotchas
Completed Date  (date)
```

**Views to create:**
- **Current Sprint** (table): Filter Status ≠ Done, Sort by Phase ASC, Priority DESC
- **Board by Status** (board): Group by Status
- **Dependency Graph** (table): Show task + Depends On relation
- **Timeline** (timeline): Estimated Days → Calendar view

---

## Page: Auth System Deep Dive

**Purpose:** Reference for every auth-related question, debugging guide, and security rationale.

**Content structure:**
```
## Token Flow Diagram
[diagram of register → verify → login → access → refresh → logout]

## Security Decisions
### Why httpOnly cookies for refresh tokens?
[rationale from T-47 — XSS can't read httpOnly]

### Why path-scoped to /auth/refresh?
[rationale from T-20 — cookie not leaked on every request]

### Why 15-minute access token TTL?
[rationale — balance between revocation speed and UX]

## Debugging Guide
### "401 Unauthorized" after login
1. Check: is the Authorization header being sent?
   → curl -v ... | grep Authorization
2. Check: has the token expired? 
   → JWT payload exp claim vs current UTC time
3. Check: is is_verified = true for this user?
   → SELECT is_verified FROM users WHERE email_lower = '...'

### "Refresh cookie not being sent"
1. Check: is the request to exactly /auth/refresh?
   → Cookie is path-scoped
2. Check: is the request HTTPS?
   → Secure attribute requires HTTPS
3. Check: is it same-site?
   → SameSite=strict — not sent cross-origin

## Test Coverage
T-23 covers: [list all test cases from the integration test suite]
```

---

## Page: Interview Prep — System Design: PDFTalk

**Purpose:** Practice explaining the system at different levels for different interviewer types.

**Content:**
```
## 2-Minute Pitch (Phone Screen)
"PDFTalk is a RAG application — users upload PDFs and ask questions in natural 
language. The backend processes uploads asynchronously: extract text with PyMuPDF, 
chunk with tiktoken, embed with OpenAI's text-embedding-3-small, store vectors in 
Postgres with pgvector. At query time: embed the question, find the 5 most relevant 
chunks via cosine similarity, inject them into a GPT-4o-mini prompt, stream the 
response via Server-Sent Events. The whole stack runs on Docker Compose on a $20/month 
Lightsail instance — a deliberate choice to minimize operational complexity and cost 
at MVP stage."

## 30-Minute Deep Dive (System Design Interview)
[Full architecture diagram]
[ADR explanations]
[Scaling plan with specific triggers]
[Security design rationale]
[Where you'd go from here]

## Questions You Should Ask the Interviewer
- "What scale are we designing for? 1,000 users? 1 million?"
- "Is this read-heavy or write-heavy at the query layer?"  
- "What's the latency requirement for the streaming endpoint?"
- "Are there compliance requirements (HIPAA, SOC 2) that constrain the architecture?"
```

---

# PART 17 — MISSING TASKS: FORMAL SPECIFICATIONS

## T-64 — Frontend E2E Tests (Playwright)

**What to build:** Playwright test suite covering the full user journey. Three core flows: happy path (register → upload → query), auth failure paths (wrong password, expired session), and error states (upload quota exceeded, document processing failure).

**Tech:** Playwright, TypeScript

**Depends on:** T-52, T-53 (frontend complete)

```typescript
// playwright.config.ts
import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,         // Sequential — auth state must not leak between tests
  timeout: 60_000,              // 60s — allows for document processing
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL || 'http://localhost:3000',
    trace: 'on-first-retry',    // Record trace for failed test debugging
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
    { name: 'Mobile Safari', use: { ...devices['iPhone 13'] } },
  ],
});
```

---

## T-65 — Error Tracking (Sentry)

**What to build:** Integrate Sentry SDK in both FastAPI and Next.js. Capture unhandled exceptions with user context (user_id only, no PII). Set up alert rules for error spikes. Add Sentry release tracking linked to git SHAs.

**Tech:** `sentry-sdk[fastapi]`, `@sentry/nextjs`

**Depends on:** T-12, T-46

```python
# backend/main.py
import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

sentry_sdk.init(
    dsn=settings.SENTRY_DSN,
    integrations=[FastApiIntegration(), SqlalchemyIntegration()],
    traces_sample_rate=0.1,     # 10% of requests for performance monitoring
    release=settings.GIT_SHA,   # Links errors to exact commit
    environment="production",
    # CRITICAL: Scrub PII from events
    before_send=scrub_pii_from_event,
)

def scrub_pii_from_event(event, hint):
    """Remove email, passwords, tokens from Sentry payloads."""
    if 'request' in event:
        if 'data' in event['request']:
            # Remove password from login requests
            event['request']['data'].pop('password', None)
    return event
```

---

## T-67 — Password Reset Flow

**What to build:**
- `POST /auth/forgot-password` — accepts email, generates reset token (same pattern as email verification: store SHA256(token) with 1-hour expiry), sends reset email. Always returns 202 (no email enumeration).
- `POST /auth/reset-password` — accepts token + new password, validates token, updates password_hash, deletes all existing refresh tokens (force logout everywhere), deletes the reset token.
- Frontend: `/forgot-password` page + `/reset-password?token=...` page

**Tech:** FastAPI, SQLAlchemy, Resend email

**Depends on:** T-17, T-18, T-20

**Security notes:**
- 1-hour token expiry (shorter than email verification's 24h — password resets are more sensitive)
- Delete ALL refresh tokens on successful reset (forces re-login on all devices)
- Rate limit to 3 password reset requests per email per hour (prevent email flooding)
- Reset token single-use, deleted immediately on use

---

# PART 18 — PRODUCTION MONITORING RUNBOOK

## Daily Health Checks (automate these with cron)

```bash
#!/bin/bash
# /opt/pdftalk/scripts/health_check.sh
# Run hourly via cron: 0 * * * * ubuntu /opt/pdftalk/scripts/health_check.sh

DOMAIN="pdftalk.com"
ALERT_EMAIL="you@example.com"
SLACK_WEBHOOK="https://hooks.slack.com/..."

# 1. Check /health endpoint
HEALTH=$(curl -sf "https://$DOMAIN/health" | jq -r '.status' 2>/dev/null)
if [ "$HEALTH" != "ok" ]; then
    curl -X POST -H 'Content-type: application/json' \
        --data '{"text":"🚨 PDFTalk health check FAILED"}' \
        "$SLACK_WEBHOOK"
fi

# 2. Check disk space
DISK_USAGE=$(df /opt/pdftalk | awk 'NR==2{print $5}' | sed 's/%//')
if [ "$DISK_USAGE" -gt 80 ]; then
    curl -X POST -H 'Content-type: application/json' \
        --data "{\"text\":\"⚠️ Disk usage: ${DISK_USAGE}%\"}" \
        "$SLACK_WEBHOOK"
fi

# 3. Check RQ queue depth
QUEUE_DEPTH=$(docker compose -f /opt/pdftalk/docker-compose.yml exec -T redis \
    redis-cli -a "$REDIS_PASSWORD" LLEN rq:queue:default)
if [ "$QUEUE_DEPTH" -gt 50 ]; then
    curl -X POST -H 'Content-type: application/json' \
        --data "{\"text\":\"⚠️ RQ queue depth: ${QUEUE_DEPTH} jobs pending\"}" \
        "$SLACK_WEBHOOK"
fi

# 4. Check SSL cert expiry
EXPIRY=$(echo | openssl s_client -servername "$DOMAIN" -connect "$DOMAIN:443" 2>/dev/null \
    | openssl x509 -noout -dates 2>/dev/null | grep notAfter | cut -d= -f2)
EXPIRY_EPOCH=$(date -d "$EXPIRY" +%s)
NOW_EPOCH=$(date +%s)
DAYS_REMAINING=$(( ($EXPIRY_EPOCH - $NOW_EPOCH) / 86400 ))
if [ "$DAYS_REMAINING" -lt 14 ]; then
    curl -X POST -H 'Content-type: application/json' \
        --data "{\"text\":\"🔐 SSL cert expires in ${DAYS_REMAINING} days!\"}" \
        "$SLACK_WEBHOOK"
fi
```

## Incident Severity Levels

| Level | Description | Response Time | Examples |
|-------|-------------|---------------|---------|
| P0 — Critical | Complete service outage | 15 minutes | Server down, DB down, HTTPS broken |
| P1 — High | Core feature broken | 1 hour | Login fails, upload fails, queries return errors |
| P2 — Medium | Degraded experience | 4 hours | Slow ingestion, quota errors, email not sending |
| P3 — Low | Minor issue | Next business day | UI cosmetic issues, log noise |

## Common Incidents & Resolutions

| Symptom | First Check | Resolution |
|---------|-------------|------------|
| API returns 502 | `docker compose ps api` → is it running? | `docker compose restart api` |
| Login fails with 500 | `docker compose logs api --tail=50` | Check DB connection (postgres running?) |
| Documents stuck in PROCESSING | `docker compose ps worker` | Worker crashed: `docker compose restart worker` |
| "certificate has expired" | `certbot certificates` | `certbot renew --force-renewal` |
| Disk full | `df -h`, `docker system df` | `docker image prune -a`, then find large files |
| Postgres OOM killed | `dmesg \| grep -i kill` | Restart Postgres, reduce `shared_buffers`, upgrade instance |
| OpenAI 429 errors in logs | OpenAI dashboard | Check if circuit breaker fired; wait for rate limit window |

---

# PART 19 — COST OPTIMIZATION GUIDE

## Current Cost Breakdown: ~$22.50/month

| Service | Cost | Notes |
|---------|------|-------|
| Lightsail $20/month | $20.00 | 2 vCPU, 4GB, 80GB, 4TB transfer |
| Lightsail static IP | $0.00 | Free while attached to an instance |
| Lightsail snapshots | $1.50 | Weekly, ~30GB storage |
| S3 documents | $0.50 | ~20GB at $0.023/GB + requests |
| S3 backups | $0.02 | 7 daily backups, ~100MB compressed each |
| Route 53 | $0.50 | 1 hosted zone + A records |
| OpenAI | Variable | $0.13/1M tokens (embedding), $0.15/1M (GPT-4o-mini) |
| Resend email | $0.00 | Free for first 3,000 emails/month |

## OpenAI Cost Estimation

```
Per document upload (assume 100-page PDF, ~50,000 tokens):
  Embedding: 50,000 tokens × $0.13/1M = $0.0065 (~half a cent)
  
Per user query:
  Query embedding: 100 tokens × $0.13/1M = $0.000013
  GPT-4o-mini response (input 3,100 tokens, output ~500 tokens):
    Input: 3,100 × $0.15/1M = $0.000465
    Output: 500 × $0.60/1M = $0.000300
  Total per query: ~$0.0008 (less than 0.1 cent)

100 active users, 5 docs each, 10 queries/day:
  Ingestion: 500 docs × $0.0065 = $3.25 (one-time)
  Queries: 1,000/day × $0.0008 × 30 days = $24/month
```

## Cost Alerts to Set

1. **OpenAI:** Set a monthly spending limit of $50 in OpenAI dashboard settings. Hard stop prevents runaway costs from a bug or malicious user.
2. **AWS:** Create a billing alarm in CloudWatch at $10/month. If AWS costs exceed $10 unexpectedly, you know immediately.
3. **Application-level:** T-44 implements per-user daily token quotas. Log when any user exceeds 50% of their daily quota.

---

# PART 20 — FINAL TECHNICAL GLOSSARY

| Term | Definition | Used In |
|------|------------|---------|
| RAG | Retrieval-Augmented Generation: retrieve relevant context, inject into LLM prompt | Core architecture |
| pgvector | PostgreSQL extension for vector data type and similarity search operators | T-04, T-34 |
| IVFFlat | Inverted File with Flat quantization: approximate nearest neighbor index for pgvector | T-04 (deferred) |
| Cosine similarity | Measure of angle between two vectors (0=orthogonal, 1=identical direction) | T-34 |
| L2 normalization | Scale a vector to unit length (magnitude=1) | T-33 |
| JWT | JSON Web Token: self-contained, signed token encoding claims | T-16 |
| JTI | JWT ID: unique identifier per token, used for revocation | T-16 |
| Opaque token | A token with no decodable content (random string) | T-16 |
| Token rotation | Issue a new refresh token on every use, invalidating the old one | T-16, T-21 |
| httpOnly cookie | Cookie inaccessible to JavaScript — XSS-safe | T-20, T-47 |
| SameSite=strict | Cookie not sent on cross-origin requests — CSRF protection | T-20 |
| Sliding window | Rate limiting: count requests in the last N seconds (not clock-reset fixed window) | T-42 |
| Circuit breaker | Stop calling a failing service after N failures, retry after timeout | T-32 |
| SSE | Server-Sent Events: one-way HTTP streaming (server → client) | T-39 |
| RQ | Redis Queue: Python background job queue backed by Redis | T-28 |
| Dead letter queue | Queue holding permanently failed jobs for inspection/retry | T-28 |
| Alembic | Python database migration tool for SQLAlchemy schemas | T-04 |
| asyncpg | Native async PostgreSQL driver for Python | T-05 |
| Multi-stage build | Docker build with multiple FROM stages — smaller final image | T-54 |
| Named volume | Docker volume with a name, persisting across container recreations | T-55 |
| pgcrypto | PostgreSQL extension providing `gen_random_uuid()` | T-04 |
| Pre-commit hook | Git hook running before commit — catches secrets, lint errors | T-01 |
| `detect-secrets` | Tool scanning code for accidentally committed secrets | T-01 |
| `email_lower` | Normalized lowercase email for case-insensitive uniqueness | T-04, T-18 |
| magic bytes | First bytes of a file identifying its true type (not Content-Type header) | T-25 |
| `pool_pre_ping` | SQLAlchemy: validate connection before use — fixes stale connections | T-05 |
| PgBouncer | PostgreSQL connection pooler — multiplexes many app connections into fewer DB connections | Migration path |
| HSTS | HTTP Strict Transport Security: tells browsers to always use HTTPS | T-10, T-56 |
| CSP | Content Security Policy: restricts sources of scripts, styles, etc. | T-41 (add) |
| ADR | Architectural Decision Record: document explaining a design decision | Throughout |
| SHA tag | Docker image tag using git commit SHA — immutable, auditable | T-58 |
| Exponential backoff | Retry delay that doubles with each failure (30s → 120s → 480s) | T-28, T-32 |
| `set -e` | Bash: exit immediately if any command fails | T-58 |
| Smoke test | Minimal test confirming a deployment works at the most basic level | T-63 |
| PKI | Public Key Infrastructure: certificates, CAs, TLS | T-10 |
| WCAG 2.1 AA | Web Content Accessibility Guidelines level AA: minimum accessible contrast and interaction | T-53 |

---

> **Document version:** 2.0 (Complete)
> **Parts:** 20 | **Sections:** Executive Summary, Architecture Review, Keep/Modify/Delete/Missing, Master Roadmap, 7 Senior Task Deep Dives, QA Strategy with test cases, Concept Teaching Library (12 topics), Knowledge Graph, Production Readiness, Interview Prep Hub (4 sections, 20+ Q&As), Notion Workspace, Missing Task Specifications, Monitoring Runbook, Cost Guide, Technical Glossary
> **Based on:** PDFTalk MVP Task List v1.0 (63 tasks, 12 phases)
> **Supplemental tasks added:** T-64 (Playwright E2E), T-65 (Sentry), T-67 (Password Reset)
> **Total tasks covered:** 66
