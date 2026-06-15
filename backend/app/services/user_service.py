from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import (
    InvalidCredentialsError,
    UnverifiedEmailError,
)
from app.models.user import User
from app.auth.password import hash_password, verify_password
from app.auth.tokens import issue_token_pair
from app.services.email_verification import send_verification_email_for_user
from app.utils.metrics import (
    user_registrations_total,
    user_logins_total,
    login_failures_total,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_FAILED_ATTEMPTS = 10
_LOCKOUT_DURATION_MINUTES = 15

_DUMMY_HASH = "$2b$12$8r3VnEHcdWKJCN5K3jCCPudYoOvlWLIaya98ZBX7NLXtlEeTPfIcu"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def get_by_email_lower(db: AsyncSession, email_lower: str) -> User | None:
    result = await db.execute(
        select(User).where(User.email_lower == email_lower)
    )
    return result.scalar_one_or_none()


async def _delete_pending_verification(db: AsyncSession, user_id: uuid.UUID | str) -> None:
    from app.models.auth import EmailVerification
    from sqlalchemy import delete

    await db.execute(
        delete(EmailVerification).where(EmailVerification.user_id == user_id)
    )


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------

async def register(db: AsyncSession, email: str, password: str) -> None:
    """
    Register a new user or re-send verification for an existing unverified one.

    Branches:
      - New email            → create user, send verification email
      - Existing, unverified → delete old verification token, send fresh one
      - Existing, verified   → silent no-op (no enumeration leak)

    Always returns None. The caller unconditionally returns 202.
    """
    email_lower = email.strip().lower()
    existing = await get_by_email_lower(db, email_lower)

    if existing is not None:
        if not existing.is_verified:
            await _delete_pending_verification(db, existing.id)
            await send_verification_email_for_user(str(existing.id), existing.email, db)
            await db.commit()
        # Verified account: silent no-op — do not reveal account existence.
        return

    # Happy path: brand-new user.
    user = User(
        email=email.strip(),
        email_lower=email_lower,
        password_hash=hash_password(password),
        is_verified=False,
        is_active=True,
    )
    db.add(user)
    await db.flush()  # Populate user.id before passing to email service.

    await send_verification_email_for_user(str(user.id), user.email, db)
    await db.commit()

    # Increment only on genuine new registrations, not on resend-verification
    # paths — those aren't new accounts.
    user_registrations_total.inc()


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


async def login(
    db: AsyncSession,
    email: str,
    password: str,
) -> tuple[str, str, int, "User"]:
    """
    Authenticate a user and issue a token pair.

    Returns:
        (access_token, raw_refresh_token, expires_in_seconds, user)

    Raises:
        InvalidCredentialsError — any auth failure (email, password, lockout,
                                  inactive account). Always use this for 401.
        UnverifiedEmailError    — account found but is_verified is False.
                                  Route handler maps this to 403.
    """
    email_lower = email.lower().strip()

    # Step 1: Look up user
    result = await db.execute(
        select(User).where(User.email_lower == email_lower)
    )
    user: User | None = result.scalar_one_or_none()

    # Step 2: Timing-safe path when user doesn't exist
    if user is None:
        verify_password(password, _DUMMY_HASH)  # result intentionally discarded
        login_failures_total.labels(reason="not_found").inc()
        raise InvalidCredentialsError()

    # Step 3: Email verification gate
    if not user.is_verified:
        login_failures_total.labels(reason="unverified").inc()
        raise UnverifiedEmailError()

    # Step 4: Account active check
    if not user.is_active:
        login_failures_total.labels(reason="wrong_password").inc()  # don't leak inactive status
        raise InvalidCredentialsError()

    # Step 5: Lockout check
    if user.locked_until is not None:
        locked_until = user.locked_until
        if locked_until.tzinfo is None:
            locked_until = locked_until.replace(tzinfo=timezone.utc)
        if _now_utc() < locked_until:
            login_failures_total.labels(reason="locked").inc()
            raise InvalidCredentialsError()

    # Step 6: Password verification
    password_valid = verify_password(password, user.password_hash)

    if not password_valid:
        # Step 7: Failed attempt tracking + lockout
        user.failed_login_attempts = (user.failed_login_attempts or 0) + 1

        if user.failed_login_attempts >= _MAX_FAILED_ATTEMPTS:
            user.locked_until = _now_utc() + timedelta(minutes=_LOCKOUT_DURATION_MINUTES)
            user.failed_login_attempts = 0
            logger.warning(
                "Account locked due to repeated failed logins",
                extra={"user_id": str(user.id)},
            )

        await db.commit()
        login_failures_total.labels(reason="wrong_password").inc()
        raise InvalidCredentialsError()

    # Step 8: Success — reset failure counters, issue tokens
    user.failed_login_attempts = 0
    user.locked_until = None
    await db.flush()

    access_token, raw_refresh_token, expires_in = await issue_token_pair(
        user_id=str(user.id),
        db=db,
    )

    user_logins_total.inc()
    logger.info("User logged in", extra={"user_id": str(user.id)})

    return access_token, raw_refresh_token, expires_in, user
