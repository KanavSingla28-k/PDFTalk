"""
Email verification token lifecycle.

Responsibilities:
  1. Generate a cryptographically secure raw token.
  2. Store its SHA-256 hash (never the raw token) in `email_verifications`.
  3. Orchestrate sending the verification email.
  4. Validate an incoming raw token on the verify-email endpoint (T-19).

Design notes:
  - The raw token is returned to the caller exactly once (to build the email URL)
    and never persisted server-side.
  - If the DB or email send fails, the exception bubbles up. The registration
    endpoint (T-18) catches it.
  - Later (when RQ is wired in T-28) replace `send_verification_email_for_user`
    with an RQ job enqueue — the DB side stays identical.
"""

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.auth import EmailVerification
from app.utils.email import send_verification_email

log = structlog.get_logger(__name__)

# Token validity window
TOKEN_TTL_HOURS = 24

# Length of the raw token in URL-safe base64 chars.
# secrets.token_urlsafe(32) → ~43 chars, 256 bits of entropy.
TOKEN_BYTES = 32


# ── Internal helpers ──────────────────────────────────────────────────────────


def _hash_token(raw_token: str) -> str:
    """Return the hex-encoded SHA-256 hash of a raw token string."""
    return hashlib.sha256(raw_token.encode()).hexdigest()


def _build_verification_url(raw_token: str) -> str:
    """
    Build the full URL that goes into the verification email.
    APP_URL comes from settings (e.g. "https://pdftalk.com" in prod,
    "http://localhost:3000" in dev).
    """
    return f"{settings.APP_URL}/verify-email?token={raw_token}"


# ── Public API ────────────────────────────────────────────────────────────────


async def generate_and_store_verification_token(
    user_id: str,
    db: AsyncSession,
) -> str:
    """
    Generate a verification token for `user_id`, persist its hash to the DB,
    and return the raw token (to be embedded in the email link).

    Any existing unexpired tokens for this user are deleted first — only one
    active verification token per user at a time.

    Returns:
        The raw (unhashed) token string. Pass this to `_build_verification_url`.

    Raises:
        SQLAlchemyError: On DB failure — caller should handle.
    """
    # Normalise to uuid.UUID so SQLAlchemy's UUID column type is satisfied
    # on both PostgreSQL (production) and SQLite (tests).
    user_uuid = uuid.UUID(user_id) if isinstance(user_id, str) else user_id

    # Delete any existing tokens for this user before creating a new one.
    # Prevents accumulation of stale rows and avoids confusion if the user
    # clicks "resend" multiple times.
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
    await db.flush()  # Write to DB within the current transaction; caller commits.

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
    """
    Full orchestration: generate token → store hash → send email.

    Called directly from the registration endpoint (T-18).

    TODO (T-28): Replace the `send_verification_email` call with an RQ job
    enqueue so the HTTP response is not blocked by the Resend API call:
        from app.workers.tasks import enqueue_verification_email
        enqueue_verification_email(user_id, email, raw_token)

    Args:
        user_id: UUID string of the newly registered user.
        email:   The user's email address (to address).
        db:      Active async DB session. Token is flushed within this session.

    Raises:
        RuntimeError: If the email send fails (from utils/email.py).
        SQLAlchemyError: If the DB write fails.
    """
    raw_token = await generate_and_store_verification_token(user_id, db)
    verification_url = _build_verification_url(raw_token)
    await send_verification_email(to_email=email, verification_url=verification_url)


async def verify_token(raw_token: str, db: AsyncSession) -> str:
    """
    Validate an incoming raw token from the verify-email endpoint (T-19).

    Checks:
      1. Token hash exists in the DB.
      2. Token has not expired.

    On success: deletes the token row (one-time-use) and returns the `user_id`.
    On failure: raises ValueError with a generic message (do not reveal why).

    Args:
        raw_token: The raw token from the URL query param.
        db:        Active async DB session.

    Returns:
        The user_id (UUID string) associated with the token.

    Raises:
        ValueError: If the token is invalid or expired.
    """
    token_hash = _hash_token(raw_token)
    now = datetime.now(timezone.utc)

    result = await db.execute(
        select(EmailVerification).where(EmailVerification.token_hash == token_hash)
    )
    record: EmailVerification | None = result.scalar_one_or_none()

    if record is None:
        log.warning("verification_token_not_found", token_hash=token_hash[:8] + "...")
        raise ValueError("Invalid verification token")

    # T-19: Sweep all expired tokens for this user on every verification attempt.
    # Avoids accumulation of stale rows without a separate cron job.
    # Done before the expiry check so cleanup happens regardless of whether
    # the current token is itself expired.
    record_id = record.id
    record_user_id = record.user_id
    expires_at = record.expires_at

    await _sweep_expired_tokens_for_user(db, record_user_id)

    # SQLite strips timezone info; normalise to UTC for comparison.
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < now:
        # The sweep already deleted this row (it was expired).
        # Nothing left to delete — just raise.
        log.warning("verification_token_expired", user_id=record_user_id)
        raise ValueError("Invalid or expired verification token")

    user_id = record_user_id

    # One-time-use: delete the (valid, not-yet-swept) row.
    await db.execute(
        delete(EmailVerification).where(EmailVerification.id == record_id)
    )
    await db.flush()

    log.info("verification_token_consumed", user_id=user_id)
    return str(user_id)


async def _sweep_expired_tokens_for_user(db: AsyncSession, user_id: uuid.UUID) -> None:
    """
    Delete all expired email_verification rows for a single user.

    Called inside verify_token on every verification attempt (T-19).
    Scoped to one user so it never touches another user's rows.
    Does not commit — the caller owns the transaction boundary.

    The comparison uses a naive UTC datetime so the WHERE clause works against
    both PostgreSQL (TIMESTAMPTZ, tz-aware) and SQLite (naive) columns.
    SQLAlchemy emits a bare timestamp literal either way; Postgres coerces it
    correctly when the session timezone is UTC (our default).
    """
    now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.execute(
        delete(EmailVerification).where(
            EmailVerification.user_id == user_id,
            EmailVerification.expires_at < now_naive,
        )
    )


async def purge_expired_tokens(db: AsyncSession) -> int:
    """
    Delete all expired verification tokens from the DB.

    Called from a daily maintenance job (or can be wired into the cron
    established in T-44). Returns the count of deleted rows.
    """
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
