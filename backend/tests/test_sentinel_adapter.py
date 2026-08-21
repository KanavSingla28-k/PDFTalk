"""
Tests for the Sentinel adapter in app/core/sentinel.py.

These tests verify that the PDFTalk/Sentinel integration correctly:
- Converts Sentinel's 429 to RateLimitExceededError with proper retry_after
- Converts Sentinel's 503 to RateLimiterUnavailableError
- Handles sliding window (no Retry-After) by falling back to 60 seconds
- Handles token bucket (with Retry-After) by passing through the value
- Does not swallow unexpected HTTP status codes
- Routes anonymous and tenant guards to correct Sentinel factories
"""

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException, Request, Response

from app.core.sentinel import (
    _adapt_sentinel_error,
    _make_anonymous_guard,
    _make_tenant_guard,
)
from app.exceptions import RateLimiterUnavailableError, RateLimitExceededError


class TestSentinelAdapter:
    """Tests for the Sentinel error adapter."""

    @pytest.fixture
    def mock_request(self):
        request = MagicMock(spec=Request)
        return request

    @pytest.mark.asyncio
    async def test_adapt_429_with_retry_after_header(self, mock_request):
        """Token bucket 429 with Retry-After header should pass through the value."""
        exc = HTTPException(
            status_code=429,
            detail="rate limit exceeded",
            headers={"Retry-After": "30"},
        )

        with pytest.raises(RateLimitExceededError) as exc_info:
            await _adapt_sentinel_error(mock_request, exc)

        assert exc_info.value.retry_after == 30

    @pytest.mark.asyncio
    async def test_adapt_429_without_retry_after_header(self, mock_request):
        """Sliding window 429 without Retry-After should fall back to 60 seconds."""
        exc = HTTPException(
            status_code=429,
            detail="rate limit exceeded",
            headers={},  # No Retry-After
        )

        with pytest.raises(RateLimitExceededError) as exc_info:
            await _adapt_sentinel_error(mock_request, exc)

        assert exc_info.value.retry_after == 60

    @pytest.mark.asyncio
    async def test_adapt_429_with_invalid_retry_after(self, mock_request):
        """Non-numeric Retry-After should fall back to 60 seconds."""
        exc = HTTPException(
            status_code=429,
            detail="rate limit exceeded",
            headers={"Retry-After": "not-a-number"},
        )

        with pytest.raises(RateLimitExceededError) as exc_info:
            await _adapt_sentinel_error(mock_request, exc)

        assert exc_info.value.retry_after == 60

    @pytest.mark.asyncio
    async def test_adapt_503(self, mock_request):
        """503 should become RateLimiterUnavailableError."""
        exc = HTTPException(
            status_code=503,
            detail="rate limiter unavailable",
        )

        with pytest.raises(RateLimiterUnavailableError):
            await _adapt_sentinel_error(mock_request, exc)

    @pytest.mark.asyncio
    async def test_adapt_unexpected_status_re_raises(self, mock_request):
        """Unexpected status codes should be re-raised, not swallowed."""
        exc = HTTPException(status_code=400, detail="bad request")

        with pytest.raises(HTTPException) as exc_info:
            await _adapt_sentinel_error(mock_request, exc)

        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_adapt_404_re_raises(self, mock_request):
        """404 (unknown endpoint) should be re-raised."""
        exc = HTTPException(status_code=404, detail="unknown endpoint")

        with pytest.raises(HTTPException) as exc_info:
            await _adapt_sentinel_error(mock_request, exc)

        assert exc_info.value.status_code == 404


