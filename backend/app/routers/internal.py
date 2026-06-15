"""
app/routers/internal.py

Internal-only routes — all protected by ADMIN_TOKEN bearer auth.

  POST /internal/alerts/webhook   Alertmanager fires here on alert state changes.
  GET  /internal/admin/stats      Aggregated business metrics for the admin dashboard.

The /api/internal/ prefix is blocked at Nginx for external traffic
(allow 172.0.0.0/8; deny all) so the token is a secondary defence.
"""

import asyncio
import structlog
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from rq.registry import FailedJobRegistry
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db
from app.models.auth import EmailVerification
from app.models.document import Document
from app.models.user import User
from app.services.alerting import dispatch_alert
from app.utils.redis_client import get_redis, get_sync_redis

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/internal", tags=["internal"])
bearer = HTTPBearer()


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------

def _require_admin(creds: HTTPAuthorizationCredentials = Depends(bearer)) -> None:
    if settings.ADMIN_TOKEN is None:
        log.error("internal.admin_token_missing", reason="ADMIN_TOKEN is not configured in settings")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Admin token is not configured on the server."
        )
    if creds.credentials != settings.ADMIN_TOKEN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")


# ---------------------------------------------------------------------------
# Alertmanager webhook receiver
# ---------------------------------------------------------------------------

@router.post("/alerts/webhook", dependencies=[Depends(_require_admin)], status_code=204)
async def alertmanager_webhook(payload: dict[str, Any]) -> None:
    """
    Alertmanager POSTs here when an alert fires or resolves.
    Dispatch is fire-and-forget — the webhook ACKs immediately (204)
    and notification delivery runs in the background.
    """
    asyncio.create_task(dispatch_alert(payload))


# ---------------------------------------------------------------------------
# Admin stats
# ---------------------------------------------------------------------------

@router.get("/admin/stats", dependencies=[Depends(_require_admin)])
async def admin_stats(
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Aggregated business metrics for the operator dashboard.
    All queries are read-only and use indexed columns.
    """
    # ── User signups (last 30 days, daily buckets) ────────────────────────
    signups_result = await db.execute(
        text("""
            SELECT DATE(created_at) AS day, COUNT(*) AS count
            FROM users
            WHERE created_at >= NOW() - INTERVAL '30 days'
            GROUP BY day
            ORDER BY day
        """)
    )
    signups_by_day = [{"day": str(r.day), "count": r.count} for r in signups_result]

    # ── Aggregate user counts ─────────────────────────────────────────────
    total_users = (
        await db.execute(select(func.count()).select_from(User))
    ).scalar() or 0

    verified_users = (
        await db.execute(
            select(func.count()).select_from(User).where(User.is_verified)
        )
    ).scalar() or 0

    # ── Document counts by status ─────────────────────────────────────────
    total_documents = (
        await db.execute(select(func.count()).select_from(Document))
    ).scalar() or 0

    documents_by_status_rows = (
        await db.execute(
            select(Document.status, func.count()).group_by(Document.status)
        )
    ).all()

    # ── Failed jobs last 7 days ───────────────────────────────────────────
    failed_jobs_7d = (
        await db.execute(
            text("SELECT COUNT(*) FROM job_logs WHERE created_at >= NOW() - INTERVAL '7 days'")
        )
    ).scalar() or 0

    # ── Active verification tokens ────────────────────────────────────────
    emails_verification = (
        await db.execute(select(func.count()).select_from(EmailVerification))
    ).scalar() or 0

    # ── Token utilization today (Redis scan) ─────────────────────────────
    # Acceptable at MVP user counts (<1000). Each key = O(1) GET.
    redis = get_redis()
    today_str = date.today().strftime("%Y%m%d")
    token_data: list[dict[str, Any]] = []
    async for key in redis.scan_iter(f"quota:tokens:*:{today_str}"):
        val = await redis.get(key)
        if val:
            # Key format: quota:tokens:{user_id}:{date}
            user_id = key.split(":")[2]
            token_data.append({"user_id": user_id, "tokens_today": int(val)})
    token_data.sort(key=lambda x: x["tokens_today"], reverse=True)

    # ── Dead-letter queue count ───────────────────────────────────────────
    # get_sync_redis() returns a plain redis.Redis for RQ compatibility.
    sync_redis = get_sync_redis()
    failed_registry = FailedJobRegistry("ingest", connection=sync_redis)
    dead_letter_count = failed_registry.count  # O(1) ZCARD

    return {
        "users": {
            "total": total_users,
            "verified": verified_users,
            "unverified": total_users - verified_users,
            "signups_by_day": signups_by_day,
        },
        "documents": {
            "total": total_documents,
            "by_status": {row[0]: row[1] for row in documents_by_status_rows},
        },
        "emails": {
            "verification_tokens_active": emails_verification,
        },
        "tokens": {
            "top_users_today": token_data[:20],
        },
        "queue": {
            "dead_letter_count": dead_letter_count,
            "failed_jobs_7d": failed_jobs_7d,
        },
    }
