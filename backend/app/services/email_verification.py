"""
Email verification token lifecycle.
"""

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.auth import EmailVerification
from app.workers.queues import default_queue
from app.utils.metrics import emails_sent_total

log = structlog.get_logger(__name__)

TOKEN_TTL_HOURS = 24
TOKEN_BYTES = 32


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


def _build_verification_url(raw_token: str) -> str:
    if "localhost:300" in settings.APP_URL or "127.0.0.1:300" in settings.APP_URL:
        api_url = "http://localhost:8000"
    else:
        api_url = f"{settings.APP_URL.rstrip('/')}/api"
    return f"{api_url}/auth/verify-email?token={raw_token}"


async def generate_and_store_verification_token(
    user_id: str,
    db: AsyncSession,
) -> str:
    user_uuid = uuid.UUID(user_id) if isinstance(user_id, str) else user_id

    await db.execute(
        delete(EmailVerification).where(EmailVerification.user_id == user_uuid)
    )

    raw_token = secrets.token_urlsafe(TOKEN_BYTES)
    token_hash = _hash_token(raw_token)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=TOKEN_TTL_HOURS)

    verification = EmailVerification(
        user_id=user_uuid,
        token_hash=token_hash,
        expires_at=expires_at,
    )
    db.add(verification)
    await db.flush()

    log.info(
        "verification_token_created",
        user_id=user_id,
        expires_at=expires_at.isoformat(),
    )
    return raw_token


async def send_verification_email_for_user(
    user_id: str,
    email: str,
    db: AsyncSession,
) -> None:
    raw_token = await generate_and_store_verification_token(user_id, db)
    verification_url = _build_verification_url(raw_token)
    default_queue.enqueue(
        "app.utils.email.send_verification_email_sync",
        kwargs={"to_email": email, "verification_url": verification_url},
    )
    emails_sent_total.labels(type="verification").inc()


async def verify_token(raw_token: str, db: AsyncSession) -> str:
    from app.models.user import User

    token_hash = _hash_token(raw_token)
    now = datetime.now(timezone.utc)

    result = await db.execute(
        select(EmailVerification)
        .where(EmailVerification.token_hash == token_hash)
        .with_for_update()
    )
    record: EmailVerification | None = result.scalar_one_or_none()

    if record is None:
        log.warning("verification_token_not_found", token_hash=token_hash[:8] + "...")
        raise ValueError("Invalid verification token")

    expires_at = record.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if expires_at < now:
        await db.execute(
            delete(EmailVerification).where(EmailVerification.id == record.id)
        )
        await db.flush()
        log.warning("verification_token_expired", user_id=record.user_id)
        raise ValueError("Invalid or expired verification token")

    user_id = record.user_id

    await db.execute(
        delete(EmailVerification).where(EmailVerification.id == record.id)
    )

    await db.execute(
        update(User).where(User.id == user_id).values(is_verified=True)
    )

    await db.flush()
    await _sweep_expired_tokens_for_user(db, user_id)

    log.info("verification_token_consumed", user_id=user_id)
    return str(user_id)


async def _sweep_expired_tokens_for_user(db: AsyncSession, user_id: uuid.UUID) -> None:
    now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.execute(
        delete(EmailVerification).where(
            EmailVerification.user_id == user_id,
            EmailVerification.expires_at < now_naive,
        )
    )


async def purge_expired_tokens(db: AsyncSession) -> int:
    now = datetime.now(timezone.utc)
    result = await db.execute(
        delete(EmailVerification)
        .where(EmailVerification.expires_at < now)
        .returning(EmailVerification.id)
    )
    deleted = len(result.fetchall())
    if deleted:
        log.info("expired_verification_tokens_purged", count=deleted)
    return deleted
