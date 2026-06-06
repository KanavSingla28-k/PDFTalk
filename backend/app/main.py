from app.core.config import settings
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.db.session import check_db_connection, engine
from app.exceptions import register_exception_handlers
from app.utils.redis_client import get_pool, get_redis
from app.routers.auth import router as auth_router
from app.routers.documents import router as document_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- startup ---
    await check_db_connection()
    
    r = get_redis()          # get the shared client
    await r.ping()           # raises ConnectionError if Redis is unreachable
    
    yield
    
    # --- shutdown ---
    await engine.dispose()
    await get_pool().aclose()  # close Redis pool cleanly

app = FastAPI(
    title="PDFTalk API",
    version="0.1.0",
    docs_url="/docs" if settings.APP_URL.startswith("http://localhost") else None,
    lifespan=lifespan
)

register_exception_handlers(app)
app.include_router(auth_router)
app.include_router(document_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.APP_URL],
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
    max_age=600,
)

@app.get("/health")
def health():
    return {"status": "ok"}
