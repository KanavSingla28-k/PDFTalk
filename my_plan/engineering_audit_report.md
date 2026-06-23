# PDFTalk v2.0 — Comprehensive Engineering Audit Report

> **Scope:** Full-stack repository audit (backend, frontend, infra, CI/CD, database, observability)
> **Objective:** Identify every weakness, inconsistency, security risk, and technical debt item that prevents this application from being production-grade, scalable, maintainable, secure, and professional — without changing what the system does.
> **Constraint:** Zero new features. 100% focused on hardening, polishing, and improving the existing system.

---

## Executive Summary

PDFTalk v2.0 is a well-structured RAG application. The architecture decisions are sound: JWT + httpOnly refresh tokens, presigned S3 uploads, sliding-window Redis rate limiting, async SQLAlchemy with a clean service layer, structured logging via `structlog`, and a CI pipeline with lint + type-check + test gates. The codebase is clearly built with care.

However, a number of issues — some **Critical**, many **High** severity — stand between this codebase and a hardened production system. This report catalogs every one of them.

**Finding Distribution:**
| Severity | Count |
|---|---|
| 🔴 Critical | 7 |
| 🟠 High | 14 |
| 🟡 Medium | 11 |
| 🔵 Low / Polish | 9 |

---

## Section 1: Security

### 🔴 CRIT-1 — Production is served over plain HTTP (No TLS)

**Location:** `infra/nginx/nginx.prod.conf` L1-4, `docker-compose.yml` L190-191, `deploy.yml` L143

**Finding:** The production Nginx config is HTTP-only. The README links directly to `http://13.207.100.137`. The commented-out HTTPS server block is marked `TODO T-10`. There is **no TLS at all on the live production instance**.

**Consequences:**
- All user credentials (passwords, JWTs) transmitted in plaintext.
- The `httpOnly` refresh token cookie has `secure=False`, so it is transmitted over HTTP, defeating its primary CSRF-protective property.
- The `Strict-Transport-Security` (HSTS) header is intentionally omitted as noted in comments.
- Session hijacking over any network (café, hotel, VPN interception) is trivially possible.

