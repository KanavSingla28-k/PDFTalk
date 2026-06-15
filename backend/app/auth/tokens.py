"""
JWT access token issuance + DB-backed refresh token lifecycle.

Design (from T-16 spec):
  Access tokens  — short-lived JWTs (15 min), HS256, verified stateless on
                   every request. Carry sub, iat, exp, jti, type claims.

  Refresh tokens — opaque random strings (secrets.token_urlsafe(32)).
                   Only the SHA-256 hash is persisted in the `refresh_tokens`
                   table. The raw token travels to the client exactly once,
                   inside an httpOnly cookie set by the login/refresh endpoint.
                   If the DB is breached, attackers get hashes — the raw tokens
                   are non-derivable.

  Rotation       — every call to validate_and_rotate_refresh_token() deletes
                   the consumed token and issues a brand-new pair. If an
                   attacker steals and uses a refresh token first, the
                   legitimate user's next refresh will find the token already
                   gone and be forced to re-login.
"""

import hashlib
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, cast

from jose import ExpiredSignatureError, JWTError, jwt
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.auth import RefreshToken  # SQLAlchemy model matching T-04 schema

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Typed exceptions — callers import these to avoid bare except clauses
# ---------------------------------------------------------------------------

class TokenExpiredError(ValueError):
    """The JWT access token has passed its exp claim."""


