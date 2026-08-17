# PDFTalk — Sentinel Integration Test Report

## Executive Summary

**Status: PASS WITH LIMITATIONS**

The Sentinel rate limiter (`sentinel` v0.1.0, vendored) is **genuinely working inside PDFTalk**. All 8 verification scenarios produced the expected behavior against the real Dockerized application:

- Sliding-window policy `pdftalk.documents.upload` (limit 3 / 60 s / tenant) enforced end-to-end via the real HTTP endpoint `POST /documents/upload`.
- The 4th request in a window returns `429 {"detail":"rate limit exceeded"}` and does **not** create an S3 object, DB document, or queue job.
- `FailMode.FAIL_CLOSED` verified: Sentinel Redis down → `503 {"detail":"rate limiter unavailable"}` with no upload side effects.
- Recovery verified: Redis restarted → next request `202`; Lua scripts lost on restart are re-loaded on demand (`NoScriptError` recovery), proven by `SCRIPT EXISTS` going `0 0 → 0 1` across the restart.
- The limit is shared across processes via Redis (two real API processes → combined 3-request limit), and is scoped per tenant (two users → independent counters, verified by Redis keys).
- No JWT, Authorization header, or Redis password appears in any log or metric.

**Limitations** (none block the integration):

1. A validly signed JWT whose `sub` is not a UUID string produces an unhandled `500` (pre-existing PDFTalk issue in `get_current_user`, `backend/app/auth/dependencies.py:78` — `uuid.UUID(user_id_str)` is unguarded). Sentinel is not at fault; PDFTalk's auth dependency runs before the guard.
2. PDFTalk's structlog configuration drops Sentinel's structured `extra` fields (`tenant_hash`, `endpoint_id`, `decision_reason`, `latency_micro`, `breaker_state`) from the `sentinel` warning log line. Denied decisions are still observable via Prometheus metrics (`sentinel_decisions_total`), which do carry the `decision_reason` label.
3. Sentinel's 20 ms socket timeouts can trip transiently under load (one connect timeout observed and recovered within seconds). Expected for a fail-closed design; noted for ops.

---

## Environment

| Item | Value |
|---|---|
| Date/time (local) | 2026-08-17T12:35–12:55 IST (UTC+05:30) |
| Date/time (UTC, log timestamps) | 2026-08-17T07:05–07:18Z |
| Docker images | `pdftalk-api:latest`, `redis:7-alpine` (both Redis instances), `pgvector/pgvector:pg15` |
| Python (API container) | 3.12.14 |
| Sentinel package | 0.1.0 (vendored wheel `backend/vendor/sentinel-0.1.0-py3-none-any.whl`) |
| Redis server | 7.4.9 (both `pdftalk-redis` and `pdftalk-sentinel-redis`) |
| PostgreSQL | 15.18 (pgvector image) |
| PDFTalk commit | `f79ad3166983126aa5888a0a9ea521f45bb62895` |
| Services running | `pdftalk-api-1`, `pdftalk-postgres`, `pdftalk-redis`, `pdftalk-sentinel-redis` |

No secrets are included in this report. JWT tokens were generated inside the API container with the application's configured `JWT_SECRET_KEY`/`JWT_ALGORITHM` and stored only in shell-session variables / a temp directory outside the repository.

Raw outputs: `docs/sentinel/evidence/*`.

---

## Configuration Tested

Actual policy loaded from `backend/app/core/sentinel.py` (verified in the running app):

| Setting | Value |
|---|---|
| endpoint_id | `pdftalk.documents.upload` |
| algorithm | `AlgorithmType.SLIDING_WINDOW` |
| fail_mode | `FailMode.FAIL_CLOSED` |
| limit | 3 |
| window_size_micro | 60,000,000 (60 s) |
| fallback_rate_per_process_micro | 1 (unused — fail-closed) |
| policy_version | 1 |

Sentinel Redis configuration (verified live):

| Setting | Value |
|---|---|
| maxmemory | 134217728 (128 MB) |
| maxmemory-policy | noeviction |

Lua scripts (SHA1 of script bodies, verified via `SCRIPT EXISTS`):

| Script | SHA1 | Present at startup |
|---|---|---|
| token_bucket | `2d6cf97450738b4fd1c37af44d625158288f6610` | 1 |
| sliding_window | `63a6d7d7423bb84fb0fc6a030c00b1557a8cf851` | 1 |

