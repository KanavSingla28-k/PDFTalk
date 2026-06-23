"""
app/routers/internal.py

Internal-only routes.

  POST /internal/admin/login      Sets httpOnly admin session cookie
  POST /internal/admin/logout     Clears the cookie
  POST /internal/alerts/webhook   Alertmanager webhook (Bearer auth — server-to-server)
  GET  /internal/admin/stats      Business metrics (cookie auth)
"""

# import asyncio
import secrets
import structlog
from datetime import date
from typing import Any, cast

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status, BackgroundTasks
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
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

_COOKIE_NAME = "admin_session"
_COOKIE_MAX_AGE = 60 * 60 * 8  # 8 hours


# ---------------------------------------------------------------------------
# Auth dependencies — two separate ones for the two auth surfaces
# ---------------------------------------------------------------------------

async def _require_admin_cookie(
    admin_session: str | None = Cookie(default=None),
) -> None:
    """
    Protects browser-facing endpoints (stats, future admin routes).
    Reads the httpOnly cookie set by /internal/admin/login and verifies
    it exists in Redis as an active session.
    """
    if not admin_session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    redis = get_redis()
    is_valid = await redis.get(f"admin:session:{admin_session}")
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired or invalid",
        )


def _require_admin_bearer(
    creds: HTTPAuthorizationCredentials = Depends(bearer),
) -> None:
    """
    Protects server-to-server endpoints (Alertmanager webhook).
    Bearer token in Authorization header — never touches a browser.
    """
    if settings.ADMIN_TOKEN is None:
        log.error("admin_token_not_configured")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="ADMIN_TOKEN is not configured on the server.",
        )
    if not secrets.compare_digest(creds.credentials, settings.ADMIN_TOKEN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden",
        )


# ---------------------------------------------------------------------------
# Login / logout
# ---------------------------------------------------------------------------

class AdminLoginRequest(BaseModel):
    token: str


@router.post("/admin/login")
async def admin_login(
    body: AdminLoginRequest,
    response: Response,
) -> dict[str, str]:
    """
    Validate the admin token and set an httpOnly session cookie.
    The secret token never touches localStorage — it goes directly into
    a secure backend Redis session, and the user gets an opaque token.
    """
    if settings.ADMIN_TOKEN is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="ADMIN_TOKEN is not configured on the server.",
        )
    if not secrets.compare_digest(body.token, settings.ADMIN_TOKEN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid token",
        )

    # Generate an opaque session token
    session_token = secrets.token_urlsafe(32)
    redis = get_redis()
    await redis.set(f"admin:session:{session_token}", "1", ex=_COOKIE_MAX_AGE)

    response.set_cookie(
        key=_COOKIE_NAME,
        value=session_token,
        httponly=True,
        secure=settings.is_production,  # Automatically secure in production
        samesite="strict",
        max_age=_COOKIE_MAX_AGE,
        path="/",
    )
    log.info("admin_login_success")
    return {"detail": "ok"}


@router.post("/admin/logout")
async def admin_logout(
    response: Response,
    admin_session: str | None = Cookie(default=None)
) -> dict[str, str]:
    """Clear the admin session cookie and invalidate it in Redis."""
    if admin_session:
        redis = get_redis()
        await redis.delete(f"admin:session:{admin_session}")

    response.delete_cookie(
        key=_COOKIE_NAME,
        path="/",
        secure=settings.is_production,
        samesite="strict",
    )
    return {"detail": "ok"}


# ---------------------------------------------------------------------------
# Alertmanager webhook — Bearer auth (server-to-server only)
# ---------------------------------------------------------------------------

class AlertPayload(BaseModel):
    status: str
    labels: dict[str, str]
    annotations: dict[str, str]

class AlertmanagerWebhookPayload(BaseModel):
    alerts: list[AlertPayload]


@router.post(
    "/alerts/webhook",
    dependencies=[Depends(_require_admin_bearer)],
    status_code=204,
)
async def alertmanager_webhook(
    payload: AlertmanagerWebhookPayload,
    background_tasks: BackgroundTasks,
) -> None:
    """
    Alertmanager POSTs here when an alert fires or resolves.
    Fire-and-forget — ACK immediately, dispatch in background.
    """
    background_tasks.add_task(dispatch_alert, payload.model_dump())


# ---------------------------------------------------------------------------
# Admin stats — cookie auth
# ---------------------------------------------------------------------------

@router.get(
    "/admin/stats",
    dependencies=[Depends(_require_admin_cookie)],
)
async def admin_stats(
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Aggregated business metrics for the operator dashboard."""

    # ── User signups (last 30 days) ───────────────────────────────────────
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

    # ── User counts ───────────────────────────────────────────────────────
    total_users = (
        await db.execute(select(func.count()).select_from(User))
    ).scalar() or 0

    verified_users = (
        await db.execute(
            select(func.count()).select_from(User).where(User.is_verified)
        )
    ).scalar() or 0

    # ── Document counts ───────────────────────────────────────────────────
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
            text(
                "SELECT COUNT(*) FROM job_logs "
                "WHERE created_at >= NOW() - INTERVAL '7 days'"
            )
        )
    ).scalar() or 0

    # ── Active verification tokens ────────────────────────────────────────
    emails_verification = (
        await db.execute(select(func.count()).select_from(EmailVerification))
    ).scalar() or 0

    # ── Token utilization today (O(1) ZSET fetch) ─────────────────────────────
    redis = get_redis()
    today_str = date.today().strftime("%Y%m%d")
    stats_key = f"admin:stats:tokens:{today_str}"
    
    # Get top 20 users by token usage today
    zset_results = cast(list[tuple[Any, float]], await redis.zrevrange(stats_key, 0, 19, withscores=True))
    token_data = [{"user_id": str(user_id), "tokens_today": int(score)} for user_id, score in zset_results]

    # ── Dead-letter queue ─────────────────────────────────────────────────
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
