import structlog
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from typing import Literal

from starlette.responses import Response as StarletteResponse

from app.utils.rate_limit import RateLimiter
from app.auth.tokens import (
    TokenExpiredError,
    TokenInvalidError,
    decode_access_token,
    revoke_all_refresh_tokens,
    revoke_refresh_token,
    validate_and_rotate_refresh_token,
)
from app.core.config import settings
from app.db.session import get_db
from app.models.auth import (
    RegisterRequest, RegisterResponse, LoginRequest, LoginResponse,
    UserInfo, MeResponse, RefreshResponse, ResendVerificationRequest,
    ForgotPasswordRequest, ResetPasswordRequest,
)
from app.auth.dependencies import get_verified_user
from app.services import user_service
from app.services.email_verification import verify_token, send_verification_email_for_user
from app.services.password_reset import initiate_password_reset, consume_reset_token
from app.services.user_service import login as login_user
from app.models.user import User


logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

# ---------------------------------------------------------------------------
# Rate limiter instances — defined once at module level, reused per request.
# Each uses a distinct key_prefix so their Redis keys never collide.
# ---------------------------------------------------------------------------

_register_limiter = RateLimiter(
    limit=5,
    window_seconds=3600,  # 5 registrations per IP per hour (T-18 spec)
    key_prefix="register",
)

_resend_limiter = RateLimiter(
    limit=5,
    window_seconds=3600,  # 5 resends per IP per hour
    key_prefix="resend",
)

_login_limiter = RateLimiter(
    limit=10,
    window_seconds=60,  # 10 login attempts per IP per minute (T-20 spec)
    key_prefix="login",
)

_reset_limiter = RateLimiter(
    limit=3,
    window_seconds=3600,  # 3 password resets per IP per hour
    key_prefix="reset",
)

# ---------------------------------------------------------------------------
# Cookie helpers — single source of truth for refresh-token cookie settings
#
# All attributes (secure, samesite, path, max_age) are defined ONCE here.
# When TLS goes live (T-10) flip secure=False → True in _COOKIE_SECURE only.
# ---------------------------------------------------------------------------

_COOKIE_KEY = "refresh_token"
_COOKIE_MAX_AGE = 60 * 60 * 24 * 7   # 7 days — matches REFRESH_TOKEN_EXPIRE_DAYS
_COOKIE_SECURE = False                # TODO: flip to True once TLS cert is in place (T-10)
_COOKIE_SAMESITE: Literal["lax", "strict", "none"] = "strict"
_COOKIE_PATH = "/"


def _set_refresh_cookie(response: Response, raw_token: str) -> None:
    """Attach the refresh-token httpOnly cookie to *response*."""
    response.set_cookie(
        key=_COOKIE_KEY,
        value=raw_token,
        httponly=True,
        secure=_COOKIE_SECURE,
        samesite=_COOKIE_SAMESITE,
        max_age=_COOKIE_MAX_AGE,
        path=_COOKIE_PATH,
    )


def _clear_refresh_cookie(response: Response) -> None:
    """Delete the refresh-token cookie from *response*.

    Must use the same path/samesite/secure settings as _set_refresh_cookie,
    or the browser will not remove the cookie.
    """
    response.delete_cookie(
        key=_COOKIE_KEY,
        path=_COOKIE_PATH,
        samesite=_COOKIE_SAMESITE,
        secure=_COOKIE_SECURE,
    )

# ---------------------------------------------------------------------------
# T-18 — Registration
# ---------------------------------------------------------------------------

@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Register a new account",
    description=(
        "Creates a new user and sends an email verification link. "
        "Always returns 202 regardless of whether the email is already registered, "
        "to prevent user enumeration."
    ),
)
async def register(
    payload: RegisterRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _rate: None = Depends(_register_limiter),
) -> RegisterResponse:
    try:
        await user_service.register(
            db=db,
            email=payload.email,
            password=payload.password,
        )
    except RuntimeError:
        # Email delivery failed (e.g. Resend API error, unverified sender domain).
        # The user row is already committed; return 202 so the frontend can
        # prompt the user to check their inbox or request a resend.
        # The error is already logged inside send_verification_email().
        logger.warning(
            "register: email delivery failed for %s — still returning 202",
            payload.email,
        )
    return RegisterResponse(message="Verification email sent")