**Fix:**
1. Provision a domain name (or use a free Let's Encrypt cert via Certbot/ACME).
2. Uncomment and activate the HTTPS server block already templated in `nginx.prod.conf` (lines 243–270).
3. Set `secure=True` on the refresh token and admin session cookies in `internal.py` and `auth.py`.
4. Convert the HTTP block to a permanent redirect (`301`) to HTTPS.
5. Add the `Strict-Transport-Security` header.

---

### 🔴 CRIT-2 — Admin token stored as cookie value (Cookie = Shared Secret)

**Location:** `backend/app/routers/internal.py` L121-128

**Finding:** On successful admin login, the raw `ADMIN_TOKEN` itself is written as the cookie value:
```python
response.set_cookie(key=_COOKIE_NAME, value=settings.ADMIN_TOKEN, ...)
```
And then authentication checks `if not secrets.compare_digest(admin_session, settings.ADMIN_TOKEN)`.

This means:
- Anyone who intercepts the admin cookie (via network sniffing on HTTP, see CRIT-1) **has the ADMIN_TOKEN** permanently, not just a session — they can authenticate directly or forge Bearer tokens.
- There is no session invalidation mechanism. Admin "logout" just clears the browser cookie; the token is not revoked anywhere server-side.
- The cookie value *is* the master secret.

**Fix:** Issue a short-lived opaque session token on admin login (e.g., `secrets.token_urlsafe(32)`), store its hash in Redis with an 8-hour TTL, and validate the hash on each request. The `ADMIN_TOKEN` becomes a login password only, not the session credential.

---

### 🔴 CRIT-3 — Swagger UI / OpenAPI docs exposed in production

**Location:** `backend/app/main.py` (FastAPI defaults), `backend/app/middleware/security.py` L14-15

**Finding:** FastAPI enables `/docs`, `/redoc`, and `/openapi.json` by default. The `SecurityHeadersMiddleware` **special-cases these paths** with a looser CSP (allowing `unsafe-inline` and CDN sources), confirming they are deliberately left accessible.

The production Nginx config has **no `location` block blocking these paths**. They are therefore publicly reachable at `http://<production-ip>/api/docs`.

This gives attackers:
- A complete, interactive map of every API endpoint, request/response schema, and error code.
- An easy way to craft valid attack payloads.

**Fix:** In `nginx.prod.conf`, add:
```nginx
location ~* ^/api/(docs|redoc|openapi.json) {
    return 404;
}
```
Alternatively, disable in `main.py` conditionally:
```python
app = FastAPI(docs_url=None if settings.is_production else "/docs", ...)
```
Add a `is_production: bool` flag to `config.py` (e.g., `ENVIRONMENT: Literal["development", "production"] = "development"`).

---

### 🔴 CRIT-4 — A hardcoded production IP address is committed to source control

**Location:** `docker-compose.yml` L171, `README.md` L15

**Finding:**
```yaml
NEXT_PUBLIC_API_URL: http://13.207.100.137/api
```
A static production IP is baked into `docker-compose.yml` as a build argument. This is committed to source control.

**Consequences:**
- Any contributor (current or future) knows the production server's IP.
- The frontend image built from this file hardcodes the IP at build time, making environment promotion (dev → staging → prod) impossible without rebuilding.
- CI also reads `NEXT_PUBLIC_API_URL` from `secrets.NEXT_PUBLIC_API_URL` (deploy.yml L54) — but the docker-compose.yml fallback leaks the value for local builds.

**Fix:** Remove the hardcoded value from `docker-compose.yml`. In a compose context, supply it via `.env` file or GitHub secrets only:
```yaml
args:
  NEXT_PUBLIC_API_URL: ${NEXT_PUBLIC_API_URL}
```

---

### 🔴 CRIT-5 — Prometheus `/metrics` endpoint accessible from public internet

**Location:** `infra/nginx/nginx.prod.conf` L225-227

**Finding:**
```nginx
location = /api/metrics {
    return 404;
}
```
This blocks `/api/metrics` (with the prefix rewrite) but the block uses `=` exact match on the URL with the `/api` prefix intact. **However**, if Nginx's rewrite rule fires first (which it does in the generic `/api/` block), the actual path reaching the API is `/metrics`. A direct request to `/metrics` on the API container from inside the Docker network is not blocked. More critically, *FastAPI registers the `/metrics` endpoint without the `/api` prefix* — if the Nginx block is matched correctly, the block succeeds; but the Nginx config's `location = /api/metrics` block is **not matched by the rewrite** used in the general `/api/` block. A careful attacker hitting `http://ip/api/metrics` may bypass this depending on evaluation order.

More concretely, the Prometheus multiprocess metrics expose: request rates, error rates, latency distributions per endpoint, daily quota breach counts, and user login patterns — a detailed fingerprint of system behavior and load.

**Fix:** Test explicitly that `/api/metrics` returns 404 from the public internet. Consider restricting the `/metrics` FastAPI route to internal network only using a middleware check (`request.client.host` must be `172.x.x.x` or `127.0.0.1`).

---

### 🔴 CRIT-6 — `pyproject.toml` lists `pytest`, `fakeredis`, `moto` as runtime (non-dev) dependencies

**Location:** `backend/pyproject.toml` L28-32

**Finding:**
```toml
dependencies = [
    ...
    "pytest",
    "pytest-asyncio",
    "pytest-cov",
    "fakeredis",
    "moto[s3]",
    ...
]
```
These are test dependencies declared inside `[project] dependencies` (runtime), not in `[dependency-groups] dev`. This means:
- The production Docker image installs `pytest`, `moto`, `fakeredis` into its environment.
- `moto[s3]` intercepts boto3 calls and can mock AWS services — its presence in production is an attack surface and an accidental footgun (e.g., environment variables that trigger moto's automatic mocking).
- Also `redis` and `rq` appear **twice** in the list (lines 34-35 are duplicates of 16 and 17).

**Fix:** Move test-only dependencies to `[dependency-groups] dev`. Use `uv sync --no-dev` in the Dockerfile to exclude dev dependencies. Remove duplicate entries.

---

### 🔴 CRIT-7 — The deploy workflow SSH key is written to a temp file with `StrictHostKeyChecking=no`

**Location:** `.github/workflows/deploy.yml` L93-99

**Finding:**
```yaml
echo "${{ secrets.LIGHTSAIL_SSH_KEY }}" > /tmp/deploy_key
chmod 600 /tmp/deploy_key
scp -i /tmp/deploy_key \
    -o StrictHostKeyChecking=no \
```
`StrictHostKeyChecking=no` means the SSH client will **accept any host key**, including one from a man-in-the-middle (MITM) attacker who has taken over the Lightsail IP. If the IP is temporarily reassigned (e.g., Lightsail instance is destroyed and re-created, or an attacker takes over the IP), the entire production deployment pipeline would upload Docker images and run arbitrary code on an attacker-controlled machine.

**Fix:** Add the known host key as a secret (`LIGHTSAIL_SSH_KNOWN_HOSTS`) and use:
```yaml
echo "${{ secrets.LIGHTSAIL_SSH_KNOWN_HOSTS }}" >> ~/.ssh/known_hosts
```
Remove `-o StrictHostKeyChecking=no`. The `appleboy/ssh-action` step already has a key fingerprint mechanism — configure it properly.

---

## Section 2: Security (High Severity)

### 🟠 HIGH-1 — JWT algorithm is configurable but not pinned; `python-jose` is used

**Location:** `backend/app/auth/tokens.py`, `backend/app/core/config.py`, `backend/pyproject.toml`

**Finding:** The JWT library is `python-jose[cryptography]`, which has known CVEs (e.g., CVE-2024-33663 related to algorithm confusion). The algorithm is configurable via `JWT_ALGORITHM` env var. An attacker who can influence env vars or who sets `alg=none` in a token header could bypass verification if not handled correctly.

**Fix:**
1. Replace `python-jose` with `PyJWT` (actively maintained, no algorithm confusion CVEs in recent versions).
2. Pin the algorithm inside the code, not via env var: `jwt.decode(token, key, algorithms=["HS256"])` — remove `JWT_ALGORITHM` from settings entirely or at minimum validate it's in an allowlist of safe algorithms.

---

### 🟠 HIGH-2 — The `status` column on `Document` is stored as plain `Text`, not constrained

**Location:** `backend/app/models/document.py` L69-71, `backend/alembic/versions/0001_initial_schema.py` L59-61

**Finding:** The migration creates a `document_status` PostgreSQL ENUM type but then never applies it to the `documents.status` column (which is `sa.Text`). The migration also drops the type in a later migration (`0002_drop_orphaned_document_status_type.py`). The ORM model uses `Mapped[str]`.

The application enforces transitions via `_ALLOWED_TRANSITIONS` in Python, but the **database has no constraint**. A direct SQL write or a future bug could write an arbitrary string like `"HACKED"` into `status`, bypassing all application-layer checks.

**Fix:** Add a `CHECK` constraint on the `status` column:
```sql
ALTER TABLE documents ADD CONSTRAINT chk_document_status
  CHECK (status IN ('PENDING_UPLOAD', 'PENDING', 'PROCESSING', 'READY', 'FAILED'));
```
Add this as a new migration.

---

### 🟠 HIGH-3 — Rate limiter fails open on Redis errors

**Location:** `backend/app/utils/rate_limit.py` L170-172

**Finding:**
```python
except RedisError as exc:
    logger.error("rate_limiter.redis_error", error=str(exc))
    raise HTTPException(status_code=503, detail="Service Unavailable")
```
When Redis is unavailable, the rate limiter returns a 503 error — which **blocks all traffic**, including legitimate users. This means a Redis outage takes down the entire API.

Conversely, if the error is swallowed (alternative fail-open), the rate limiter is bypassed. Neither extreme is correct.

**Fix:** Implement a **fail-open** mode behind a feature flag: if Redis is unreachable, log a warning and allow the request through (fail open), accepting the risk of temporarily unthrottled traffic rather than a complete outage. Gate the behavior on `settings.RATE_LIMIT_FAIL_OPEN: bool = True`. This is the industry-standard approach for non-security-critical rate limits. For the auth rate limiter specifically, consider fail-closed (503) since brute-force protection is a security control.

---

### 🟠 HIGH-4 — `query.api.ts` SSE stream uses raw `fetch`, not the authenticated `apiFetch` wrapper

**Location:** `frontend/src/lib/query.api.ts`

**Finding:** The SSE streaming request is made with `apiFetch(..., { rawResponse: true })` which correctly attaches the Authorization header. However, if a 401 occurs *during* the SSE stream (after the headers are sent), the client cannot retry — the stream is already open. The 401 will appear as an `error` event inside the stream that requires specific client-side handling. The current `_sse_generator` in `query.py` does not emit a 401 error event; it would simply close the stream, leaving the frontend in an undefined state.

**Fix:** In `query.py`, if a `TokenExpiredError` / `InvalidTokenError` is raised inside `_sse_generator`, emit a structured error event before closing:
```python
yield _error_event("TOKEN_EXPIRED", "Session expired.")
```
And in the frontend SSE parser, handle `error` events with `code === "TOKEN_EXPIRED"` by redirecting to login.

---

### 🟠 HIGH-5 — Alertmanager webhook has no payload validation

**Location:** `backend/app/routers/internal.py` L150-160

**Finding:**
```python
async def alertmanager_webhook(payload: dict[str, Any]) -> None:
    asyncio.create_task(dispatch_alert(payload))
```
The payload is typed as `dict[str, Any]` — entirely unconstrained. Any JSON body is accepted and dispatched. If `dispatch_alert` passes this data downstream to an email/webhook template without sanitization, it's an injection surface. `asyncio.create_task` in a route handler context (outside the request lifecycle) is also risky — if the event loop is torn down, the task is silently dropped.

**Fix:** Define a Pydantic model for the Alertmanager webhook payload schema and validate it. Use FastAPI's background tasks (`BackgroundTasks`) instead of `asyncio.create_task` for lifecycle safety.

---

### 🟠 HIGH-6 — Retrieval SQL query vector is formatted as a Python string

**Location:** `backend/app/services/retrieval.py` L173

**Finding:**
```python
vector_literal = "[" + ",\".join(str(x) for x in query_vector) + "]"
```
The vector is constructed by Python string formatting and then passed as a parameter `:query_vec`. While this is parameterized (SQLAlchemy bind param), the *construction* of the literal from `list[float]` means that if `query_vector` somehow contained malformed data (e.g., due to a bug in the embedding model's response), it could create an invalid or truncated SQL literal. More importantly, floats like `inf` or `nan` would produce a string that PostgreSQL rejects with an unhelpful error.

**Fix:** Validate the embedding vector before constructing the literal: assert all values are finite floats with `math.isfinite()`. Also consider using pgvector's Python type directly (`from pgvector.sqlalchemy import Vector`) to let the ORM handle serialization.

---

### 🟠 HIGH-7 — `retrieve_similar_chunks_sync` passes an `AsyncSession` to a sync context

**Location:** `backend/app/services/retrieval.py` L124-147

**Finding:** The sync wrapper `retrieve_similar_chunks_sync` accepts an `AsyncSession` and wraps the async function with `asyncio.run()`. The docstring warns "Do NOT call this from an already-running event loop." 

The deeper problem: the `AsyncSession` object holds a reference to a specific event loop. When `asyncio.run()` creates a *new* event loop, the session's internal connection may reference the old loop, causing "attached to a different loop" errors that are only visible at runtime.

**Fix:** The sync worker should create its own database session via the sync `SessionLocal` (which already exists in `sync_session.py`). If the worker needs to perform retrieval, it should use a synchronous equivalent or restructure the worker to use `asyncio.run` at the top level (not nested). Either way, the `AsyncSession` argument in the sync wrapper is architecturally incorrect.

---

### 🟠 HIGH-8 — `setup_stale_document_cleanup` swallows all exceptions to reschedule

**Location:** `backend/app/workers/tasks.py` L294-310

**Finding:**
```python
except Exception:
    logger.info("Scheduling initial stale document cleanup job.")
    q.enqueue_in(...)
```
The `except Exception` catches *everything*, including genuine programming errors during `Job.fetch()`. The fallback schedules the job regardless. If the RQ connection is unhealthy or the job state is corrupted, this silently loops forever, writing misleading "Scheduling" log lines.

**Fix:** Catch only the specific expected exception types (`rq.exceptions.NoSuchJobError` or the `ValueError` raised explicitly in the branch). Let genuine errors propagate.

---

### 🟠 HIGH-9 — Token quota TTL is 90,000 seconds (~25 hours), not midnight-aligned

**Location:** `backend/app/utils/openai_client.py` L108

**Finding:**
```python
new_total = await rc.increment_counter_by(key, tokens, ttl_seconds=90_000)
```
The daily quota resets after a sliding 90,000-second window from first use, not at UTC midnight. A user who uses their quota at 11:59 PM can reuse it again at ~1:00 AM the next day (not at midnight). Meanwhile, a user who first queries at midnight must wait until ~1:00 AM the following day. This is inconsistent and confusing.

**Fix:** Set the TTL to expire at the next UTC midnight using `timedelta`:
```python
import datetime
now = datetime.datetime.now(datetime.timezone.utc)
midnight = (now + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
ttl = int((midnight - now).total_seconds())
```
Apply the same fix to the query quota.

---

### 🟠 HIGH-10 — Deploy workflow builds images without a registry; images transferred via `scp` as a tar

**Location:** `.github/workflows/deploy.yml` L60-99

**Finding:** The build job saves all three Docker images as a single `images.tar.gz` (potentially several GB), uploads to GitHub artifacts (1-day retention), and then `scp`s the tarball to the production server. This is:
- Slow (transfer of multi-GB artifact on every deploy)
- Fragile (the `scp` step can time out on large images)
- Non-idempotent (if the scp succeeds but the next step fails, the production server has a partially-loaded state)
- Not using an image registry (no image version history, no rollback path)

**Fix:** Push images to a container registry (e.g., AWS ECR, which is free for private repos under a quota, or GitHub Container Registry `ghcr.io`). The deploy step then becomes `docker compose pull && docker compose up -d` — fast, atomic, and rollback-capable.

---

### 🟠 HIGH-11 — Database backup is `|| true` — silent failures

**Location:** `.github/workflows/deploy.yml` L119

**Finding:**
```yaml
docker compose exec -T postgres sh -c "pg_dump ... -f /var/lib/postgresql/data/backup_$GIT_SHA.dump" || true
```
The `|| true` silently swallows a failed `pg_dump`. If the backup fails (disk full, pg_dump error, container unhealthy), the deployment proceeds and runs migrations — potentially with no backup at all.

**Fix:** Remove `|| true`. Let the step fail loudly if `pg_dump` fails. Or introduce a separate "backup check" step that verifies the dump file exists and is non-empty before proceeding with migrations.

Additionally: backups written to `/var/lib/postgresql/data/` inside the postgres container accumulate over time with no rotation. Define a retention policy.

---

### 🟠 HIGH-12 — The `documents.status` field default on the ORM model is wrong

**Location:** `backend/app/models/document.py` L69-71

**Finding:**
```python
status: Mapped[str] = mapped_column(
    Text, nullable=False, default=DocumentStatus.PENDING.value
)
```
The ORM model defaults to `PENDING`, but the presigned URL flow correctly creates documents as `PENDING_UPLOAD` in `document_service.py`. If a code path bypasses the service layer and creates a `Document` directly (e.g., in tests, future migration scripts, or a bug), it would set the status to `PENDING` — skipping the S3 upload step entirely and creating an inconsistent state.

**Fix:** Change the ORM default to `DocumentStatus.PENDING_UPLOAD.value` to match the presigned flow. This is the correct initial state for all document creation.

---

### 🟠 HIGH-13 — `admin_stats` endpoint performs a full Redis key scan (`scan_iter`)

**Location:** `backend/app/routers/internal.py` L229-233

**Finding:**
```python
async for key in redis.scan_iter(f"quota:tokens:*:{today_str}"):
```
`SCAN` is non-blocking in Redis but iterates over the full keyspace. As user count grows, this becomes a slow, resource-intensive operation that can hold the async event loop. Running this on the same Redis instance as rate limiting and job queues degrades other operations.

**Fix:** Maintain a running counter per day in a separate Redis key (`stats:tokens:total:{today_str}`) and increment it when user quotas are checked. The admin stats endpoint then reads O(1) keys instead of scanning the full keyspace.

---

### 🟠 HIGH-14 — `pyproject.toml` does not pin dependency versions; production images are non-reproducible

**Location:** `backend/pyproject.toml`

**Finding:** Nearly all dependencies use `>=` version constraints with no upper bound:
```toml
"fastapi>=0.111",
"redis>=5.0.0",
"openai",  # no version constraint at all
```
This means two production builds weeks apart can produce different images with different dependency versions, including potentially **breaking changes or security patches that break the application**.

**Fix:** Pin all dependencies to exact versions in `pyproject.toml` (or better, generate a lock file with `uv lock` and commit `uv.lock`). The CI `uv sync` already reads from lockfile if present — do `uv lock` once and commit the result.

---

## Section 3: Backend Architecture

### 🟡 MED-1 — `from sqlalchemy import func` imported inside the route body

**Location:** `backend/app/routers/query.py` L108

**Finding:**
```python
from sqlalchemy import func
chat.updated_at = func.now()
```
Module-level imports placed inside function bodies are an anti-pattern. They hide dependencies, are slower (import machinery runs every call, though Python caches after first import), and make the import graph harder to trace for static analysis tools (mypy, ruff).

**Fix:** Move all imports to the top of `query.py`. Additionally, `uuid`, `update`, `func`, `Chat`, and `Message` are all imported inside `_sse_generator`'s `finally` block (lines 297-301). Move them all to the module top-level.

---

### 🟡 MED-2 — `check_and_increment_query_usage` is called before chat validation

**Location:** `backend/app/routers/query.py` L64-70

**Finding:**
```python
await check_and_increment_query_usage(user_id=str(current_user.id))  # quota consumed here
chat, valid_uuids, missing_ids = await validate_chat_for_query(...)  # may raise 404
```
If `validate_chat_for_query` raises (chat not found, wrong user), the query quota has already been incremented. The user loses a query for nothing.

**Fix:** Perform validation first, then increment the counter only after all pre-conditions pass.

---

### 🟡 MED-3 — Chat title updated via attribute assignment and `func.now()` on a managed object

**Location:** `backend/app/routers/query.py` L105-110

**Finding:**
```python
if chat.title == "New Chat":
    chat.title = body.question[:50].strip()
from sqlalchemy import func
chat.updated_at = func.now()
await db.commit()
```
Using `func.now()` on an attribute of a loaded ORM object causes SQLAlchemy to generate a `server_default` call on the *next flush*, but the value won't be populated on the Python object until after a refresh. Then, in the `finally` block, `updated_at` is updated again via a raw `UPDATE` statement. This means `updated_at` is touched twice in the same request, and the first touch may not do what's expected.

**Fix:** Use `onupdate=func.now()` at the model level (already present on `Document`) and simply let SQLAlchemy handle timestamps automatically. Remove the manual `chat.updated_at = func.now()` line.

---

### 🟡 MED-4 — Worker `tasks.py` uses legacy `db.query()` style ORM

**Location:** `backend/app/workers/tasks.py` L92-98

**Finding:**
```python
stale_docs = (
    db.query(Document)
    .filter(Document.status == DocumentStatus.PENDING_UPLOAD.value, ...)
    .all()
)
```
The rest of the codebase uses the modern `select(Model)` + `db.execute()` pattern. `db.query()` is the SQLAlchemy 1.x legacy API, deprecated in SQLAlchemy 2.x. Mixing both styles creates confusion and risks future deprecation warnings/breakage.

**Fix:** Migrate to `select(Document).where(...)` + `db.execute().scalars().all()` consistently. Note: the worker uses a sync `Session`, so the correct pattern is `db.scalars(select(Document).where(...)).all()`.

---

### 🟡 MED-5 — `CONTEXT_TOKEN_BUDGET` (3,000) is not config-driven

**Location:** `backend/app/services/prompt.py` L17

**Finding:** `CONTEXT_TOKEN_BUDGET = 3_000` is a hardcoded constant. Changing it requires a code change and redeploy. This is a key RAG tuning parameter (trade-off between context quality and API cost/latency).

**Fix:** Move to `settings` in `config.py`:
```python
CONTEXT_TOKEN_BUDGET: int = 3000
HISTORY_TOKEN_BUDGET: int = 1500
```
The budget for history (`1500`) in `prompt.py` L112 is similarly hardcoded.

---

### 🟡 MED-6 — `_cleanup_stale_pending_uploads` always writes `attempt=1` to `job_logs`

**Location:** `backend/app/workers/tasks.py` L147-154

**Finding:**
```python
log = JobLog(id=uuid.uuid4(), document_id=doc.id, attempt=1, ...)
```
The `attempt` field is always `1` for stale cleanup failures. The `JobLog.attempt` field is presumably designed to track retry count for ingest jobs, but here it's repurposed misleadingly.

**Fix:** For cleanup-initiated failures, use `attempt=0` (or a dedicated sentinel value) to distinguish "system cleanup failure" from "ingest job attempt #1 failure." Alternatively, add a `source: str` column to `job_logs` (`source = "ingest_worker" | "stale_cleanup"`).

---

### 🟡 MED-7 — `_ALLOWED_TRANSITIONS` map is defined separately from the enum

**Location:** `backend/app/models/document.py` L38-44

**Finding:** The transition map is a module-level dict. If a new `DocumentStatus` value is added, Python won't automatically require updating the map — a missing entry would cause a `KeyError` at runtime only when that transition is attempted.

**Fix:** Add a validation at module load time:
```python
assert set(_ALLOWED_TRANSITIONS.keys()) == set(DocumentStatus), \
    "Missing transitions for some DocumentStatus values"
```
This turns a runtime bug into an import-time crash, caught immediately in tests and CI.

---

## Section 4: Database

### 🟡 MED-8 — Missing IVFFlat (or HNSW) index on `chunks.embedding`

**Location:** `backend/alembic/versions/0001_initial_schema.py` L110-113

**Finding:** The schema comment says "Add IVFFlat index in migration 002 after your first real data load." This migration never materialized in the `versions/` directory. The `chunks` table **has no vector index**. Every similarity search performs a full sequential scan of all `1536`-dimensional vectors owned by the user.

For small datasets this is acceptable, but at even a few thousand chunks the query cost grows linearly. For 10,000+ chunks, queries will noticeably slow.

**Fix:** Create migration `0008_add_embedding_index.py`:
```sql
-- Use HNSW (preferred over IVFFlat — no training phase, better recall)
CREATE INDEX idx_chunks_embedding_hnsw ON chunks
USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);
```
(HNSW is available in pgvector ≥ 0.5.0; IVFFlat is the alternative for older versions.)

---

### 🟡 MED-9 — `updated_at` on the `documents` table is not guaranteed to refresh on status changes

**Location:** `backend/app/models/document.py` L79-84

**Finding:** `onupdate=func.now()` in SQLAlchemy only fires for ORM-tracked updates. The cleanup task in `tasks.py` manually sets `doc.updated_at = datetime.now(timezone.utc)` — which correctly updates it. However, some paths may use `db.execute(update(Document).where(...).values(status=...))` (bulk update), which bypasses ORM triggers and `onupdate`. The `updated_at` would then remain stale.

**Fix:** For all raw `UPDATE` statements, explicitly include `updated_at = func.now()` in the `values()` call. Consider adding a PostgreSQL trigger as the authoritative guard:
```sql
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$ BEGIN NEW.updated_at = NOW(); RETURN NEW; END; $$
LANGUAGE 'plpgsql';
CREATE TRIGGER update_documents_updated_at BEFORE UPDATE ON documents
  FOR EACH ROW EXECUTE PROCEDURE update_updated_at_column();
```

---

### 🟡 MED-10 — One stale migration file uses a non-sequential timestamp-based name

**Location:** `backend/alembic/versions/ef85fde67e77_add_password_resets_table.py`

**Finding:** All migrations use sequential numeric names (`0001` through `0007`) except one: `ef85fde67e77_add_password_resets_table.py`, which uses Alembic's auto-generated hash-based name. This breaks the visual ordering convention and makes the migration history harder to read.

**Fix:** Rename to `0008_add_password_resets_table.py` (or the appropriate sequence number) and update `revision` / `down_revision` fields accordingly. This is a non-breaking change since Alembic tracks revision IDs, not filenames.

---

## Section 5: Frontend

### 🔵 LOW-1 — `window.location.href` redirect bypasses Next.js router state

**Location:** `frontend/src/contexts/AuthContext.tsx` L164

**Finding:**
```javascript
window.location.href = '/auth/login';
```
This is a hard browser redirect, which performs a full page reload, destroying all React state and Next.js prefetched routes. The rest of the codebase uses `router.push()` from `useRouter`. The inconsistency means the auth redirect path is slower and loses any navigation context.

**Fix:** Use `router.replace('/auth/login')` (not `push`, as you don't want the login page in history when the user came from an expired session). The `router.replace` call in the timer-based refresh failure (L87) is already correct.

---

### 🔵 LOW-2 — `sessionStorage.setItem` saves user data redundantly without benefit

**Location:** `frontend/src/contexts/AuthContext.tsx` L149

**Finding:**
```javascript
sessionStorage.setItem('pdftalk_user', JSON.stringify(user));
```
This saves the user object to `sessionStorage`, but it's never read back — not on session restore (which calls the API directly), not in `clearSession` (which only removes it). It's dead code that writes PII (`email`) to browser storage unnecessarily.

**Fix:** Remove the `sessionStorage.setItem` and `sessionStorage.removeItem` calls. The in-memory `AuthContext` state is the single source of truth.

---

### 🔵 LOW-3 — Polling side-effect triggers on every documents state change, not just additions

**Location:** `frontend/src/app/dashboard/documents/page.tsx` L305-315

**Finding:**
```javascript
useEffect(() => {
    documents.forEach((doc) => {
        if (doc.status === 'PENDING_UPLOAD' || ...) {
            startPolling(doc.document_id);
        }
    });
}, [documents, startPolling]);
```
This `useEffect` runs every time `documents` state changes (including when a poll update comes in). The `startPolling` guard `if (pollingControllers.current[docId]) return;` prevents duplicate polling, but the forEach itself iterates all documents on every update — O(n) on every state change. For a user with 50 documents, this runs on every single poll tick.

**Fix:** Track which documents are already being polled in a `Set` in state, and only call `startPolling` for newly added documents. Or separate the "start polling on initial load" logic from "start polling when new docs appear."

---

### 🔵 LOW-4 — `handleDelete` in `DocumentsPage` re-throws errors causing unhandled promise rejections

**Location:** `frontend/src/app/dashboard/documents/page.tsx` L343

**Finding:**
```javascript
throw err; // Re-throw to reset button state in DocumentCard
```
`handleDelete` is called from `DocumentCard.handleDelete` as `await onDelete(doc.document_id)` inside a try/finally. The throw correctly propagates to the finally block. But in React, an unhandled rejection in an event handler won't be caught by an Error Boundary — it surfaces as a console error. The `finally { setIsDeleting(false) }` in `DocumentCard` only runs if the error propagates, which it does, but this pattern is fragile.

**Fix:** Make `handleDelete` return a boolean success indicator instead of throwing. `DocumentCard` checks the return value to reset its state, and callers don't need to know about the error.

---

### 🔵 LOW-5 — `getUploadErrorMessage` ignores the `validationReason` field it was designed to use

**Location:** `frontend/src/lib/documents.api.ts` L253-261

**Finding:**
```javascript
export function getUploadErrorMessage(err: ApiError): string {
    if (err instanceof UploadApiError && err.validationReason) {
        return FILE_VALIDATION_MESSAGES[err.validationReason] ?? err.message;
    }
```
The `UploadApiError` is constructed in `uploadDocument()` at line 232 without ever setting `validationReason`:
```javascript
throw new UploadApiError(err.code, err.message, err.status, err.retryAfter);
// validationReason is never passed
```
The constructor has `validationReason` as an optional 5th parameter, but the call site doesn't pass it — so `err.validationReason` is always `undefined`, making the first branch of `getUploadErrorMessage` dead code.

**Fix:** The backend returns the `reason` field in `FILE_VALIDATION_FAILED` responses. Extract it from the backend error body and pass it as the 5th argument to `UploadApiError`. This requires reading the `reason` field in the API layer.

---

## Section 6: Infrastructure & DevOps

### 🟡 MED-11 — Nginx serves no `client_max_body_size` limit on the generic `/api/` block

**Location:** `infra/nginx/nginx.prod.conf` L229-240

**Finding:** The specific upload endpoints correctly set low `client_max_body_size` (4KB and 1KB). But the generic `/api/` block has no `client_max_body_size`, which means Nginx uses its default of **1MB**. Endpoints that accept larger bodies (e.g., chat message bodies with long question text, future endpoints) may be silently capped.

**Fix:** Add an explicit `client_max_body_size 64k;` to the generic `/api/` block. Tune as needed. Never rely on Nginx defaults in a production config.

---

### 🔵 LOW-6 — `docker-compose.yml` uses `restart: unless-stopped` without a health-check on the worker

**Location:** `docker-compose.yml` L134-163

**Finding:** The worker service has no `healthcheck:` directive. If the worker enters a deadlock or infinite loop without crashing (e.g., a stuck RQ job), Docker won't restart it because the process is still running. The worker also has `depends_on: postgres: condition: service_healthy` but no equivalent for checking RQ readiness.

**Fix:** Add a healthcheck that verifies the worker process is alive and the Redis connection is healthy:
```yaml
healthcheck:
    test: ["CMD", "python", "-c", "import redis; r=redis.from_url('redis://redis'); r.ping()"]
    interval: 30s
    timeout: 10s
    retries: 3
```

---

### 🔵 LOW-7 — `redis` maxmemory-policy is `noeviction` — correct for queues, but undocumented risk

**Location:** `docker-compose.yml` L91

**Finding:** `--maxmemory-policy noeviction` means when Redis hits its 96MB memory limit, **all writes fail**. This includes rate-limit counter updates, job enqueues, quota checks, and circuit breaker state updates. The result is cascading 503s across the entire API.

The policy is correct for an RQ job queue (you don't want jobs silently evicted), but the risk needs to be acknowledged and monitored. Currently no Prometheus alert fires when Redis memory usage approaches the limit.

**Fix:** Add a Prometheus alert in `prometheus_rules.yml`:
```yaml
- alert: RedisMemoryHigh
  expr: redis_memory_used_bytes / redis_memory_max_bytes_metric > 0.85
  for: 5m
  severity: warning
```

---

## Section 7: Observability & Testing

### 🔵 LOW-8 — CI coverage report is uploaded as an artifact but never gated

**Location:** `.github/workflows/ci.yml` L102-107

**Finding:**
```yaml
- name: Upload coverage
  uses: actions/upload-artifact@v4
  if: always()
  with:
    name: backend-coverage
    path: backend/coverage.xml
```
Coverage is measured and uploaded but there is no coverage threshold. A PR that drops coverage from 80% to 5% passes CI.

**Fix:** Add a `--cov-fail-under=N` flag to the pytest command (e.g., `uv run pytest --cov=app --cov-fail-under=70 --cov-report=xml`). Set the threshold to at least the current baseline.

---

### 🔵 LOW-9 — Trivy scan uses `@master` — a mutable tag reference

**Location:** `.github/workflows/ci.yml` L163

**Finding:**
```yaml
uses: aquasecurity/trivy-action@master
```
`@master` is a floating reference that will use whatever commit is at the tip of the `master` branch at the time the workflow runs. This is a supply-chain risk: a malicious commit to the `trivy-action` repository's `master` branch could execute arbitrary code in the CI runner.

**Fix:** Pin to a specific tag or SHA:
```yaml
uses: aquasecurity/trivy-action@v0.24.0  # or latest stable tag
```

---

## Section 8: Technical Debt & Polish

### 🟡 MED-3 (Redux) — README documents the old multipart upload endpoint

**Location:** `README.md` L231

**Finding:**
```
POST | /documents/upload | Upload a PDF document (creates ingestion job)
```
The README still documents the legacy `/documents/upload` endpoint. The actual API uses the 3-step presigned URL flow (`/documents/initiate-upload`, S3 PUT, `/documents/confirm-upload`). New developers and API consumers will be confused or attempt to use the deprecated endpoint.

**Fix:** Update the README API table to document the actual presigned URL flow. Remove reference to `/documents/upload`.

---

### Duplicate Dependencies

**Location:** `backend/pyproject.toml` L34-35

**Finding:** `rq` and `redis` appear twice in the dependency list. This is harmless but should be cleaned up.

---

### TODO Comments Documenting Active Production Risks

The codebase contains the following TODO comments that represent acknowledged, deferred security/operational issues. Each should have a tracking ticket:

| Location | TODO |
|---|---|
| `nginx.prod.conf` L1-4 | Enable HTTPS, add HSTS |
| `internal.py` L125 | `secure=False` cookie — flip on TLS |
| `internal.py` L140 | Same |
| `deploy.yml` L143 | Smoke test uses HTTP |
| `nginx.prod.conf` L244 | HTTPS server block commented out |

All of these are resolved by completing CRIT-1 (TLS). They should be tracked as a single milestone.

---

## Consolidated Priority Table

| Priority | Finding | Effort |
|---|---|---|
| 🔴 | CRIT-1: Enable TLS/HTTPS end-to-end | Medium (1–2 days) |
| 🔴 | CRIT-2: Fix admin session token security | Small (2–4 hours) |
| 🔴 | CRIT-3: Block Swagger UI in production | Trivial (<1 hour) |
| 🔴 | CRIT-4: Remove hardcoded production IP | Trivial (<1 hour) |
| 🔴 | CRIT-5: Validate /metrics endpoint is blocked | Small (1–2 hours) |
| 🔴 | CRIT-6: Move test deps to dev group | Trivial (<1 hour) |
| 🔴 | CRIT-7: Fix SSH known_hosts in deploy | Small (1–2 hours) |
| 🟠 | HIGH-1: Replace python-jose with PyJWT | Small (2–4 hours) |
| 🟠 | HIGH-2: Add DB CHECK constraint on status | Trivial (1 migration) |
| 🟠 | HIGH-3: Rate limiter fail-open strategy | Small (2–4 hours) |
| 🟠 | HIGH-8: Use container registry for deploys | Medium (4–8 hours) |
| 🟠 | HIGH-9: Fix token quota TTL to midnight | Trivial (<1 hour) |
| 🟠 | HIGH-14: Pin dependency versions + lock file | Small (2 hours) |
| 🟡 | MED-8: Add HNSW index on chunks.embedding | Trivial (1 migration) |
| 🟡 | MED-1: Move inline imports to module top | Trivial (<30 min) |
| 🟡 | MED-2: Validate before incrementing quota | Trivial (<30 min) |
| 🟡 | MED-5: Move token budgets to settings | Trivial (<1 hour) |

---

*Report generated from full codebase review of PDFTalk v2.0.*
*Reviewed files: `main.py`, `config.py`, `auth.py`, `tokens.py`, `documents.py`, `query.py`, `retrieval.py`, `prompt.py`, `user_service.py`, `document_service.py`, `tasks.py`, `internal.py`, `security.py`, `logging.py`, `openai_client.py`, `rate_limit.py`, `api.ts`, `documents.api.ts`, `AuthContext.tsx`, `nginx.prod.conf`, `docker-compose.yml`, `ci.yml`, `deploy.yml`, and all Alembic migrations.*
