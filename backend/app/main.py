import ipaddress
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

from app.core.config import settings
from app.core.sentinel import guard as sentinel_guard
from app.core.sentinel import redis as sentinel_redis
from app.db.session import check_db_connection, engine
from app.exceptions import register_exception_handlers
from app.middleware.logging import RequestLoggingMiddleware
from app.middleware.security import SecurityHeadersMiddleware
from app.routers.auth import router as auth_router
from app.routers.chats import router as chat_router
from app.routers.documents import router as document_router
from app.routers.health import router as health_router
from app.routers.internal import router as internal_router
from app.routers.query import router as query_router
from app.utils.logging import configure_logging
from app.utils.redis_client import get_pool, get_redis


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # --- startup ---
    configure_logging()  # structlog must be configured before any log calls

    await check_db_connection()

    r = get_redis()
    await r.ping()  # type: ignore[misc]

    # Sentinel rate limiter initialization
    await sentinel_redis.assert_noeviction()
    await sentinel_guard.load_scripts()

    yield

    # --- shutdown ---
    await engine.dispose()
    await get_pool().aclose()
    await sentinel_redis.aclose()


_docs_url = None if settings.is_production else "/docs"
_redoc_url = None if settings.is_production else "/redoc"
_openapi_url = None if settings.is_production else "/openapi.json"

app = FastAPI(
    title="PDFTalk API",
    version="1.0.0",
    docs_url=_docs_url,
    redoc_url=_redoc_url,
    openapi_url=_openapi_url,
    lifespan=lifespan,
)

register_exception_handlers(app)
app.include_router(auth_router)
app.include_router(document_router)
app.include_router(query_router)
app.include_router(chat_router)
app.include_router(health_router)
app.include_router(internal_router)


# ── Prometheus metrics ────────────────────────────────────────────────────────
# Exposes /metrics for Prometheus scraping (internal network only — not proxied
# through Nginx). Instrumentator must be set up after routers are registered
# so it sees all routes for labelling, but before middleware is added.
def _require_internal_ip(request: Request) -> None:
    """Ensure the request comes from an internal network IP and is not proxied."""
    # Nginx adds X-Forwarded-For if it proxies the request from the public internet.
    if "x-forwarded-for" in request.headers:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    client_ip = request.client.host if request.client else ""
    try:
        ip_obj = ipaddress.ip_address(client_ip)
        if not ip_obj.is_private and not ip_obj.is_loopback:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


Instrumentator(
    should_group_status_codes=True,       # 2xx/4xx/5xx, not individual codes
    should_ignore_untemplated=True,       # drops /metrics itself from its own metrics
    excluded_handlers=["/live", "/ready", "/metrics"],
).instrument(app).expose(
    app, endpoint="/metrics", include_in_schema=False, dependencies=[Depends(_require_internal_ip)]
)

# ---------------------------------------------------------------------------
# Middleware stack — added in reverse execution order.
# Request path:  RequestLogging → SecurityHeaders → CORS → route handler
# Response path: route handler → CORS → SecurityHeaders → RequestLogging
#
# RequestLogging is outermost so it:
#   - generates request_id before anything else runs
#   - measures total wall-clock time including all middleware
#   - catches exceptions from every inner layer
# ---------------------------------------------------------------------------
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestLoggingMiddleware)

allowed_origins = [settings.APP_URL]


app.add_middleware(  # added last = outermost
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "PATCH", "PUT"],
    allow_headers=["Authorization", "Content-Type"],
    max_age=600,
)
