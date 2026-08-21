# Core AGENTS.md

Context for the core configuration and Sentinel rate limiting layer.

## Purpose

Handles the central configuration for the backend via `pydantic-settings` and configures the Sentinel rate limiter.

## Configuration: `config.py`

- Uses `Settings(BaseSettings)` to load env vars from `.env.local` or `.env.docker` (defined by `ENV_FILE`).
- **`ENVIRONMENT`**: Defaults to `"production"` as a fail-safe. Set to `"development"` in `.env.local`.
- Handles validation (e.g., `JWT_SECRET_KEY` must be $\ge$ 32 chars).
- Configures limits: `MAX_DOCS_PER_USER`, token budgets, `RETRIEVAL_TOP_K`, and `RETRIEVAL_MAX_DISTANCE` (default 0.70).

## Rate Limiting: `sentinel.py`

All rate limiting uses **Sentinel v1.2.0** (`sentinel-rate-limiter`).
- Uses a dedicated Redis instance (see `docker-compose.yml`) which MUST have `maxmemory-policy noeviction`.
- **Identity Models**: 
  - Authenticated: Uses hashed JWT `sub`.
  - Anonymous: Uses dual-bucket HMAC-signed device cookie (`pdftalk_anon_id`) AND client IP.
- **Failure Mode**: All policies use `fail_open` with a per-process fallback limit. If Redis fails, Sentinel allows a capped amount of traffic.
- Sentinel converts its internal exceptions to PDFTalk typed exceptions in `_sentinel_exception_handler`.
- **Seven Policies**:
  1. `pdftalk.auth.register` (5/hr)
  2. `pdftalk.auth.resend` (5/hr)
  3. `pdftalk.auth.login` (10/min)
  4. `pdftalk.auth.reset` (3/hr)
  5. `pdftalk.documents.upload` (5/min, sliding window)
  6. `pdftalk.query.ask` (20/min, sliding window)
  7. `pdftalk.chats.create` (10/min, sliding window)

## Related Context

- App context: `../AGENTS.md`
