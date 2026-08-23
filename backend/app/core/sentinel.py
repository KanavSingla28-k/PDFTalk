"""Sentinel rate limiter integration for PDFTalk.

Builds SentinelConfig from PDFTalk settings, instantiates the Redis client,
script loader, and SentinelGuard, and exports typed FastAPI dependencies
that adapt Sentinel's HTTPException errors to PDFTalk's exception hierarchy.
"""

# from __future__ import annotations

from collections.abc import Awaitable, Callable
from urllib.parse import quote

from fastapi import HTTPException, Request, Response, status
from pydantic import SecretStr
from sentinel.config import AppConfig, SentinelConfig
from sentinel.http import SentinelGuard
from sentinel.models import AlgorithmType, FailMode, IdentityMode, Policy
from sentinel.redis import ScriptLoader, SentinelRedis

from app.core.config import settings
from app.exceptions import RateLimitExceededError


def _build_sentinel_config() -> SentinelConfig:
    """Build SentinelConfig from PDFTalk settings."""
    if settings.SENTINEL_REDIS_URL:
        redis_url = settings.SENTINEL_REDIS_URL
    elif settings.SENTINEL_REDIS_PASSWORD:
        redis_password = quote(settings.SENTINEL_REDIS_PASSWORD, safe="")
        redis_url = f"redis://:{redis_password}@sentinel-redis:6379/0"
    else:
        raise ValueError("Either SENTINEL_REDIS_URL or SENTINEL_REDIS_PASSWORD must be configured")

    if not settings.ANONYMOUS_COOKIE_SECRET:
        raise ValueError("ANONYMOUS_COOKIE_SECRET must be configured for anonymous policies")

    return SentinelConfig(
        app=AppConfig(
            redis_url=redis_url,
            jwt_secret=SecretStr(settings.JWT_SECRET_KEY),
            jwt_algorithm_allowlist=frozenset({settings.JWT_ALGORITHM}),
            anonymous_cookie_secret=SecretStr(settings.ANONYMOUS_COOKIE_SECRET),
            anonymous_cookie_name=settings.ANONYMOUS_COOKIE_NAME,
            anonymous_cookie_ttl_seconds=settings.ANONYMOUS_COOKIE_TTL_SECONDS,
            anonymous_cookie_secure=settings.ANONYMOUS_COOKIE_SECURE,
        ),
        policies={
            "pdftalk.auth.register": Policy(
                endpoint_id="pdftalk.auth.register",
                identity=IdentityMode.ANONYMOUS,
                algorithm=AlgorithmType.TOKEN_BUCKET,
                fail_mode=FailMode.FAIL_OPEN,
                fallback_rate_per_process_micro=1_000_000,
                policy_version=1,
                capacity_micro=5_000_000,
                refill_rate_micro_per_sec=1_389,
            ),
            "pdftalk.auth.resend": Policy(
                endpoint_id="pdftalk.auth.resend",
                identity=IdentityMode.ANONYMOUS,
                algorithm=AlgorithmType.TOKEN_BUCKET,
                fail_mode=FailMode.FAIL_OPEN,
                fallback_rate_per_process_micro=1_000_000,
                policy_version=1,
                capacity_micro=5_000_000,
                refill_rate_micro_per_sec=1_389,
            ),
            "pdftalk.auth.login": Policy(
                endpoint_id="pdftalk.auth.login",
                identity=IdentityMode.ANONYMOUS,
                algorithm=AlgorithmType.TOKEN_BUCKET,
                fail_mode=FailMode.FAIL_OPEN,
                fallback_rate_per_process_micro=1_000_000,
                policy_version=1,
                capacity_micro=10_000_000,
                refill_rate_micro_per_sec=166_667,
            ),
            "pdftalk.auth.reset": Policy(
                endpoint_id="pdftalk.auth.reset",
                identity=IdentityMode.ANONYMOUS,
                algorithm=AlgorithmType.TOKEN_BUCKET,
                fail_mode=FailMode.FAIL_OPEN,
                fallback_rate_per_process_micro=1_000_000,
                policy_version=1,
                capacity_micro=3_000_000,
                refill_rate_micro_per_sec=833,
            ),
            "pdftalk.documents.upload": Policy(
                endpoint_id="pdftalk.documents.upload",
                identity=IdentityMode.TENANT_JWT,
                algorithm=AlgorithmType.SLIDING_WINDOW,
                fail_mode=FailMode.FAIL_OPEN,
                fallback_rate_per_process_micro=1_000_000,
                policy_version=1,
                limit=5,
                window_size_micro=60_000_000,
            ),
            "pdftalk.query.ask": Policy(
                endpoint_id="pdftalk.query.ask",
                identity=IdentityMode.TENANT_JWT,
                algorithm=AlgorithmType.SLIDING_WINDOW,
                fail_mode=FailMode.FAIL_OPEN,
                fallback_rate_per_process_micro=10_000_000,
                policy_version=1,
                limit=20,
                window_size_micro=60_000_000,
            ),
            "pdftalk.chats.create": Policy(
                endpoint_id="pdftalk.chats.create",
                identity=IdentityMode.TENANT_JWT,
                algorithm=AlgorithmType.SLIDING_WINDOW,
                fail_mode=FailMode.FAIL_OPEN,
                fallback_rate_per_process_micro=1_000_000,
                policy_version=1,
                limit=10,
                window_size_micro=60_000_000,
            ),
        },
    )


