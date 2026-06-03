from app.core.config import settings
from fastapi import FastAPI
from contextlib import asynccontextmanager
from app.db.session import check_db_connection, engine

@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- startup ---
    await check_db_connection()
    yield
    # --- shutdown ---
    await engine.dispose()  # Cleanly close all pooled connections

app = FastAPI(lifespan=lifespan)

@app.get("/health")
def health():
    return {"status": "ok"}