from __future__ import annotations

import logging
import secrets
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

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
 
_MAX_FAILED_ATTEMPTS = 10
_LOCKOUT_DURATION_MINUTES = 15
 
# A fixed bcrypt hash of the string "dummy". Used to perform a constant-time
# password verification even when the email doesn't exist, so that a timing
# attacker cannot distinguish "email not found" from "wrong password".
# Generated once: passlib.context.CryptContext(["bcrypt"]).hash("dummy")
_DUMMY_HASH = "$2b$12$8r3VnEHcdWKJCN5K3jCCPudYoOvlWLIaya98ZBX7NLXtlEeTPfIcu"

# ----------------------------------------------------------------------------


async def get_by_email_lower(db: AsyncSession, email_lower: str) -> User | None:
    result = await db.execute(
        select(User).where(User.email_lower == email_lower)
    )
    return result.scalar_one_or_none()


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
            # Re-send: delete the stale verification row first so we don't
            # accumulate orphaned tokens, then issue a fresh one.
            await _delete_pending_verification(db, existing.id)
            await send_verification_email_for_user(str(existing.id), existing.email, db)
            await db.commit()
        # If already verified: silent no-op — do not reveal account existence.
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


async def _delete_pending_verification(db: AsyncSession, user_id) -> None:
    """
    Remove any existing email_verifications rows for this user.
    Called before issuing a fresh token toapp.models.auth
    """
    from app.models.auth import EmailVerification
    from sqlalchemy import delete

    await db.execute(
        delete(EmailVerification).where(EmailVerification.user_id == user_id)
    )

"""
Login check sequence:
  1. Look up by email_lower
  2. Timing-safe dummy verify if user not found (prevents email enumeration)
  3. is_verified check
  4. is_active check
  5. locked_until check
  6. bcrypt verify
  7. On failure: increment attempts, maybe lock
  8. On success: reset attempts, issue tokens
"""

# ---------------------------------------------------------------------------
# Service function
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

    The route handler is responsible for:
      - Placing raw_refresh_token into an httpOnly cookie
      - Returning access_token + expires_in in the JSON body
      - Using the returned User object for the response UserInfo payload
        (avoids a second SELECT in the router)

    Raises:
        InvalidCredentialsError — any auth failure (email, password, lockout,
                                  inactive account). Always use this for 401.
        UnverifiedEmailError    — account found but email_verified is False.
                                  Route handler maps this to 403.
    """
    email_lower = email.lower().strip()
 
    # ------------------------------------------------------------------
    # Step 1: Look up user by normalised email
    # ------------------------------------------------------------------
    result = await db.execute(
        select(User).where(User.email_lower == email_lower)
    )
    user: User | None = result.scalar_one_or_none()
 
    # ------------------------------------------------------------------
    # Step 2: Timing-safe path when user doesn't exist
    #
    # Without this, an attacker can enumerate valid emails by timing:
    #   - Unknown email   → returns in ~0 ms  (no DB row → early return)
    #   - Known email     → returns in ~250 ms (bcrypt verify runs)
    #
    # By always running a dummy bcrypt verify, both paths take ~250 ms,
    # making timing-based enumeration infeasible.
    # ------------------------------------------------------------------
    if user is None:
        verify_password(password, _DUMMY_HASH)  # result intentionally discarded
        raise InvalidCredentialsError()
 
    # ------------------------------------------------------------------
    # Step 3: Email verification gate
    #
    # Raises UnverifiedEmailError (→ 403) instead of InvalidCredentialsError
    # (→ 401) so the frontend can show a "resend verification" prompt.
    # This is an intentional, acceptable information disclosure: the user
    # already knows they registered with this email.
    # ------------------------------------------------------------------
    if not user.is_verified:
        raise UnverifiedEmailError()
 
    # ------------------------------------------------------------------
    # Step 4: Account active check
    # ------------------------------------------------------------------
    if not user.is_active:
        raise InvalidCredentialsError()
 
    # ------------------------------------------------------------------
    # Step 5: Lockout check
    #
    # SQLite drops timezone info on read; Postgres preserves it.
    # Normalise locked_until to UTC-aware before comparing with _now_utc()
    # to prevent the test-suite failing on SQLite (same fix applied in T-18).
    # ------------------------------------------------------------------
    if user.locked_until is not None:
        locked_until = user.locked_until
        if locked_until.tzinfo is None:
            locked_until = locked_until.replace(tzinfo=timezone.utc)
        if _now_utc() < locked_until:
            # Do NOT say "account is locked" — that confirms the email exists
            # to an attacker probing for accounts.
            raise InvalidCredentialsError()
 
    # ------------------------------------------------------------------
    # Step 6: Password verification (bcrypt, ~250 ms intentionally)
    # ------------------------------------------------------------------
    password_valid = verify_password(password, user.password_hash)
 
    if not password_valid:
        # ------------------------------------------------------------------
        # Step 7: Failed attempt tracking + lockout
        # ------------------------------------------------------------------
        user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
 
        if user.failed_login_attempts >= _MAX_FAILED_ATTEMPTS:
            user.locked_until = _now_utc() + timedelta(minutes=_LOCKOUT_DURATION_MINUTES)
            user.failed_login_attempts = 0  # reset so counter is clean after lockout lifts
            logger.warning(
                "Account locked due to repeated failed logins",
                extra={"user_id": str(user.id)},
            )
 
        await db.commit()
        raise InvalidCredentialsError()
 
    # ------------------------------------------------------------------
    # Step 8: Success — reset failure counters, issue tokens
    # ------------------------------------------------------------------
    user.failed_login_attempts = 0
    user.locked_until = None
    # Flush the counter reset in the same transaction that store_refresh_token
    # will commit. We use flush() (not commit()) here so that if token issuance
    # fails mid-way, the counter reset doesn't persist without a token being
    # issued — they succeed or fail together.
    await db.flush()
 
    access_token, raw_refresh_token, expires_in = await issue_token_pair(
        user_id=str(user.id),
        db=db,
    )
 
    logger.info(
        "User logged in",
        extra={"user_id": str(user.id)},
    )
 
    return access_token, raw_refresh_token, expires_in, user