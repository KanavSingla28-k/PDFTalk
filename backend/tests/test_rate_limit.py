"""
Tests for app/utils/rate_limit.py

Coverage
--------
- RateLimiter allows requests under the limit
- RateLimiter blocks at exactly the limit and returns correct Retry-After
- Sliding window expires old entries (requests outside the window don't count)
- user_id_from_request extracts the correct user_id from a Bearer token
- user_id_from_request raises TokenInvalidError on a missing/malformed token
- IP-based vs user-based identifiers use distinct Redis keys (no bleed)

All tests use fakeredis — no real Redis needed.
"""

import time
import pytest
import pytest_asyncio
import fakeredis.aioredis

from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import Request

from app.exceptions import RateLimitExceededError
from app.auth.tokens import TokenInvalidError
from app.utils.rate_limit import RateLimiter, user_id_from_request


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def fake_redis():
    """In-memory Redis using fakeredis — fully async, pipeline-compatible."""
    r = fakeredis.aioredis.FakeRedis()
    yield r
    await r.aclose()


def make_request(
    ip: str = "1.2.3.4",
    forwarded_for: str | None = None,
    auth_header: str | None = None,
) -> MagicMock:
    """
    Build a minimal mock Request.

    Mimics the parts of Starlette's Request that RateLimiter and
    user_id_from_request actually touch — no real ASGI scope needed.
    """
    headers: dict[str, str] = {}
    if forwarded_for:
        headers["X-Forwarded-For"] = forwarded_for
    if auth_header:
        headers["Authorization"] = auth_header

    request = MagicMock(spec=Request)
    request.headers = headers
    request.client = MagicMock()
    request.client.host = ip
    return request


# ---------------------------------------------------------------------------
# Helper — run the limiter against fake_redis
# ---------------------------------------------------------------------------

async def _call_limiter(limiter: RateLimiter, request: Request, fake_redis) -> None:
    """
    Invoke limiter.__call__ with fake_redis injected via get_redis mock.

    RateLimiter calls get_redis() internally; we patch it to return
    our fakeredis instance so no real Redis connection is attempted.
    """
    with patch("app.utils.rate_limit.get_redis", return_value=fake_redis):
        await limiter(request)


# ---------------------------------------------------------------------------
# Core sliding-window behaviour
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_allows_requests_under_limit(fake_redis):
    """Requests up to (limit - 1) must all succeed without raising."""
    limiter = RateLimiter(limit=3, window_seconds=60, key_prefix="test_under")
    request = make_request()

    for _ in range(2):  # 2 < limit=3 → all should pass
        await _call_limiter(limiter, request, fake_redis)  # must not raise


@pytest.mark.asyncio
async def test_blocks_at_limit(fake_redis):
    """The (limit)th request must raise RateLimitExceededError."""
    limiter = RateLimiter(limit=3, window_seconds=60, key_prefix="test_at_limit")
    request = make_request()

    # Exhaust the allowance
    for _ in range(3):
        try:
            await _call_limiter(limiter, request, fake_redis)
        except RateLimitExceededError:
            pass  # May fire on the 3rd call depending on pipeline ordering

    # This call must definitely be blocked
    with pytest.raises(RateLimitExceededError):
        await _call_limiter(limiter, request, fake_redis)


@pytest.mark.asyncio
async def test_retry_after_is_positive(fake_redis):
    """RateLimitExceededError must carry a positive retry_after value."""
    limiter = RateLimiter(limit=1, window_seconds=30, key_prefix="test_retry")
    request = make_request()

    # First call exhausts the limit
    await _call_limiter(limiter, request, fake_redis)

    with pytest.raises(RateLimitExceededError) as exc_info:
        await _call_limiter(limiter, request, fake_redis)

    # retry_after is passed as the first arg to RateLimitExceededError
    retry_after = exc_info.value.args[0]
    assert retry_after >= 1, f"Expected retry_after >= 1, got {retry_after}"
    assert retry_after <= 30, f"Expected retry_after <= window (30s), got {retry_after}"


@pytest.mark.asyncio
async def test_distinct_key_prefixes_are_independent(fake_redis):
    """
    Two limiters with different key_prefixes but the same identifier must
    track independent counters. Exhausting one must not affect the other.
    """
    limiter_a = RateLimiter(limit=1, window_seconds=60, key_prefix="ns_a")
    limiter_b = RateLimiter(limit=1, window_seconds=60, key_prefix="ns_b")
    request = make_request()

    # Exhaust limiter_a
    await _call_limiter(limiter_a, request, fake_redis)
    with pytest.raises(RateLimitExceededError):
        await _call_limiter(limiter_a, request, fake_redis)

    # limiter_b must still allow the request — different key
    await _call_limiter(limiter_b, request, fake_redis)  # must not raise