config = _build_sentinel_config()
redis = SentinelRedis(config.app.redis_url)
loader = ScriptLoader(redis.client)
guard = SentinelGuard(config, redis, loader)


async def _adapt_sentinel_error(request: Request, exc: HTTPException) -> None:
    """Convert Sentinel HTTPException to PDFTalk typed exceptions."""
    if exc.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
        retry_after: str | None = None
        if exc.headers:
            retry_after = exc.headers.get("Retry-After")
        if retry_after and retry_after.isdigit():
            retry_after_seconds = int(retry_after)
        else:
            retry_after_seconds = 60
        raise RateLimitExceededError(retry_after_seconds) from None
    if exc.status_code == status.HTTP_503_SERVICE_UNAVAILABLE:
        # Import locally to avoid circular dependency
        from app.exceptions import RateLimiterUnavailableError

        raise RateLimiterUnavailableError() from None
    raise exc


def _make_tenant_guard(endpoint_id: str) -> Callable[[Request], Awaitable[None]]:
    """Create a FastAPI dependency for tenant-authenticated endpoints."""
    sentinel_dep = guard.guard_for(endpoint_id)

    async def _dep(request: Request) -> None:
        try:
            await sentinel_dep(request)
        except HTTPException as exc:
            await _adapt_sentinel_error(request, exc)

    return _dep


def _make_anonymous_guard(
    endpoint_id: str,
) -> Callable[[Request, Response], Awaitable[None]]:
    """Create a FastAPI dependency for anonymous endpoints."""
    sentinel_dep = guard.anonymous_guard_for(endpoint_id)

    async def _dep(request: Request, response: Response) -> None:
        try:
            await sentinel_dep(request, response)
        except HTTPException as exc:
            await _adapt_sentinel_error(request, exc)

    return _dep


# Exported guard functions — one per rate-limited endpoint
# Use as: Depends(register_guard), Depends(upload_guard), etc.
register_guard = _make_anonymous_guard("pdftalk.auth.register")
resend_guard = _make_anonymous_guard("pdftalk.auth.resend")
login_guard = _make_anonymous_guard("pdftalk.auth.login")
reset_guard = _make_anonymous_guard("pdftalk.auth.reset")

upload_guard = _make_tenant_guard("pdftalk.documents.upload")
query_guard = _make_tenant_guard("pdftalk.query.ask")
chat_create_guard = _make_tenant_guard("pdftalk.chats.create")
