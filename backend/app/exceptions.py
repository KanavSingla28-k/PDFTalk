"""
Typed exception hierarchy for PDFTalk.

Design:
  - All domain exceptions inherit from PDFTalkError (not from HTTPException).
    Services raise typed exceptions; the centralized handlers in
    register_exception_handlers() translate them to HTTP responses.
  - This keeps services framework-agnostic and testable without a running
    ASGI app.
  - HTTP status codes and response shapes are defined exactly once, here.
  - Adding a new exception = add a subclass + one handler registration.
    Nothing else changes.

Response shape (all errors):
    {
        "error": "SCREAMING_SNAKE_CASE_CODE",
        "message": "Human-readable description"
    }
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class PDFTalkError(Exception):
    """Root for all application-level exceptions."""

# ---------------------------------------------------------------------------
# PDFTalk Error
# ---------------------------------------------------------------------------

class RateLimitExceededError(PDFTalkError):
    def __init__(self, retry_after: int):
        self.retry_after = retry_after
        super().__init__("Too many requests. Please wait before retrying.")

# ---------------------------------------------------------------------------
# Auth exceptions
# ---------------------------------------------------------------------------

class AuthError(PDFTalkError):
    """Base for all authentication / authorisation failures."""


class InvalidTokenError(AuthError):
    """
    JWT is malformed, has wrong type, missing claims, or signature is bad.
    Maps to 401.
    """


class ExpiredTokenError(AuthError):
    """
    JWT is structurally valid but past its exp claim.
    Kept separate from InvalidTokenError so callers can prompt a silent
    refresh rather than a full re-login.
    Maps to 401.
    """


class InactiveUserError(AuthError):
    """
    User account exists and token is valid, but is_active=False.
    Maps to 403 (authenticated, not authorised).
    """


class UnverifiedUserError(AuthError):
    """
    User account exists and token is valid, but is_verified=False.
    Maps to 403.
    """


class UserNotFoundError(AuthError):
    """
    Token decoded successfully but the user_id in sub no longer exists in the DB.
    Maps to 401 (treat as invalid credential, not 404 — avoids user enumeration).
    """


class InvalidCredentialsError(Exception):
    """
    Raised for ANY login failure that should surface as 401.
 
    Intentionally generic — callers must NOT leak which specific check failed.
    A consistent error message prevents user enumeration (an attacker cannot
    tell whether the email exists, the password is wrong, or the account is
    locked by observing the error text).
    """
 
 
class UnverifiedEmailError(Exception):
    """
    Raised when the account exists but email is not yet verified.
 
    Surfaced as 403 (not 401) so the frontend can show a distinct
    "resend verification email" prompt rather than a generic login failure.
    This is an acceptable enumeration trade-off: the user has already
    proved they can receive email at that address (they registered), so
    confirming the account exists here leaks nothing new.
    """
 
# ---------------------------------------------------------------------------
# Registration handlers
# ---------------------------------------------------------------------------

def register_exception_handlers(app: FastAPI) -> None:
    """
    Attach all domain-exception → HTTP response mappings to the FastAPI app.
    Call once in main.py after creating the app instance.

    Adding a new handler:
        1. Define the exception class above.
        2. Add @app.exception_handler(YourError) here.
        Done.
    """

    @app.exception_handler(ExpiredTokenError)
    async def expired_token_handler(
        request: Request, exc: ExpiredTokenError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=401,
            content={
                "error": "TOKEN_EXPIRED",
                "message": str(exc) or "Access token has expired",
            },
        )

    @app.exception_handler(InvalidTokenError)
    async def invalid_token_handler(
        request: Request, exc: InvalidTokenError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=401,
            content={
                "error": "INVALID_TOKEN",
                "message": str(exc) or "Invalid or missing token",
            },
        )

    @app.exception_handler(UserNotFoundError)
    async def user_not_found_handler(
        request: Request, exc: UserNotFoundError
    ) -> JSONResponse:
        # 401, not 404 — don't reveal whether the user ever existed
        return JSONResponse(
            status_code=401,
            content={
                "error": "INVALID_TOKEN",
                "message": "Could not validate credentials",
            },
        )

    @app.exception_handler(InactiveUserError)
    async def inactive_user_handler(
        request: Request, exc: InactiveUserError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=403,
            content={
                "error": "ACCOUNT_INACTIVE",
                "message": str(exc) or "This account has been deactivated",
            },
        )

    @app.exception_handler(UnverifiedUserError)
    async def unverified_user_handler(
        request: Request, exc: UnverifiedUserError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=403,
            content={
                "error": "EMAIL_NOT_VERIFIED",
                "message": str(exc) or "Please verify your email address before continuing",
            },
        )

    @app.exception_handler(InvalidCredentialsError)
    async def invalid_credentials_handler(
        request: Request,
        exc: InvalidCredentialsError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=401,
            content={
                "error": "INVALID_CREDENTIALS",
                "message": "Invalid credentials",
            },
            headers={"WWW-Authenticate": "Bearer"},
        )

    @app.exception_handler(UnverifiedEmailError)
    async def unverified_email_handler(
        request: Request,
        exc: UnverifiedEmailError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=403,
            content={
                "error": "EMAIL_NOT_VERIFIED",
                "message": str(exc) or "Please verify your email address before continuing",
            },
        )

    @app.exception_handler(RateLimitExceededError)
    async def rate_limit_handler(
        request: Request,
        exc: RateLimitExceededError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=429,
            content={
                "error": "RATE_LIMIT_EXCEEDED",
                "message": str(exc),
            },
            headers={"Retry-After": str(exc.retry_after)},
        )