The API startup log prints `Sentinel scripts loaded: 2d6cf97450738b4fd1c37af44d625158288f6610 63a6d7d7423bb84fb0fc6a030c00b1557a8cf851` — this line is only emitted after `guard.load_scripts()` returns, i.e. after `_scripts_loaded` is set to `True` in the running process. Every request would otherwise raise `RuntimeError("Sentinel scripts are not loaded...")`.

---

## Test Results

| Test | Expected | Actual | Status |
|---|---|---|---|
| Normal request | 202 | 202 × 3 | PASS |
| Rate limit | 4th → 429 | 4th → 429 `{"detail":"rate limit exceeded"}` | PASS |
| Redis failure | 503 | 503 `{"detail":"rate limiter unavailable"}` | PASS |
| Redis recovery | 202 | 202 | PASS |
| Multi-process | shared 3-request limit | 202,202,202 then 429 across 2 processes | PASS |
| Multi-user | independent limits | A: 3×202 then 429; B: 1st 202 | PASS |
| Authentication | expected auth behavior | 401s for missing/malformed/expired; 500 for non-UUID `sub` (pre-existing PDFTalk bug, see below) | PASS (with pre-existing issue) |
| Script reload | recovery | auto re-load + full cycle 202,202,202,429 post-restart | PASS |
| Observability | no secret leakage | no JWT/password in logs; metrics carry reasons | PASS |

### Detailed results

**Test 1 — Normal operation (user A, real HTTP, real Sentinel dependency)**
Four `POST /documents/upload` requests (valid PDF `sentinel-test.pdf`, 219 bytes, `%PDF` magic bytes):

| Req | Status | Request ID | Document created |
|---|---|---|---|
| 1 | 202 Accepted | `6b778267-e820-4072-af0c-7ae43772595e` | `4b5fe669-65bf-4348-8f44-6100feef7159` |
| 2 | 202 Accepted | `35bd707e-2f8e-4bd6-b718-c8c5cac8d735` | `99804e2d-40bf-47aa-a260-e4dc6a9dc5f0` |
| 3 | 202 Accepted | `745549f0-c66c-4529-8165-3c4707e57ba3` | `9af9b7fa-91e8-4b48-9745-d95353c5f9d5` |
| 4 | 429 Too Many Requests | `4ed4d1bd-0cb1-4c76-84a7-d868932a06ef` | none |

For request 4 the API log shows `"event": "rate limit decision denied"` (logger `sentinel`) and `request.completed` with `status_code: 429` (`duration_ms: 5`), and **no** `s3_upload_success` / `document_s3_uploaded` / `document_db_created` / enqueue events. The upload handler did not execute.

**Test 2 — Shared Redis state representation**

Key generated:
```
sentinel:v1:48716045f3d524fe08e166a27636d5f8d7119869a3eec43a9a00f171398c22ff:pdftalk.documents.upload:1
```
- `48716045...` = `sha256("941a368b-5699-45e9-9286-df3d0a0a7b5b")` (verified independently).
- `TYPE` = **string** (a plain Redis STRING, not a ZSET/hash — this is the representation used by the sentinel sliding-window Lua script).
- `VALUE` = `3:0:1786950523332283` → `current:previous:window_start_micro` per the Lua implementation (current window count = 3, previous window count = 0).
- `TTL` = 108 s after the burst (~2 windows = 120 s minus elapsed time; the script sets TTL to 2×window).
- `MEMORY USAGE` = 176 bytes.

Sliding-window state is a single string key holding `current:previous:window_start_micro`, expiring after two windows. Denied requests never write (count stays 3 after the 429 — verified).

**Test 3 — Fail-closed (Sentinel Redis down)**

- `docker stop pdftalk-sentinel-redis`; ping fails.
- Upload → **503** `{"detail":"rate limiter unavailable"}` (request id `102f0256-ab9b-4e8e-8d6e-23b6da749264`, `duration_ms: 27`).
- API log shows `rate limit decision denied` (reason was `FAIL_CLOSED` — visible only in metrics; see observability note).
- No S3 upload, no DB document, no queue job for this request. DB row count for the test users unchanged.

This is correct for `FAIL_CLOSED`: the limiter denies rather than allowing traffic when the decision store is unavailable.

**Test 4 — Recovery**

- `docker start pdftalk-sentinel-redis` → `PONG`.
- `SCRIPT EXISTS` → `0 0` (scripts are in-memory only and were lost on restart).
- Upload → **202** (request id `fedc56d8-abb8-4353-a571-bf189c706f64`, document `8645fd78-c74b-4c76-a838-add54c68e7a7`). `SCRIPT EXISTS` afterwards → `0 1`: the `sliding_window` script was re-loaded on demand by the `ScriptLoader` `NoScriptError` recovery path.

