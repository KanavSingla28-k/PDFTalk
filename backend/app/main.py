from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.db.session import check_db_connection, engine
from app.exceptions import register_exception_handlers
from app.middleware.logging import RequestLoggingMiddleware
from app.middleware.security import SecurityHeadersMiddleware
from app.routers.auth import router as auth_router
from app.routers.documents import router as document_router
from app.routers.query import router as query_router
from app.routers.health import router as health_router
from app.utils.logging import configure_logging
from app.utils.redis_client import get_pool, get_redis


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- startup ---
    configure_logging()          # structlog must be configured before any log calls

    await check_db_connection()

    r = get_redis()
    await r.ping()

    yield

    # --- shutdown ---
    await engine.dispose()
    await get_pool().aclose()


app = FastAPI(
    title="PDFTalk API",
    version="0.1.0",
    docs_url="/docs" if settings.APP_URL.startswith("http://localhost") else None,
    lifespan=lifespan,
)

register_exception_handlers(app)
app.include_router(auth_router)
app.include_router(document_router)
app.include_router(query_router)
app.include_router(health_router)

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
if settings.APP_URL.startswith("http://localhost"):
    for port in ["3000", "3001", "3002"]:
        allowed_origins.append(f"http://localhost:{port}")
        allowed_origins.append(f"http://127.0.0.1:{port}")
allowed_origins = list(set(allowed_origins))

app.add_middleware(                          # added last = outermost
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
    max_age=600,
)