@router.post(
    "/resend-verification",
    response_model=RegisterResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Resend verification email",
    description=(
        "Resends a verification email for an unverified account. "
        "Always returns 202 regardless of whether the email is registered or verified, "
        "to prevent user enumeration."
    ),
)
async def resend_verification(
    payload: ResendVerificationRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _rate: None = Depends(_resend_limiter),
) -> RegisterResponse:
    email_lower = payload.email.strip().lower()

    existing = await user_service.get_by_email_lower(db, email_lower)

    if existing is not None:
        if not existing.is_verified:
            try:
                # Delete the stale verification row first so we don't accumulate orphaned tokens
                await user_service._delete_pending_verification(db, existing.id)
                await send_verification_email_for_user(str(existing.id), existing.email, db)
                await db.commit()
            except Exception as exc:
                logger.warning(
                    "resend_verification: email delivery failed for %s: %s",
                    existing.email,
                    exc,
                )
    return RegisterResponse(message="Verification email sent")


# ---------------------------------------------------------------------------
# T-19 — Email verification
# ---------------------------------------------------------------------------

@router.get(
    "/verify-email",
    summary="Verify a user's email address",
    response_class=RedirectResponse,
    status_code=302,
    responses={
        302: {"description": "Redirects to frontend (success or error slug)"},
    },
)
async def verify_email(
    token: str = Query(..., description="Raw verification token from the email link"),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """
    Validates the one-time email verification token sent to the user's inbox.

    Success  → 302 to {APP_URL}/login?verified=true
    Failure  → 302 to {APP_URL}/verify-email?error={slug}

    Error slugs:
      - invalid_token  — hash not found (never existed, already used, tampered)
      - token_expired  — found but past its 24-hour window

    is_verified is now set atomically inside verify_token() in the same
    transaction as the token deletion, so there is no separate SELECT+UPDATE.
    """
    try:
        # verify_token() atomically deletes the token AND marks is_verified=True.
        await verify_token(raw_token=token, db=db)
        await db.commit()
    except ValueError as exc:
        msg = str(exc).lower()
        slug = "token_expired" if "expired" in msg else "invalid_token"
        return RedirectResponse(
            url=f"{settings.APP_URL}/auth/verify-email?error={slug}",
            status_code=302,
        )

    return RedirectResponse(
        url=f"{settings.APP_URL}/auth/login?verified=true",
        status_code=302,
    )


# ---------------------------------------------------------------------------
# T-20 — Login
# ---------------------------------------------------------------------------

@router.post(
    "/login",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
    summary="Authenticate and receive tokens",
    description=(
        "Validates credentials and issues an access token (JSON body) plus a "
        "refresh token (httpOnly cookie). "
        "Returns 401 for any credential failure — intentionally generic to "
        "prevent user enumeration. "
        "Returns 403 if the account email has not been verified yet."
    ),
)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    _rate: None = Depends(_login_limiter),
) -> LoginResponse:
    """
    POST /auth/login

    Security contract
    -----------------
    Access token  → JSON body → frontend stores in React memory (never localStorage).
                   XSS can steal it, but it expires in 15 min and cannot be
                   renewed without the httpOnly refresh token cookie. See T-47.

    Refresh token → httpOnly cookie → invisible to JavaScript entirely.
                   path="/" allows Next.js middleware to check for session presence.

    The 401 message is deliberately identical for all failure cases
    (wrong email, wrong password, inactive account, locked account) to deny
    an attacker any signal about which check failed.
    """

    access_token, raw_refresh_token, expires_in, user = await login_user(
        db=db,
        email=payload.email,
        password=payload.password,
    )

    _set_refresh_cookie(response, raw_refresh_token)

    return LoginResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=expires_in,
        user=UserInfo(id=str(user.id), email=user.email),
    )

# ---------------------------------------------------------------------------
# T-21 — Token refresh
# ---------------------------------------------------------------------------

