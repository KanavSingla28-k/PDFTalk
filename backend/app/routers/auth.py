from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status, Cookie
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.rate_limit import RateLimiter
from app.auth.tokens import (
    TokenInvalidError,
    revoke_refresh_token,
    validate_and_rotate_refresh_token,
)
from app.core.config import settings
from app.db.session import get_db
from app.models.auth import RegisterRequest, RegisterResponse, LoginRequest, LoginResponse, UserInfo, RefreshResponse
from app.services import user_service
from app.services.email_verification import verify_token
from app.services.user_service import login as login_user
from app.exceptions import (
    InvalidCredentialsError,
    UnverifiedEmailError
)
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

_login_limiter = RateLimiter(
    limit=10,
    window_seconds=60,  # 10 login attempts per IP per minute (T-20 spec)
    key_prefix="login",
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
    _rate: None = Depends(_register_limiter),  # T-42 rate limit now wired up
) -> RegisterResponse:
    await user_service.register(
        db=db,
        email=payload.email,
        password=payload.password,
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
    """
    try:
        await verify_token(raw_token=token, db=db)
        await db.commit()
    except ValueError as exc:
        msg = str(exc).lower()
        slug = "token_expired" if "expired" in msg else "invalid_token"
        return RedirectResponse(
            url=f"{settings.APP_URL}/verify-email?error={slug}",
            status_code=302,
        )

    return RedirectResponse(
        url=f"{settings.APP_URL}/login?verified=true",
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
                   path="/auth/refresh" means it's only sent on that one route,
                   not on every API call, minimising the attack surface.

    The 401 message is deliberately identical for all failure cases
    (wrong email, wrong password, inactive account, locked account) to deny
    an attacker any signal about which check failed.
    """
    try:
        access_token, raw_refresh_token, expires_in = await login_user(
            db=db,
            email=payload.email,
            password=payload.password,
        )
    except UnverifiedEmailError:
        raise 
    except InvalidCredentialsError:
        raise

    # ------------------------------------------------------------------
    # Set the refresh token as an httpOnly cookie.
    #
    # Key settings:
    #   httponly=True   — JS cannot read this cookie; XSS cannot steal it
    #   secure=True     — only sent over HTTPS (enforced by Nginx in prod)
    #   samesite="strict" — not sent on cross-site requests; CSRF mitigation
    #   path="/auth"
    # ------------------------------------------------------------------
    response.set_cookie(
        key="refresh_token",
        value=raw_refresh_token,
        httponly=True,
        secure=False,        # TODO: change to true in after domain cert certification
        samesite="strict",
        max_age=60 * 60 * 24 * 7,  # 7 days — matches REFRESH_TOKEN_EXPIRE_DAYS
        path="/auth",
    )

    # Fetch the user record to populate UserInfo in the response.
    # The login service already validated the user exists and is active,
    # so this select cannot return None — it's safe to assert.
    from sqlalchemy import select
    from app.models.user import User

    result = await db.execute(
        select(User.id, User.email).where(
            User.email_lower == payload.email.lower().strip()
        )
    )
    row = result.one()

    return LoginResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=expires_in,
        user=UserInfo(id=str(row.id), email=row.email),
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
) -> RefreshResponse:
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
        response.delete_cookie(key="refresh_token", path="/auth")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Overwrite the old cookie with the new refresh token.
    # All settings must mirror the login cookie exactly so the browser
    # replaces rather than accumulates a second cookie.
    response.set_cookie(
        key="refresh_token",
        value=new_raw_refresh_token,
        httponly=True,
        secure=False,        # TODO: flip to True once TLS cert is in place (T-10)
        samesite="strict",
        max_age=60 * 60 * 24 * 7,  # 7 days — matches REFRESH_TOKEN_EXPIRE_DAYS
        path="/auth",
    )

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
    # delete_cookie must use the same path/samesite/secure settings that
    # set_cookie used, or the browser will not remove it.
    response.delete_cookie(
        key="refresh_token",
        path="/auth",
        samesite="strict",
        secure=False,        # TODO: flip to True once TLS cert is in place (T-10)
    )