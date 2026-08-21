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
from fastapi.exceptions import RequestValidationError
import logging
import uuid
from app.utils.openai_client import (
    CircuitBreakerOpenError,
    DailyQuotaExceededError,
    OpenAIRetryExhaustedError,
    DailyQueryQuotaExceededError,
)

logger = logging.getLogger(__name__)


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
        super().__init__(retry_after)


class RateLimiterUnavailableError(PDFTalkError):
    """Rate limiter backend (Sentinel Redis) is unavailable.

    Maps to 503 with RATE_LIMITER_UNAVAILABLE error code.
    """


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


class InvalidCredentialsError(AuthError):
    """
    Raised for ANY login failure that should surface as 401.

    Intentionally generic — callers must NOT leak which specific check failed.
    A consistent error message prevents user enumeration (an attacker cannot
    tell whether the email exists, the password is wrong, or the account is
    locked by observing the error text).
    """


class UnverifiedEmailError(AuthError):
    """
    Raised when the account exists but email is not yet verified.

    Surfaced as 403 (not 401) so the frontend can show a distinct
    "resend verification email" prompt rather than a generic login failure.
    This is an acceptable enumeration trade-off: the user has already
    proved they can receive email at that address (they registered), so
    confirming the account exists here leaks nothing new.
    """


class InvalidResetTokenError(PDFTalkError):
    """
    Raised when a password reset token is missing, invalid, or expired.
    Maps to 400 INVALID_OR_EXPIRED_TOKEN.
    """


# ---------------------------------------------------------------------------
# File validation exceptions
# ---------------------------------------------------------------------------


class QuotaExceededError(PDFTalkError):
    """
    Raised by document_service.upload_document() when the user’s document
    quota (per plan) has been reached.

    Maps to 429     Too Many Requests.
    """


# ---------------------------------------------------------------------------
# Document-related exceptions
# ---------------------------------------------------------------------------


class DocumentNotFoundError(PDFTalkError):
    def __init__(self, document_id: uuid.UUID):
        self.document_id = document_id


class DocumentNotReadyError(PDFTalkError):
    def __init__(self, document_id: uuid.UUID, status: str):
        self.document_id = document_id
        self.status = status


class AllDocumentsDeletedError(PDFTalkError):
    pass


class InvalidStatusTransitionError(PDFTalkError):
    """
    Raised when a caller attempts a document status move that violates the
    state machine defined in _ALLOWED_TRANSITIONS.

    Maps to 409 Conflict — the request is syntactically valid but conflicts
    with the current resource state.

    Attributes:
        document_id: the document whose transition was attempted
        from_status: current status at the time of the attempt
        to_status:   the illegal target status
    """

    def __init__(
        self,
        document_id: uuid.UUID,
        from_status: object,  # DocumentStatus enum — typed loosely to avoid circular import
        to_status: object,
    ) -> None:
        self.document_id = document_id
        self.from_status = from_status
        self.to_status = to_status
        super().__init__(f"Document {document_id}: cannot transition {from_status} → {to_status}")


# ---------------------------------------------------------------------------
# File validation exceptions
# ---------------------------------------------------------------------------


class FileValidationError(PDFTalkError):
    """
    Raised by services/file_validation.py when an uploaded file fails any
    validation check. The reason field is a stable machine-readable code
    suitable for logging and frontend display logic.

    Maps to 422 Unprocessable Entity.

    Reasons:
        file_too_large       — exceeds MAX_FILE_SIZE_BYTES (50 MB)
        unsupported_mime     — MIME type not in the allow-list
        invalid_magic_bytes  — magic bytes contradict the declared MIME type
                               (e.g. file claimed to be PDF but header is not %PDF)
    """

    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        super().__init__(message)


# ---------------------------------------------------------------------------
# Ingestion / Processing exceptions
# ---------------------------------------------------------------------------


class ExtractionError(PDFTalkError):
    """
    Raised when text extraction from a document fails.
    """

    def __init__(self, reason: str, s3_key: str) -> None:
        self.reason = reason
        self.s3_key = s3_key
        super().__init__(f"ExtractionError({reason!r}) for key={s3_key!r}")