@router.post(
    "/refresh",
    response_model=RefreshResponse,
    status_code=status.HTTP_200_OK,
    summary="Rotate refresh token and issue a new access token",
    description=(
        "Reads the refresh token from the httpOnly cookie, validates it, "
        "immediately deletes it (one-time-use), and issues a fresh access token "
        "plus a new refresh token cookie. "
        "Returns 401 if the cookie is missing, the token is unknown, or it has expired."
    ),
)
async def refresh(
    response: Response,
    db: AsyncSession = Depends(get_db),
    refresh_token: str | None = Cookie(default=None),
) -> RefreshResponse | JSONResponse:
    """
    POST /auth/refresh

    Token rotation contract
    -----------------------
    Every call consumes the presented refresh token and replaces it with a new
    one. If an attacker steals a refresh token and uses it first, the legitimate
    user's next call here will find the token already gone and receive a 401 —
    forcing a re-login and signalling a possible session theft.

    The new refresh token travels as the same httpOnly cookie (path="/auth"),
    overwriting the previous one. The new access token is returned in the JSON
    body exactly like the login response.
    """
    if refresh_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No refresh token provided.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        new_access_token, new_raw_refresh_token = (
            await validate_and_rotate_refresh_token(
                raw_token=refresh_token,
                db=db,
            )
        )
    except TokenInvalidError as exc:
        # Token not found, already used, or expired.
        # Clear the stale cookie so the browser doesn't keep replaying it.
        # Must return JSONResponse instead of raising HTTPException so cookie changes are preserved.
        resp = JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": str(exc)},
            headers={"WWW-Authenticate": "Bearer"},
        )
        _clear_refresh_cookie(resp)
        return resp

    # Overwrite the old cookie with the rotated refresh token.
    _set_refresh_cookie(response, new_raw_refresh_token)

    expires_in = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    return RefreshResponse(
        access_token=new_access_token,
        token_type="bearer",
        expires_in=expires_in,
    )


# ---------------------------------------------------------------------------
# T-21 — Logout
# ---------------------------------------------------------------------------

@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke the current session",
    description=(
        "Deletes the refresh token from the database and clears the httpOnly cookie. "
        "Idempotent — returns 204 even if no cookie is present or the token is "
        "already expired/revoked."
    ),
)
async def logout(
    response: Response,
    db: AsyncSession = Depends(get_db),
    refresh_token: str | None = Cookie(default=None),
) -> None:
    """
    POST /auth/logout

    Why server-side deletion matters
    ---------------------------------
    Clearing the cookie on the client is not sufficient. An attacker who
    already copied the cookie value (e.g. from a shared browser session) could
    still use it. Deleting the DB row ensures the token is dead regardless of
    what the client does.

    revoke_refresh_token() silently succeeds if the token is not found — it was
    already expired or revoked — so this endpoint is safely idempotent.
    """
    if refresh_token is not None:
        await revoke_refresh_token(raw_token=refresh_token, db=db)

    # Always clear the cookie, even if it was absent or already revoked.
    _clear_refresh_cookie(response)

# ---------------------------------------------------------------------------
# T-47 — GET /auth/me (with silent refresh fallback)
# ---------------------------------------------------------------------------

