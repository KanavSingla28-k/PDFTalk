# App AGENTS.md

Context for the main application package (`backend/app`).

## Purpose

This is the core directory of the PDFTalk backend. It contains the FastAPI application setup, configurations, exceptions, database session management, and the middleware stack.

## Entry Point: `main.py`

`main.py` is the application entry point.
- Initializes the `FastAPI` app.
- **Lifespan**: Configures `structlog`, checks DB connectivity, pings Redis, asserts Sentinel Redis `noeviction` policy, and loads Sentinel Lua scripts.
- **Middleware Order**: `RequestLoggingMiddleware` → `SecurityHeadersMiddleware` → `CORSMiddleware`. (Executed in reverse order of addition; `RequestLoggingMiddleware` is outermost).
- Registers routers from `app.routers`.
- Configures Prometheus metrics using `Instrumentator`, blocking external access to `/metrics` by enforcing internal IP checks.

## Exceptions: `exceptions.py`

Defines the typed exception hierarchy. 
- All services **must** raise these typed exceptions rather than FastAPI's `HTTPException`.
- `main.py` registers global exception handlers that map these typed exceptions to standardized JSON HTTP responses shaped like `{"error": "CODE", "message": "..."}`.

## Middleware

- `middleware/logging.py`: Injects a UUID `request_id` into `structlog` contextvars and the `X-Request-ID` response header. Strips query strings from logs to prevent token leakage.
- `middleware/security.py`: Adds security headers. Note: HSTS is set by Nginx, so it is *not* duplicated here.

## Child Contexts

- `core/`: Configuration and Sentinel rate limiting. See `core/AGENTS.md`.
- `db/`: Database setup.
- `routers/`: API endpoints. See `routers/AGENTS.md`.
- `services/`: Business logic. See `services/AGENTS.md`.
- `models/`: DB Models and Schemas. See `models/AGENTS.md`.
- `workers/`: Background task processing. See `workers/AGENTS.md`.
- `auth/`: Authentication logic. See `auth/AGENTS.md`.

## Related Context

- Backend context: `../AGENTS.md`