class ChunkingError(PDFTalkError):
    """
    Raised when chunking a document fails or limits are exceeded.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)


# ---------------------------------------------------------------------------
# Chat exceptions
# ---------------------------------------------------------------------------


class ChatNotFoundError(PDFTalkError):
    pass


class MessageNotFoundError(PDFTalkError):
    pass


class EmptyDocumentListError(PDFTalkError):
    pass


class InvalidDocumentSelectionError(PDFTalkError):
    pass


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
    async def expired_token_handler(request: Request, exc: ExpiredTokenError) -> JSONResponse:
        return JSONResponse(
            status_code=401,
            content={
                "error": "TOKEN_EXPIRED",
                "message": str(exc) or "Access token has expired",
            },
        )

    @app.exception_handler(InvalidTokenError)
    async def invalid_token_handler(request: Request, exc: InvalidTokenError) -> JSONResponse:
        return JSONResponse(
            status_code=401,
            content={
                "error": "INVALID_TOKEN",
                "message": str(exc) or "Invalid or missing token",
            },
        )

    @app.exception_handler(UserNotFoundError)
    async def user_not_found_handler(request: Request, exc: UserNotFoundError) -> JSONResponse:
        # 401, not 404 — don't reveal whether the user ever existed
        return JSONResponse(
            status_code=401,
            content={
                "error": "INVALID_TOKEN",
                "message": "Could not validate credentials",
            },
        )

    @app.exception_handler(InactiveUserError)
    async def inactive_user_handler(request: Request, exc: InactiveUserError) -> JSONResponse:
        return JSONResponse(
            status_code=403,
            content={
                "error": "ACCOUNT_INACTIVE",
                "message": str(exc) or "This account has been deactivated",
            },
        )

    @app.exception_handler(UnverifiedUserError)
    async def unverified_user_handler(request: Request, exc: UnverifiedUserError) -> JSONResponse:
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

    @app.exception_handler(InvalidResetTokenError)
    async def invalid_reset_token_handler(
        request: Request,
        exc: InvalidResetTokenError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={
                "error": "INVALID_OR_EXPIRED_TOKEN",
                "message": str(exc) or "This password reset link is invalid or has expired.",
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

    @app.exception_handler(RateLimiterUnavailableError)
    async def rate_limiter_unavailable_handler(
        request: Request,
        exc: RateLimiterUnavailableError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "error": "RATE_LIMITER_UNAVAILABLE",
                "message": "Rate limiter temporarily unavailable",
            },
        )

    @app.exception_handler(FileValidationError)
    async def file_validation_handler(
        request: Request,
        exc: FileValidationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": "FILE_VALIDATION_FAILED",
                "reason": exc.reason,
                "message": str(exc),
            },
        )

    @app.exception_handler(DocumentNotFoundError)
    async def document_not_found_handler(
        request: Request,
        exc: DocumentNotFoundError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={
                "error": "DOCUMENT_NOT_FOUND",
                "message": f"Document {exc.document_id} not found",
            },
        )

    @app.exception_handler(DocumentNotReadyError)
    async def document_not_ready_handler(
        request: Request,
        exc: DocumentNotReadyError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={
                "error": "DOCUMENT_NOT_READY",
                "message": (
                    f"Document {exc.document_id} is not ready for querying "
                    f"(current status: {exc.status})"
                ),
            },
        )

    @app.exception_handler(AllDocumentsDeletedError)
    async def all_documents_deleted_handler(
        request: Request,
        exc: AllDocumentsDeletedError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={
                "error": "ALL_DOCUMENTS_DELETED",
                "message": "All documents attached to this chat have been deleted.",
            },
        )

    @app.exception_handler(InvalidStatusTransitionError)
    async def invalid_status_transition_handler(
        request: Request,
        exc: InvalidStatusTransitionError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={
                "error": "INVALID_STATUS_TRANSITION",
                "message": str(exc),
            },
        )

    @app.exception_handler(CircuitBreakerOpenError)
    async def circuit_breaker_handler(
        request: Request,
        exc: CircuitBreakerOpenError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "error": "AI_SERVICE_UNAVAILABLE",
                "message": "The AI service is temporarily unavailable. Please try again shortly.",
            },
        )

    @app.exception_handler(OpenAIRetryExhaustedError)
    async def openai_retry_exhausted_handler(
        request: Request,
        exc: OpenAIRetryExhaustedError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "error": "AI_SERVICE_UNAVAILABLE",
                "message": "The AI service is temporarily unavailable. Please try again shortly.",
            },
        )

    @app.exception_handler(DailyQuotaExceededError)
    async def daily_quota_handler(
        request: Request,
        exc: DailyQuotaExceededError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=429,
            content={
                "error": "DAILY_QUOTA_EXCEEDED",
                "message": str(exc),
            },
        )

    @app.exception_handler(DailyQueryQuotaExceededError)
    async def daily_query_quota_handler(
        request: Request,
        exc: DailyQueryQuotaExceededError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=429,
            content={
                "error": "DAILY_QUERY_QUOTA_EXCEEDED",
                "message": str(exc),
            },
        )

    @app.exception_handler(ChatNotFoundError)
    async def chat_not_found_handler(
        request: Request,
        exc: ChatNotFoundError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={
                "error": "CHAT_NOT_FOUND",
                "message": "Chat not found",
            },
        )

    @app.exception_handler(MessageNotFoundError)
    async def message_not_found_handler(
        request: Request,
        exc: MessageNotFoundError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={
                "error": "MESSAGE_NOT_FOUND",
                "message": "Message not found",
            },
        )

    @app.exception_handler(EmptyDocumentListError)
    async def empty_document_list_handler(
        request: Request,
        exc: EmptyDocumentListError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={
                "error": "EMPTY_DOCUMENT_LIST",
                "message": "At least one document must be selected",
            },
        )

    @app.exception_handler(InvalidDocumentSelectionError)
    async def invalid_document_selection_handler(
        request: Request,
        exc: InvalidDocumentSelectionError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={
                "error": "INVALID_DOCUMENT_SELECTION",
                "message": "Invalid document selection",
            },
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_exception_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        logger.warning("Validation error on %s %s: %s", request.method, request.url, exc.errors())
        return JSONResponse(
            status_code=422,
            content={
                "error": "VALIDATION_ERROR",
                "message": "The request contained invalid data.",
            },
        )