**Test 5 — Multi-process / shared limit**

Second real API process started inside the same container (`uvicorn app.main:app --port 8001`, PID 962; primary app PID 980 on port 8000 — both independent Python processes, same code, same Sentinel Redis). No infrastructure was destroyed; the second process was killed after the test.

Sequence (same user A, Redis state reset first):

| Step | Process (port) | Status | Request ID |
|---|---|---|---|
| 1 | A (8000) | 202 | `1c725406-0f1f-4edb-a01f-089cafcf09b2` |
| 2 | B (8001) | 202 | `19e16338-9ee4-42ab-b96d-2fa55ff046bb` |
| 3 | A (8000) | 202 | `d6f4fea7-5de6-4146-a77e-ec398854b86b` |
| 4 | B (8001) | 429 | `24a11079-29aa-4bb9-9579-869f8ea2f828` |

Post-state: a single key with `VALUE='3:0:...'` — one shared counter for both processes. **The limit is 3 total, not 3 per process** — the limiter state lives in Sentinel Redis, not in per-process memory.

**Test 6 — Multi-user independence**

User A (`941a368b...`) and user B (`e3d821da...`) both active+verified. State reset. Sequence:
- A: 202, 202, 202, 429 (documents `b6d35570`, `b7523300`, `070a6012`).
- B: 202 (`8c7e5784-5f14-4114-bbf2-c2c3a71ec11c`).

Redis held two keys with distinct hashes: A → `48716045...` (`3:0:...`), B → `7a0a7c6d...` (`1:0:...`). `sha256(userB)` verified to equal `7a0a7c6d9535925fba597a4b97a3fb9b53085b77ce1597228a5e76acbffc6f8e`. Limits are scoped by tenant (hashed user id) + endpoint + policy version.

**Test 7 — Authentication interaction**

| Case | Status | Body |
|---|---|---|
| Missing Authorization header | 401 | `{"error":"INVALID_TOKEN","message":"Authorization header is missing or not Bearer"}` |
| Malformed JWT (`not.a.jwt`) | 401 | `{"error":"INVALID_TOKEN","message":"Invalid access token: ..."}` |
| Expired JWT (signed, exp in past) | 401 | `{"error":"TOKEN_EXPIRED","message":"Access token has expired"}` |
| Validly signed JWT, `sub` = `not-a-valid-uuid` | **500** | `Internal Server Error` (plain text) |
| Validly signed JWT, well-formed but nonexistent user UUID | 401 | `{"error":"INVALID_TOKEN","message":"Could not validate credentials"}` |

The 500 is **not a Sentinel defect**: dependency resolution order runs PDFTalk's `get_verified_user` first, and `get_current_user` (`backend/app/auth/dependencies.py:78`) calls `uuid.UUID(user_id_str)` unguarded — `ValueError: badly formed hexadecimal UUID string` (confirmed in the API log). Sentinel's own `verify_bearer_token` would accept the claim; the crash happens before the guard runs. This is a pre-existing PDFTalk robustness issue; no auth behavior was changed to make tests pass.

**Test 8 — Script reload / restart behavior**