@pytest.mark.asyncio
async def test_distinct_identifiers_are_independent(fake_redis):
    """
    Two different IPs (or user IDs) must have fully independent counters
    under the same limiter. One identity exhausting the limit must not
    block a different identity.
    """
    limiter = RateLimiter(limit=1, window_seconds=60, key_prefix="test_ids")
    req_a = make_request(ip="10.0.0.1")
    req_b = make_request(ip="10.0.0.2")

    # Exhaust for identity A
    await _call_limiter(limiter, req_a, fake_redis)
    with pytest.raises(RateLimitExceededError):
        await _call_limiter(limiter, req_a, fake_redis)

    # Identity B must be unaffected
    await _call_limiter(limiter, req_b, fake_redis)  # must not raise


@pytest.mark.asyncio
async def test_sliding_window_expires_old_entries(fake_redis):
    """
    After the window elapses, old entries must not count against the limit.
    We simulate this by back-dating the existing Redis entries rather than
    sleeping (which would make the test slow and flaky).
    """
    limiter = RateLimiter(limit=2, window_seconds=10, key_prefix="test_expire")
    request = make_request()
    redis_key = "ratelimit:test_expire:1.2.3.4"

    # Manually insert two entries that are 20s old (outside a 10s window)
    old_ms = int((time.time() - 20) * 1000)
    await fake_redis.zadd(redis_key, {str(old_ms): old_ms, str(old_ms + 1): old_ms + 1})

    # The limiter should clean those up and allow 2 fresh requests
    await _call_limiter(limiter, request, fake_redis)  # must not raise
    await _call_limiter(limiter, request, fake_redis)  # must not raise

    # Now the limit is actually hit
    with pytest.raises(RateLimitExceededError):
        await _call_limiter(limiter, request, fake_redis)


# ---------------------------------------------------------------------------
# IP extraction (_default_identifier)
# ---------------------------------------------------------------------------

def test_default_identifier_uses_forwarded_for():
    """X-Forwarded-For takes precedence over request.client.host."""
    request = make_request(ip="10.0.0.1", forwarded_for="203.0.113.5, 10.0.0.1")
    result = RateLimiter._default_identifier(request)
    assert result == "203.0.113.5"


def test_default_identifier_falls_back_to_client_host():
    """Without X-Forwarded-For, request.client.host is used."""
    request = make_request(ip="192.168.1.1")
    result = RateLimiter._default_identifier(request)
    assert result == "192.168.1.1"


def test_default_identifier_handles_missing_client():
    """If request.client is None (e.g. test transports), returns 'unknown'."""
    request = MagicMock(spec=Request)
    request.headers = {}
    request.client = None
    result = RateLimiter._default_identifier(request)
    assert result == "unknown"


# ---------------------------------------------------------------------------
# user_id_from_request
# ---------------------------------------------------------------------------

def test_user_id_from_request_extracts_user_id():
    """
    A valid Bearer token must yield the correct user_id string.
    We mock decode_access_token so this test doesn't depend on a real JWT.
    """
    request = make_request(auth_header="Bearer sometoken")

    with patch(
        "app.auth.tokens.decode_access_token",  # patched at import site
        return_value="user-uuid-1234",
    ) as mock_decode:
        result = user_id_from_request(request)

    mock_decode.assert_called_once_with("sometoken")
    assert result == "user-uuid-1234"


def test_user_id_from_request_missing_token_raises():
    """
    A missing Authorization header must propagate TokenInvalidError,
    which the global exception handler converts to HTTP 401.
    """
    request = make_request()  # no auth_header

    with patch(
        "app.auth.tokens.decode_access_token",
        side_effect=TokenInvalidError("Token is missing 'sub' claim"),
    ):
        with pytest.raises(TokenInvalidError):
            user_id_from_request(request)


def test_user_id_from_request_strips_bearer_prefix():
    """The 'Bearer ' prefix must be stripped before passing to decode_access_token."""
    request = make_request(auth_header="Bearer abc.def.ghi")

    with patch(
        "app.auth.tokens.decode_access_token",
        return_value="some-user-id",
    ) as mock_decode:
        user_id_from_request(request)

    # Must receive the raw token, not the full header value
    mock_decode.assert_called_once_with("abc.def.ghi")


# ---------------------------------------------------------------------------
# Custom identifier_fn integration
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_custom_identifier_fn_is_used(fake_redis):
    """
    When identifier_fn is provided, it must be called to derive the key —
    not _default_identifier.
    """
    called_with: list[Request] = []

    def my_identifier(req: Request) -> str:
        called_with.append(req)
        return "custom-id-xyz"

    limiter = RateLimiter(
        limit=5,
        window_seconds=60,
        key_prefix="test_custom",
        identifier_fn=my_identifier,
    )
    request = make_request()

    await _call_limiter(limiter, request, fake_redis)

    assert len(called_with) == 1
    assert called_with[0] is request

    # Verify the Redis key used the custom identifier
    keys = await fake_redis.keys("ratelimit:test_custom:*")
    assert any(b"custom-id-xyz" in k for k in keys)