@router.get(
    "/me",
    response_model=MeResponse,
    summary="Get current user — silently refreshes session if access token is absent",
    description=(
        "Primary path: Bearer token present → validates it → returns user (no new tokens).\n"
        "Fallback path: no/expired Bearer token + valid refresh cookie → "
        "rotates refresh token, sets new cookie, returns user + fresh access token.\n"
        "Returns 401 if neither is valid."
    ),
)
async def get_me(
    response: Response,
    request: Request,
    db: AsyncSession = Depends(get_db),
    refresh_token: str | None = Cookie(default=None),
) -> MeResponse | StarletteResponse:
    """
    Page-reload auth state restoration.

    On every hard reload the frontend calls this endpoint before rendering
    protected pages. Two paths:

    1. Valid Bearer token in Authorization header
       → decode it → fetch user → return UserInfo (no token rotation).
       Fast path — no cookie touched, no DB write.

    2. No/expired Bearer token + refresh cookie present
       → validate_and_rotate_refresh_token()
       → set new refresh cookie (same settings as /auth/login)
       → return user + new access_token so the frontend can restore
         its in-memory token without a second round trip.

    401 if both are absent or invalid.
    """
    from sqlalchemy import select as sa_select
    from app.models.user import User as UserModel

    # ── Path 1: try the Bearer token first ──────────────────────────────
    # Only fall through to the cookie path if the token itself is invalid
    # or expired. If the token is valid but the account is deactivated or
    # unverified, we must return 401 immediately — not silently hand off to
    # the cookie path, which would let a deactivated user restore a session
    # via page reload (I-07).
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        raw_token = auth_header.removeprefix("Bearer ").strip()
        try:
            user_id_str = decode_access_token(raw_token)
            result = await db.execute(
                sa_select(UserModel).where(UserModel.id == uuid.UUID(user_id_str))
            )
            user = result.scalar_one_or_none()

            if user is None:
                # Token is valid but user no longer exists — treat as 401.
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Not authenticated",
                    headers={"WWW-Authenticate": "Bearer"},
                )

            if not user.is_active:
                # Explicitly reject deactivated accounts — do not fall through.
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Not authenticated",
                    headers={"WWW-Authenticate": "Bearer"},
                )

            if not user.is_verified:
                # Explicitly reject unverified accounts — do not fall through.
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Not authenticated",
                    headers={"WWW-Authenticate": "Bearer"},
                )

            return MeResponse(id=str(user.id), email=user.email)

        except HTTPException:
            raise  # propagate our explicit 401s above unchanged
        except (TokenInvalidError, TokenExpiredError):
            pass  # token is genuinely invalid/expired — fall through to cookie path
        except Exception:
            pass  # any other decode failure — fall through to cookie path

    # ── Path 2: silent refresh via cookie ───────────────────────────────
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        new_access_token, new_raw_refresh = await validate_and_rotate_refresh_token(
            raw_token=refresh_token,
            db=db,
        )
    except TokenInvalidError as exc:
        resp = JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": str(exc)},
            headers={"WWW-Authenticate": "Bearer"},
        )
        _clear_refresh_cookie(resp)
        return resp

    # Decode the new access token to get user_id, then fetch user
    user_id_str = decode_access_token(new_access_token)
    result = await db.execute(
        sa_select(UserModel).where(UserModel.id == uuid.UUID(user_id_str))
    )
    user = result.scalar_one_or_none()

    if not user or not user.is_active or not user.is_verified:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    # Set the rotated refresh token cookie
    _set_refresh_cookie(response, new_raw_refresh)

    expires_in = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    return MeResponse(
        id=str(user.id),
        email=user.email,
        access_token=new_access_token,
        token_type="bearer",
        expires_in=expires_in,
    )

# ---------------------------------------------------------------------------
# T-66 — Password Reset
# ---------------------------------------------------------------------------

@router.post(
    "/forgot-password",
    response_model=RegisterResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Request a password reset",
)
async def forgot_password(
    payload: ForgotPasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _rate: None = Depends(_reset_limiter),
) -> RegisterResponse:
    import structlog
    _log = structlog.get_logger(__name__)
    
    try:
        await initiate_password_reset(email=payload.email, db=db)
    except Exception as exc:
        _log.error("forgot_password_failed", email=payload.email, error=str(exc))
        
    return RegisterResponse(message="If an account with that email exists, you'll receive an email shortly.")


@router.post(
    "/reset-password",
    response_model=RegisterResponse,
    status_code=status.HTTP_200_OK,
    summary="Reset password with token",
)
async def reset_password(
    payload: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
) -> RegisterResponse:
    await consume_reset_token(
        raw_token=payload.token,
        new_password=payload.new_password,
        db=db,
    )
    await db.commit()
    return RegisterResponse(message="Password updated. Please log in.")


# ---------------------------------------------------------------------------
# F-02 — DELETE /auth/sessions (revoke all sessions)
# ---------------------------------------------------------------------------

@router.delete(
    "/sessions",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke all active sessions",
    description=(
        "Immediately invalidates every refresh token for the authenticated user. "
        "All devices (browser tabs, mobile apps, etc.) will be signed out on their "
        "next token refresh. "
        "The caller's own refresh-token cookie is also cleared. "
        "Returns 204 on success."
    ),
)
async def revoke_all_sessions(
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: User =Depends(get_verified_user),
) -> None:
    """
    DELETE /auth/sessions

    Security use-case
    -----------------
    A user who suspects their account is compromised can call this endpoint
    to invalidate every active session in a single request. Any refresh token
    that subsequently arrives (from an attacker's device) will not be found
    in the DB and will receive a 401.

    The caller's own access token remains valid until its 15-minute expiry
    (stateless JWTs cannot be revoked without a denylist). The cookie is
    cleared immediately so this browser tab also requires re-login on next
    page load.
    """
    await revoke_all_refresh_tokens(user_id=current_user.id, db=db)
    # Clear the caller's own cookie so this browser also requires re-login
    _clear_refresh_cookie(response)
