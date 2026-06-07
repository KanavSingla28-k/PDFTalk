import asyncio
import time
from datetime import datetime, timezone

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.db.session import engine          # async engine, not get_db()
from app.utils.redis_client import get_redis
from app.utils.s3_client import s3_client

router = APIRouter(tags=["health"])

TIMEOUT = 0.5  # seconds per dependency check


async def _check_db() -> dict:
    start = time.monotonic()
    try:
        async with engine.connect() as conn:
            await asyncio.wait_for(conn.execute(text("SELECT 1")), timeout=TIMEOUT)
        latency_ms = round((time.monotonic() - start) * 1000)
        return {"status": "ok", "latency_ms": latency_ms}
    except Exception as e:
        latency_ms = round((time.monotonic() - start) * 1000)
        return {"status": "error", "latency_ms": latency_ms, "detail": str(e)}


async def _check_redis() -> dict:
    start = time.monotonic()
    try:
        r = get_redis()
        await asyncio.wait_for(r.ping(), timeout=TIMEOUT)
        latency_ms = round((time.monotonic() - start) * 1000)
        return {"status": "ok", "latency_ms": latency_ms}
    except Exception as e:
        latency_ms = round((time.monotonic() - start) * 1000)
        return {"status": "error", "latency_ms": latency_ms, "detail": str(e)}


async def _check_s3() -> dict:
    start = time.monotonic()
    try:
        # head_bucket is a blocking boto3 call — run in a thread
        await asyncio.wait_for(
            asyncio.to_thread(s3_client.check_connectivity),
            timeout=TIMEOUT,
        )
        latency_ms = round((time.monotonic() - start) * 1000)
        return {"status": "ok", "latency_ms": latency_ms}
    except Exception as e:
        latency_ms = round((time.monotonic() - start) * 1000)
        return {"status": "error", "latency_ms": latency_ms, "detail": str(e)}


@router.get("/health")
async def health_check():
    db_result, redis_result, s3_result = await asyncio.gather(
        _check_db(),
        _check_redis(),
        _check_s3(),
        return_exceptions=False,  # each helper catches its own exceptions
    )

    all_ok = all(
        r["status"] == "ok" for r in (db_result, redis_result, s3_result)
    )

    body = {
        "status": "ok" if all_ok else "degraded",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": {
            "db": db_result,
            "redis": redis_result,
            "s3": s3_result,
        },
    }

    return JSONResponse(content=body, status_code=200 if all_ok else 503)