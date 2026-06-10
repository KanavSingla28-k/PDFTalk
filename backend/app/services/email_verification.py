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
  - If the DB write fails, the exception bubbles up. The registration
    endpoint (T-18) catches it.
  - Email delivery is offloaded to the RQ "default" queue (T-28) — the HTTP
    response is not blocked by the Resend API call.
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
    In local development, the frontend is on port 3000/3001, and the backend
    API is on port 8000. The verification link must point directly to the
    backend API so it can process the token and redirect back to the frontend.
    """
    if "localhost:300" in settings.APP_URL or "127.0.0.1:300" in settings.APP_URL:
        api_url = "http://localhost:8000"
    else:
        # In production/Nginx environment, API is routed through /api
        api_url = f"{settings.APP_URL.rstrip('/')}/api"
    return f"{api_url}/auth/verify-email?token={raw_token}"


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
    Full orchestration: generate token → store hash → enqueue email job.

    Called directly from the registration endpoint (T-18). Email delivery is
    offloaded to the RQ "default" queue (T-28) so the HTTP response is not
    blocked by the Resend API call.

    The RQ job calls `app.utils.email.send_verification_email_sync` by import
    path string, which is safe because:
      - The worker process has no running event loop (asyncio.run() is safe).
      - The job carries only primitive values (strings) — no DB session crosses
        the queue boundary.

    Args:
        user_id: UUID string of the newly registered user.
        email:   The user's email address (to address).
        db:      Active async DB session. Token is flushed within this session.

    Raises:
        SQLAlchemyError: If the DB write fails.
    """
    raw_token = await generate_and_store_verification_token(user_id, db)
    verification_url = _build_verification_url(raw_token)
    default_queue.enqueue(
        "app.utils.email.send_verification_email_sync",
        kwargs={"to_email": email, "verification_url": verification_url},
    )


async def verify_token(raw_token: str, db: AsyncSession) -> str:
    """
    Validate an incoming raw token from the verify-email endpoint (T-19).

    Checks:
      1. Token hash exists in the DB and has not expired.
      2. Row is locked FOR UPDATE so concurrent requests can't double-verify.

    On success:
      - Deletes the token row (one-time-use).
      - Marks user.is_verified = True in the same transaction.
      - Returns the user_id string.

    On failure: raises ValueError with a generic message.

    Args:
        raw_token: The raw token from the URL query param.
        db:        Active async DB session.

    Returns:
        The user_id (UUID string) associated with the token.

    Raises:
        ValueError: If the token is invalid or expired.
    """
    from app.models.user import User

    token_hash = _hash_token(raw_token)
    now = datetime.now(timezone.utc)

    # SELECT FOR UPDATE: locks the row so a second concurrent request that
    # arrives before the DELETE commits will block and then see record=None
    # (the row is gone), raising ValueError instead of double-verifying.
    result = await db.execute(
        select(EmailVerification)
        .where(EmailVerification.token_hash == token_hash)
        .with_for_update()
    )
    record: EmailVerification | None = result.scalar_one_or_none()

    if record is None:
        log.warning("verification_token_not_found", token_hash=token_hash[:8] + "...")
        raise ValueError("Invalid verification token")

    # Normalise timezone for SQLite compatibility.
    expires_at = record.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if expires_at < now:
        # Expired — sweep it and raise.
        await db.execute(
            delete(EmailVerification).where(EmailVerification.id == record.id)
        )
        await db.flush()
        log.warning("verification_token_expired", user_id=record.user_id)
        raise ValueError("Invalid or expired verification token")

    user_id = record.user_id

    # One-time-use: delete the token row.
    await db.execute(
        delete(EmailVerification).where(EmailVerification.id == record.id)
    )

    # Mark the user verified in the same transaction — atomic with the delete.
    await db.execute(
        update(User).where(User.id == user_id).values(is_verified=True)
    )

    await db.flush()

    # Also sweep any other stale tokens for this user as a cleanup courtesy.
    await _sweep_expired_tokens_for_user(db, user_id)

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