`docker restart pdftalk-sentinel-redis`:
- `SCRIPT EXISTS` → `0 0` (scripts lost; note the rate-limit keys survived because Redis persisted an RDB snapshot — state is durable).
- Next upload (user B, key reset first) → **202**; `SCRIPT EXISTS` → `0 1` (sliding_window re-loaded on demand via `ScriptLoader.execute()`'s `NoScriptError` recovery).
- Full cycle after restart: 202, 202, 202, 429 — rate limiting continues to work correctly after Redis/script state changes.

`guard._scripts_loaded` verification: the startup log line proves `load_scripts()` completed in each process; additionally, any request served without loaded scripts would raise `RuntimeError` (all requests returned 2xx/4xx/5xx as designed, never a 500 from the guard).

---

## Observability

### What is recorded?

1. **Denied decisions → warning logs** (Sentinel `sentinel/observability.py`): stdlib `logging.getLogger("sentinel").warning("rate limit decision denied", extra={tenant_hash, endpoint_id, decision_reason, latency_micro, breaker_state})`.
2. **All decisions → Prometheus metrics** on the default registry (process-wide):
   - `sentinel_decisions_total{endpoint_id, decision_reason}` (counter)
   - `sentinel_evaluate_latency_microseconds{endpoint_id, decision_reason}` (histogram)
   - Exposed by the app at `/metrics` (gated to internal/loopback clients).
3. **PDFTalk request logs**: `request.completed` lines carry `status_code`, `request_id`, `user_id`, `duration_ms` for every request (200/202/429/503 all visible), plus the middleware-attached `request_id` (`X-Request-ID` header).

### Where is it recorded?

- Logs: container stdout (captured by Docker; in production this would go to the log aggregator).
- Metrics: in-process `prometheus_client` registry, exposed at `/metrics` for scraping.

### Who owns the data?

- Log lines: PDFTalk's `configure_logging()` (structlog) renders them; the `sentinel` logger is a foreign stdlib logger processed by `foreign_pre_chain`.
- Metrics: the API process's default Prometheus registry (owned by the app process; `PROMETHEUS_MULTIPROC_DIR` set for multiproc mode).

### Is anything sent outside the application?

**No.** The `sentinel` package contains no HTTP/telemetry export code (verified by grep: no `httpx`, `requests`, `urllib`, `opentelemetry`, `sentry`, `datadog`, or webhook references). Data only leaves the process via (a) the app's logs and (b) a Prometheus scrape of `/metrics` — both local, and neither is sent by Sentinel itself.

### Observed in this test run

- `sentinel_decisions_total{decision_reason="allowed",endpoint_id="pdftalk.documents.upload"} 3` and `{decision_reason="rate_limited",...} 1` observed at `07:09:52Z` after Test 1 — allowed **and** denied decisions are observable via metrics.
- Denial log line observed: `{"event":"rate limit decision denied","request_id":"...","user_id":"...","level":"warning","logger":"sentinel","timestamp":"..."}`.
- **Finding:** the `extra` fields (`tenant_hash`, `endpoint_id`, `decision_reason`, `latency_micro`, `breaker_state`) are **dropped** by PDFTalk's logging pipeline — `configure_logging()` uses `foreign_pre_chain=shared_processors` without a record-extra copier, so Sentinel's structured details don't reach the emitted JSON. Denial *existence* and the affected user/request are still visible; the machine-readable reason is only in metrics. This is a PDFTalk-side integration nuance (the fix would be in `backend/app/utils/logging.py`), not a Sentinel bug.

### Secret-leak checks (grep over full API logs)

- JWT-like strings (`eyJ...`) in logs: **0**
- Sentinel Redis password / app Redis password in API logs: **0** (both were grepped for; no occurrences)
- JWT tokens never written to any repo file; evidence files contain redacted/absent credentials.

---

## Redis Evidence

| Check | Result |
|---|---|
| `pdftalk-redis` ping | `PONG` |
| `pdftalk-sentinel-redis` ping | `PONG` |
| maxmemory | `134217728` (128 MB) |
| maxmemory-policy | `noeviction` |
| Generated keys | `sentinel:v1:<sha256(tenant)>:pdftalk.documents.upload:1` |
| Data structure | STRING, value `current:previous:window_start_micro` |
| TTL | 2 × window (120 s), refreshed on each allowed request; keys expired on their own post-test (observed 0 keys ~2 min after the last burst) |
| Script SHAs | `token_bucket`=`2d6cf97450738b4fd1c37af44d625158288f6610`, `sliding_window`=`63a6d7d7423bb84fb0fc6a030c00b1557a8cf851` (`SCRIPT EXISTS` → `1 1` at startup) |

---

## Failure Behavior

Redis unavailable → **503 `rate limiter unavailable`**, correct for `FAIL_CLOSED`: when the rate-limit decision store cannot be reached, the request is denied rather than admitted unchecked. Verified with a real container stop; the 503 returned in ~27 ms (Sentinel's 20 ms socket timeouts) and the upload pipeline (S3/DB/queue) never ran.

---

## Recovery Behavior

`docker start` → `PONG` → next upload `202`. Two independent recovery mechanisms observed:

1. **Connection recovery**: the API reconnects to Redis with no restart required.
2. **Script recovery**: Redis restart flushes loaded Lua scripts (`SCRIPT EXISTS` → `0 0`); `ScriptLoader.execute()` catches `NoScriptError`, re-issues `SCRIPT LOAD`, and retries — observed live (`0 1` immediately after the first post-restart request).

---

## Security Observations

- **JWT not logged**: no token material appears in any log line or saved evidence.
- **Redis password not logged**: neither the Sentinel Redis password nor the app Redis password appears in API logs (grepped; both dev passwords are kept out of the report and evidence).
- **Secrets not committed**: JWT tokens lived only in `$env:` variables and `%TEMP%\opencode\sentinel_token_*.txt` (outside the repo); `git status` shows no `.env` modifications.
- **User identity handling**: Sentinel hashes the tenant (`sha256(user_id)`) for the Redis key (`sentinel:v1:<hash>:...`). Note: PDFTalk's `RequestLoggingMiddleware` binds the **raw `user_id`** into structlog contextvars, so the `sentinel` denial log line also carries the raw user UUID — consistent with every other PDFTalk log line (by design), not a new exposure.
- **Hashed tenant key behavior**: verified — `sentinel:v1:48716045...` == `sha256(userA)`, `sentinel:v1:7a0a7c6d...` == `sha256(userB)`.
- **No outbound telemetry** from the Sentinel package (code-inspected).

---

## Bugs / Issues Found

### Real Sentinel integration bugs
**None.** Sentinel behaved per its documented contract in every scenario (sliding window, fail-closed, script reload, per-tenant keys, observability).

### Test-environment issues
1. **uvicorn `--reload` + scratch files**: writing helper scripts under `backend/` (mounted at `/app`) triggered `WatchFiles` reloads of the API process (observed 5 reloads). This reset in-process Prometheus counters mid-testing (metrics are process-wide; a scrape taken right after Test 1 captured the `3 allowed / 1 rate_limited` state). It did not affect rate-limit correctness (state lives in Redis), and both processes in the multi-process test were confirmed live at the time of each request.
2. **Transient Sentinel Redis connect timeout** during a state-inspection call (20 ms connect timeout under load); retry succeeded immediately.

### Pre-existing PDFTalk issues (not Sentinel bugs)
1. **500 on non-UUID `sub`**: `get_current_user` (`backend/app/auth/dependencies.py:78`) raises unhandled `ValueError` from `uuid.UUID(...)` for a validly-signed JWT with a non-UUID `sub` → `500 Internal Server Error`. Should map to 401. (Auth robustness gap predating this work; no changes made.)
2. **Sentinel structured log fields dropped**: `configure_logging()`'s `foreign_pre_chain` lacks an `ExtraAdder`-style copier, so `tenant_hash`/`endpoint_id`/`decision_reason`/`latency_micro`/`breaker_state` don't appear in the `sentinel` log line. Denial existence + user + request id are visible; reasons are in metrics.

### Test artifacts
All artifacts from the test run were cleaned up (see below). No documents, S3 objects, or queue jobs remain.

---

## Test Artifacts

### Created (all cleaned)
- 17 `sentinel-test.pdf` documents in Postgres (rows `PENDING`) — 14 for user A, 3 for user B (incl. 6 from pre-existing manual verification).
- 17 S3 objects (`<user>/<document_id>/sentinel-test.pdf`).
- 17 RQ ingest jobs in `rq:queue:ingest` (worker container not running at test time).

### Cleanup performed (PDFTalk's normal mechanism)
- `DELETE /documents/{id}` (S3 object + DB row, verified `204` for all 17; S3 re-check via `head_object` → `404` for sampled keys).
- RQ job hashes removed and `rq:queue:ingest` drained (`LLEN` → 0) after confirming each job referenced a test document (`run_ingest(document_id='<test-doc>')`).
- Temp JWT files under `%TEMP%\opencode\` left in place (outside repo, not committed).

### Remaining artifacts
- None in Postgres, S3, or the ingest queue. Sentinel rate-limit keys auto-expired (TTL 120 s) — confirmed `0 keys`.

---

## Final Verdict

**PASS WITH LIMITATIONS**

Sentinel is genuinely protecting `POST /documents/upload` in the real application: correct sliding-window enforcement (3/60 s/tenant), correct fail-closed behavior (503 when Redis is down), correct recovery (202 after restart, including on-demand Lua script re-load), shared cross-process state, per-tenant isolation, and no secret leakage. The limitations are the pre-existing PDFTalk 500-on-non-UUID-sub auth gap, PDFTalk's logging pipeline dropping Sentinel's structured decision fields (reason still visible in metrics), and the operational note that Sentinel uses aggressive 20 ms Redis timeouts. None of these are defects in Sentinel itself.

---

## Reproducibility Notes

- Helper scripts used during the run lived in `backend/scratch/` (deleted after the run; they triggered uvicorn `--reload`).
- JWT generation was done inside the API container with the app's own `create_access_token`/`jwt.encode` using the configured `JWT_SECRET_KEY` + `JWT_ALGORITHM`.
- The multi-process test used a second `uvicorn` (port 8001) inside the existing container — no infrastructure was created or destroyed; it was killed post-test.
