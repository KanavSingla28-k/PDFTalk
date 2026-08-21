"""
FastAPI dependency functions for JWT authentication (T-22).

Two dependencies, two contracts:

  get_current_user()
    - Extracts and validates the Bearer token from the Authorization header.
    - Decodes the JWT and checks type == "access".
    - Returns user_id as uuid.UUID — NO database hit.
    - Use on endpoints that only need identity (e.g. /auth/refresh, /auth/logout).

  get_verified_user()
    - Calls get_current_user() first (token validation, free).
    - Then fetches the full User row from the DB (one query).
    - Asserts is_active=True and is_verified=True.
    - Returns the User ORM object.
    - Use on ALL data endpoints (documents, query, etc.).

Error flow:
    Dependencies raise typed exceptions from app.exceptions.
    register_exception_handlers() in main.py translates them to HTTP responses.
    No HTTPException is raised here — services stay framework-clean.
"""

import uuid

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.tokens import TokenExpiredError, TokenInvalidError, decode_access_token
from app.db.session import get_db
from app.exceptions import (
    ExpiredTokenError,
    InactiveUserError,
    InvalidTokenError,
    UnverifiedUserError,
    UserNotFoundError,
)
from app.models.user import User

# HTTPBearer extracts the token from "Authorization: Bearer <token>".
# auto_error=False lets us raise our own typed exception instead of FastAPI's
# default 403, keeping the error shape consistent with the rest of the API.
_bearer = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------------------
# get_current_user — token validation only, no DB hit
# ---------------------------------------------------------------------------


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> uuid.UUID:
    """
    Validate the Bearer JWT and return the user_id.

    No database query. Use on endpoints that only need the caller's identity
    and do not need to assert account status (e.g. /auth/refresh, /auth/logout).

    Raises:
        InvalidTokenError  — missing header, malformed token, wrong type
        ExpiredTokenError  — structurally valid token past its exp
    """
    if credentials is None:
        raise InvalidTokenError("Authorization header is missing or not Bearer")

    raw_token = credentials.credentials

    try:
        user_id_str = decode_access_token(raw_token)
    except TokenExpiredError as exc:
        raise ExpiredTokenError(str(exc)) from exc
    except TokenInvalidError as exc:
        raise InvalidTokenError(str(exc)) from exc

    try:
        return uuid.UUID(str(user_id_str))
    except (ValueError, TypeError, AttributeError) as exc:
        raise InvalidTokenError("Invalid access token: malformed subject") from exc


# ---------------------------------------------------------------------------
# get_verified_user — token + DB check (is_active + is_verified)
# ---------------------------------------------------------------------------


async def get_verified_user(
    user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Validate the Bearer JWT, then fetch and assert the User's account status.

    One database query. Use on ALL data endpoints (documents upload, query, etc.).

    Returns:
        User ORM object — routes access .id, .email, .is_active, etc. directly.

    Raises:
        UserNotFoundError   — user_id from token no longer exists in DB
        InactiveUserError   — user exists but is_active=False
        UnverifiedUserError — user exists but is_verified=False
    """
    result = await db.execute(select(User).where(User.id == user_id))
    user: User | None = result.scalar_one_or_none()

    if user is None:
        raise UserNotFoundError(f"No user found for id={user_id}")

    if not user.is_active:
        raise InactiveUserError("This account has been deactivated")

    if not user.is_verified:
        raise UnverifiedUserError("Email address has not been verified")

    return user
