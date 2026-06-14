import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.auth import PasswordReset, RefreshToken
from app.auth.password import hash_password
from app.services.email_verification import send_verification_email_for_user
from app.workers.queues import default_queue
from app.utils.metrics import emails_sent_total

log = structlog.get_logger(__name__)

TOKEN_BYTES = 32
TOKEN_TTL_HOURS = 1


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


async def initiate_password_reset(email: str, db: AsyncSession) -> None:
    email_lower = email.strip().lower()

    result = await db.execute(
        select(User).where(User.email_lower == email_lower)
    )
    user: User | None = result.scalar_one_or_none()

    if user is None:
        return  # Silently return — no user enumeration

    if not user.is_verified:
        # Send verification email instead of reset email
        await send_verification_email_for_user(str(user.id), user.email, db)
        await db.commit()
        return

    # User is verified — generate reset token
    await db.execute(
        delete(PasswordReset).where(PasswordReset.user_id == user.id)
    )

    raw_token = secrets.token_urlsafe(TOKEN_BYTES)
    token_hash = _hash_token(raw_token)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=TOKEN_TTL_HOURS)

    reset_record = PasswordReset(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=expires_at,
    )
    db.add(reset_record)
    await db.flush()

    default_queue.enqueue(
        "app.utils.email.send_password_reset_email_sync",
        kwargs={"to_email": user.email, "raw_token": raw_token},
    )
    emails_sent_total.labels(type="password_reset").inc()

    await db.commit()
    log.info("password_reset_initiated", user_id=str(user.id))


async def consume_reset_token(raw_token: str, new_password: str, db: AsyncSession) -> User:
    from app.exceptions import InvalidResetTokenError

    token_hash = _hash_token(raw_token)
    now = datetime.now(timezone.utc)

    result = await db.execute(
        select(PasswordReset)
        .where(PasswordReset.token_hash == token_hash)
        .with_for_update()
    )
    record: PasswordReset | None = result.scalar_one_or_none()

    if record is None:
        log.warning("password_reset_token_not_found", token_hash=token_hash[:8] + "...")
        raise InvalidResetTokenError("Invalid or expired token")

    expires_at = record.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if expires_at < now:
        await db.execute(delete(PasswordReset).where(PasswordReset.id == record.id))
        await db.flush()
        log.warning("password_reset_token_expired", user_id=str(record.user_id))
        raise InvalidResetTokenError("Invalid or expired token")

    user_id = record.user_id

    result = await db.execute(select(User).where(User.id == user_id))
    user: User | None = result.scalar_one_or_none()

    if user is None:
        raise InvalidResetTokenError("Invalid or expired token")

    user.password_hash = hash_password(new_password)

    await db.execute(delete(PasswordReset).where(PasswordReset.id == record.id))
    await db.execute(delete(RefreshToken).where(RefreshToken.user_id == user_id))

    await db.flush()
    log.info("password_reset_consumed", user_id=str(user_id))

    return user