class TestGuardFactories:
    """Tests that guard factories route to correct Sentinel methods."""

    @pytest.mark.asyncio
    async def test_make_tenant_guard_calls_guard_for(self, monkeypatch):
        """Tenant guard should call guard.guard_for."""
        from app.core import sentinel

        # guard_for returns an async function, so we need to mock it properly
        async def mock_guard_func(request):
            pass

        mock_guard = MagicMock()  # Use MagicMock, not AsyncMock
        mock_guard.guard_for.return_value = mock_guard_func
        monkeypatch.setattr(sentinel, "guard", mock_guard)

        dep = _make_tenant_guard("test.endpoint")
        mock_request = MagicMock(spec=Request)

        await dep(mock_request)

        mock_guard.guard_for.assert_called_once_with("test.endpoint")

    @pytest.mark.asyncio
    async def test_make_anonymous_guard_calls_anonymous_guard_for(self, monkeypatch):
        """Anonymous guard should call guard.anonymous_guard_for."""
        from app.core import sentinel

        async def mock_anon_guard_func(request, response):
            pass

        mock_guard = MagicMock()  # Use MagicMock, not AsyncMock
        mock_guard.anonymous_guard_for.return_value = mock_anon_guard_func
        monkeypatch.setattr(sentinel, "guard", mock_guard)

        dep = _make_anonymous_guard("test.anon")
        mock_request = MagicMock(spec=Request)
        mock_response = MagicMock(spec=Response)

        await dep(mock_request, mock_response)

        mock_guard.anonymous_guard_for.assert_called_once_with("test.anon")

    @pytest.mark.asyncio
    async def test_tenant_guard_converts_429(self, monkeypatch):
        """Tenant guard should adapt 429 to RateLimitExceededError."""
        from app.core import sentinel

        async def mock_guard_func(request):
            raise HTTPException(
                status_code=429,
                detail="rate limit exceeded",
                headers={"Retry-After": "45"},
            )

        mock_guard = MagicMock()  # Use MagicMock, not AsyncMock
        mock_guard.guard_for.return_value = mock_guard_func
        monkeypatch.setattr(sentinel, "guard", mock_guard)

        dep = _make_tenant_guard("test.endpoint")
        mock_request = MagicMock(spec=Request)

        with pytest.raises(RateLimitExceededError) as exc_info:
            await dep(mock_request)

        assert exc_info.value.retry_after == 45

    @pytest.mark.asyncio
    async def test_anonymous_guard_converts_503(self, monkeypatch):
        """Anonymous guard should adapt 503 to RateLimiterUnavailableError."""
        from app.core import sentinel

        async def mock_anon_guard_func(request, response):
            raise HTTPException(
                status_code=503,
                detail="rate limiter unavailable",
            )

        mock_guard = MagicMock()  # Use MagicMock, not AsyncMock
        mock_guard.anonymous_guard_for.return_value = mock_anon_guard_func
        monkeypatch.setattr(sentinel, "guard", mock_guard)

        dep = _make_anonymous_guard("test.anon")
        mock_request = MagicMock(spec=Request)
        mock_response = MagicMock(spec=Response)

        with pytest.raises(RateLimiterUnavailableError):
            await dep(mock_request, mock_response)


class TestExportedGuards:
    """Verify all expected guards are exported."""

    def test_all_guards_exported(self):
        from app.core.sentinel import (
            chat_create_guard,
            login_guard,
            query_guard,
            register_guard,
            resend_guard,
            reset_guard,
            upload_guard,
        )

        guards = [
            register_guard,
            resend_guard,
            login_guard,
            reset_guard,
            upload_guard,
            query_guard,
            chat_create_guard,
        ]

        for guard in guards:
            assert guard is not None
            # Each guard is a callable (function)
            assert callable(guard)


class TestPolicyConfiguration:
    """Verify the policy configuration matches expectations."""

    def test_seven_policies_defined(self):
        from app.core.sentinel import config

        assert len(config.policies) == 7
        expected_ids = {
            "pdftalk.auth.register",
            "pdftalk.auth.resend",
            "pdftalk.auth.login",
            "pdftalk.auth.reset",
            "pdftalk.documents.upload",
            "pdftalk.query.ask",
            "pdftalk.chats.create",
        }
        assert set(config.policies.keys()) == expected_ids

    def test_anonymous_policies_use_token_bucket(self):
        from sentinel.models import AlgorithmType

        from app.core.sentinel import config

        for policy_id in [
            "pdftalk.auth.register",
            "pdftalk.auth.resend",
            "pdftalk.auth.login",
            "pdftalk.auth.reset",
        ]:
            policy = config.policies[policy_id]
            assert policy.identity == "anonymous"
            assert policy.algorithm == AlgorithmType.TOKEN_BUCKET
            assert policy.fail_mode.value == "fail_open"

    def test_tenant_policies_use_sliding_window(self):
        from sentinel.models import AlgorithmType

        from app.core.sentinel import config

        for policy_id in [
            "pdftalk.documents.upload",
            "pdftalk.query.ask",
            "pdftalk.chats.create",
        ]:
            policy = config.policies[policy_id]
            assert policy.identity == "tenant_jwt"
            assert policy.algorithm == AlgorithmType.SLIDING_WINDOW
            assert policy.fail_mode.value == "fail_open"

    def test_upload_policy_shared(self):
        """Upload and initiate-upload should share the same policy."""
        from app.core.sentinel import config

        # Both endpoints use upload_guard which wraps pdftalk.documents.upload
        policy = config.policies["pdftalk.documents.upload"]
        assert policy.limit == 5
        assert policy.window_size_micro == 60_000_000