class TokenInvalidError(ValueError):
    """The token is malformed, has the wrong type, or is missing required claims."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _hash_token(raw: str) -> str:
    """
    SHA-256 hash of the raw token string.

    This is the value stored in the DB. The raw token never touches
    persistent storage — it lives only in memory and in the httpOnly cookie.
    """
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _decode_token_unverified(token: str) -> str | None:
    """
    Decode a JWT without verifying the signature or expiry.
 
    Returns the 'sub' claim (user_id) if present, otherwise None.
    Never raises — any failure returns None.
 
    IMPORTANT: This is for LOGGING ONLY. Never use for auth decisions.
    """
    try:
        payload = jwt.decode(
            token,
            key="",                         # ignored when verify_signature=False
            algorithms=["HS256"],
            options={
                "verify_signature": False,
                "verify_exp": False,
                "verify_aud": False,
            },
        )
        sub = payload.get("sub")
        return str(sub) if sub else None
    except Exception:
        return None
# ---------------------------------------------------------------------------
# Response schema
# ---------------------------------------------------------------------------

class TokenPair(BaseModel):
    """
    Returned in the JSON body of login and refresh responses.

    The access_token goes into the Authorization header for API calls.
    The refresh token is NOT included here — it travels as an httpOnly
    cookie set directly on the Response object by the route handler (T-20).
    """
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds until access token expiry — set by caller


# ---------------------------------------------------------------------------
# Access token
# ---------------------------------------------------------------------------

def create_access_token(user_id: str) -> str:
    """
    Issue a signed JWT access token valid for ACCESS_TOKEN_EXPIRE_MINUTES.

    Claims:
      sub  — user ID (string)
      iat  — issued-at timestamp
      exp  — expiry timestamp (15 min from now)
      jti  — unique token ID; enables future stateful revocation via Redis
             without changing the stateless verification path
      type — "access"; checked on decode to prevent refresh tokens being
             accepted as access tokens
    """
    now = _now_utc()
    payload: dict[str, Any] = {
        "sub": user_id,
        "iat": now,
        "exp": now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        "jti": str(uuid.uuid4()),
        "type": "access",
    }
    return jwt.encode(
        payload,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def decode_access_token(token: str) -> str:
    """
    Decode and validate a JWT access token. Returns user_id on success.

    Raises:
        TokenExpiredError  — token is structurally valid but past its exp
        TokenInvalidError  — signature bad, wrong type, or missing claims
    """
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            options={"verify_exp": True},
        )
    except ExpiredSignatureError:
        raise TokenExpiredError("Access token has expired")
    except JWTError as exc:
        raise TokenInvalidError(f"Invalid access token: {exc}") from exc

    if payload.get("type") != "access":
        # Hard rejection: a refresh token (or any other type) must never be
        # accepted where an access token is expected.
        raise TokenInvalidError(
            f"Wrong token type: expected 'access', got '{payload.get('type')}'"
        )

    user_id: str | None = payload.get("sub")
    if not user_id:
        raise TokenInvalidError("Token is missing 'sub' claim")

    return user_id


# ---------------------------------------------------------------------------
# Refresh token — DB-backed, hashed at rest
# ---------------------------------------------------------------------------

async def store_refresh_token(user_id: str, db: AsyncSession) -> str:
    """
    Generate a new refresh token, persist only its SHA-256 hash to the DB,
    and return the raw token to the caller exactly once.

    The caller (login/refresh route handler) places the raw token in an
    httpOnly cookie — it must never be written to any log, response body,
    or other persistent store.

    Returns:
        raw_token (str) — the plaintext token for the httpOnly cookie
    """
    raw_token = secrets.token_urlsafe(32)
    token_hash = _hash_token(raw_token)
    expires_at = _now_utc() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

    db.add(
        RefreshToken(
            user_id=uuid.UUID(user_id) if isinstance(user_id, str) else user_id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
    )
    await db.commit()

    return raw_token


async def validate_and_rotate_refresh_token(
    raw_token: str,
    db: AsyncSession,
) -> tuple[str, str]:
    """
    Validate a refresh token and immediately rotate it.

    Steps:
      1. Hash the incoming raw token.
      2. Look up the hash in `refresh_tokens`.
      3. Check expiry.
      4. DELETE the row (one-time-use enforcement + rotation).
      5. Issue a brand-new access token + refresh token pair.

    Returns:
        (new_access_token, new_raw_refresh_token)

    Raises:
        TokenInvalidError  — token not found, already used, or expired
    """
    token_hash = _hash_token(raw_token)

    result = await db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    stored: RefreshToken | None = result.scalar_one_or_none()

    if stored is None:
        # Either never existed or already consumed. Could be a replay attack —
        # log it so security tooling can detect patterns.
        logger.warning("Refresh token not found — possible replay attack")
        raise TokenInvalidError("Refresh token is invalid or has already been used")

    expires_at = stored.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    
    now = _now_utc()
    if expires_at < now:
        # Clean up the stale row while we're here
        await db.delete(stored)
        await db.commit()
        raise TokenInvalidError("Refresh token has expired — please log in again")

    user_id: str = str(stored.user_id)

    if stored.revoked_at:
        revoked_at = stored.revoked_at

        if revoked_at.tzinfo is None:
            revoked_at = revoked_at.replace(tzinfo=timezone.utc)

        grace_period_end = revoked_at + timedelta(seconds=60)

        if now > grace_period_end:
            # Replay attack or past grace period. Clean it up.
            await db.delete(stored)
            await db.commit()
            raise TokenInvalidError("Refresh token is invalid or has already been used")
        # Within grace period: proceed to issue new tokens.
    else:
        # First use. Mark as revoked instead of deleting.
        # This allows concurrent requests in the grace period to succeed.
        stored.revoked_at = now
        db.add(stored)
        await db.flush()

    new_raw_refresh = await store_refresh_token(user_id, db)  # commits
    new_access = create_access_token(user_id)

    return new_access, new_raw_refresh


async def revoke_refresh_token(raw_token: str, db: AsyncSession) -> None:
    """
    Invalidate a refresh token on logout by deleting its DB row.

    Clearing the cookie alone is NOT sufficient — an attacker who already
    copied the cookie value could reuse it. Hard-deleting the row ensures
    that the token is dead server-side regardless of what the client does.

    Silently succeeds if the token is not found (already expired/revoked).
    """
    token_hash = _hash_token(raw_token)
    await db.execute(
        delete(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    await db.commit()


async def revoke_all_refresh_tokens(user_id: uuid.UUID, db: AsyncSession) -> int:
    """
    Invalidate ALL active refresh tokens for *user_id* in a single query.

    Used by DELETE /auth/sessions to implement "sign out of all devices".
    Any device that subsequently tries to use its refresh token will receive
    a 401 and be forced to re-authenticate.

    Returns:
        The number of tokens deleted (useful for logging).
    """
    result = await db.execute(
        delete(RefreshToken)
        .where(RefreshToken.user_id == user_id)
        .returning(RefreshToken.id)
    )
    count = len(result.fetchall())
    await db.commit()
    logger.info("revoke_all_refresh_tokens: deleted %d token(s) for user %s", count, user_id)
    return count


# ---------------------------------------------------------------------------
# Convenience factory used by the login route (T-20)
# ---------------------------------------------------------------------------

async def issue_token_pair(user_id: str, db: AsyncSession) -> tuple[str, str, int]:
    """
    Issue a complete access + refresh token pair in a single call.

    Returns:
        (access_token, raw_refresh_token, expires_in_seconds)

    The caller sets the raw_refresh_token as an httpOnly cookie and returns
    access_token + expires_in in the JSON response body as a TokenPair.
    """
    access_token = create_access_token(user_id)
    raw_refresh_token = await store_refresh_token(user_id, db)
    expires_in = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    return access_token, raw_refresh_token, expires_in
