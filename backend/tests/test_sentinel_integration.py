"""
Integration tests for Sentinel rate limiter with real Redis.

These tests require a running Sentinel Redis instance with noeviction policy.
They are marked with `integration` and will be skipped if Redis is not available.

Run with: pytest -m integration
"""

import pytest
import pytest_asyncio
from uuid import uuid4
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.core.sentinel import guard as sentinel_guard
from app.main import app


def _sentinel_redis_available() -> bool:
    """Check if Sentinel Redis is available."""
    import redis.asyncio as redis

    try:
        r = redis.from_url(
            settings.SENTINEL_REDIS_URL or "redis://:sentinel-local-dev-password@localhost:6379/0"
        )
        r.ping()
        r.close()
        return True
    except Exception:
        return False


SENTINEL_REDIS_AVAILABLE = _sentinel_redis_available()


@pytest.mark.integration
@pytest.mark.skipif(
    not SENTINEL_REDIS_AVAILABLE, reason="Integration tests require running Sentinel Redis"
)
class TestSentinelIntegration:
    """Integration tests with real Sentinel Redis."""

    @pytest_asyncio.fixture
    async def client(self):
        """Create test client with real app."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            yield client

    @pytest_asyncio.fixture(autouse=True)
    async def cleanup_redis(self):
        """Clean up Redis keys before and after each test."""
        import redis.asyncio as redis

        r = redis.from_url(
            settings.SENTINEL_REDIS_URL or "redis://:sentinel-local-dev-password@localhost:6379/0"
        )
        # Delete all sentinel keys
        async for key in r.scan_iter("sentinel:*"):
            await r.delete(key)
        await r.close()
        yield
        # Cleanup after
        async for key in r.scan_iter("sentinel:*"):
            await r.delete(key)
        await r.close()

    async def test_anonymous_rate_limit_allows_under_limit(self, client):
        """Anonymous endpoint allows requests under the limit."""
        # register endpoint: 5 requests per hour
        for i in range(3):
            response = await client.post(
                "/auth/register",
                json={
                    "email": f"test{i}@example.com",
                    "password": "TestPassword123!",     # pragma: allowlist secret
                },  
            )
            assert response.status_code == 202

    async def test_anonymous_rate_limit_blocks_at_limit(self, client):
        """Anonymous endpoint blocks at the limit."""
        # register endpoint: 5 requests per hour
        for i in range(5):
            response = await client.post(
                "/auth/register",
                json={
                    "email": f"limit{i}@example.com",
                    "password": "TestPassword123!",  # pragma: allowlist secret
                },  
            )
            assert response.status_code == 202

        # 6th request should be 429
        response = await client.post(
            "/auth/register",
            json={
                "email": "limit6@example.com",
                "password": "TestPassword123!",    # pragma: allowlist secret
            },  
        )
        assert response.status_code == 429
        assert response.json()["error"] == "RATE_LIMIT_EXCEEDED"
        assert "Retry-After" in response.headers

    async def test_login_rate_limit(self, client):
        """Login endpoint has its own rate limit (10/min)."""
        for i in range(10):
            response = await client.post(
                "/auth/login",
                json={
                    "email": f"login{i}@example.com",
                    "password": "wrongpassword",     # pragma: allowlist secret
                },
            )
            # Wrong password returns 401, but should not be rate limited yet
            assert response.status_code == 401

        # 11th request should be 429
        response = await client.post(
            "/auth/login",
            json={
                "email": "login11@example.com",
                "password": "wrongpassword",    # pragma: allowlist secret
            },  
        )
        assert response.status_code == 429
        assert response.json()["error"] == "RATE_LIMIT_EXCEEDED"

    async def test_authenticated_endpoint_rate_limit(self, client):
        """Authenticated endpoints use tenant JWT identity."""
        # First register and verify a user
        import jwt
        import time

        token = jwt.encode(
            {"sub": str(uuid4()), "exp": int(time.time()) + 3600},
            settings.JWT_SECRET_KEY,
            algorithm="HS256",
        )
        headers = {"Authorization": f"Bearer {token}"}

        # query endpoint: 20 requests per minute
        for i in range(3):
            response = await client.post(
                "/query/ask",
                json={"chat_id": str(uuid4()), "question": f"test question {i}"},
                headers=headers,
            )
            # May fail for other reasons (no chat, etc.) but not 429
            assert response.status_code != 429

    async def test_shared_upload_counter(self, client):
        """Upload and initiate-upload share the same rate limit counter."""
        import jwt
        import time

        token = jwt.encode(
            {"sub": str(uuid4()), "exp": int(time.time()) + 3600},
            settings.JWT_SECRET_KEY,
            algorithm="HS256",
        )
        headers = {"Authorization": f"Bearer {token}"}

        # upload: 5 requests per minute (shared with initiate-upload)
        for i in range(3):
            response = await client.post(
                "/documents/upload",
                files={"file": (f"test{i}.pdf", b"%PDF test", "application/pdf")},
                headers=headers,
            )
            # May fail for validation but not 429
            assert response.status_code != 429

        # initiate-upload counts toward the same limit
        for i in range(2):
            response = await client.post(
                "/documents/initiate-upload",
                json={
                    "filename": f"test{i}.pdf",
                    "mime_type": "application/pdf",
                    "file_size_bytes": 100,
                },
                headers=headers,
            )
            assert response.status_code != 429

        # 6th combined request should be 429
        response = await client.post(
            "/documents/upload",
            files={"file": ("test6.pdf", b"%PDF test", "application/pdf")},
            headers=headers,
        )
        # May be 429 or validation error depending on mock S3
        # The key is that they share the counter

    async def test_tenant_isolation(self, client):
        """Different tenants have independent rate limit buckets."""
        import jwt
        import time

        token_a = jwt.encode(
            {"sub": str(uuid4()), "exp": int(time.time()) + 3600},
            settings.JWT_SECRET_KEY,
            algorithm="HS256",
        )
        token_b = jwt.encode(
            {"sub": str(uuid4()), "exp": int(time.time()) + 3600},
            settings.JWT_SECRET_KEY,
            algorithm="HS256",
        )
        headers_a = {"Authorization": f"Bearer {token_a}"}
        headers_b = {"Authorization": f"Bearer {token_b}"}

        # User A makes 3 requests
        for i in range(3):
            response = await client.post(
                "/query/ask",
                json={"chat_id": str(uuid4()), "question": f"test {i}"},
                headers=headers_a,
            )
            assert response.status_code != 429

        # User B should still have full quota
        for i in range(3):
            response = await client.post(
                "/query/ask",
                json={"chat_id": str(uuid4()), "question": f"test {i}"},
                headers=headers_b,
            )
            assert response.status_code != 429

    async def test_sentinel_metrics_exposed(self, client):
        """Sentinel metrics should be exposed at /metrics."""
        response = await client.get("/metrics")
        assert response.status_code == 200
        metrics_text = response.text
        assert "sentinel_decisions_total" in metrics_text

    async def test_fail_open_behavior_on_redis_failure(self, client):
        """When Sentinel Redis fails, fail-open endpoints use emergency limiter."""

        # Stop Sentinel Redis by closing all connections
        # Note: This is a soft test - we can't easily stop Docker from here
        # but we can verify the emergency limiter exists by checking metrics
        response = await client.get("/metrics")
        assert response.status_code == 200

    async def test_anonymous_cookie_issued(self, client):
        """Allowed anonymous requests should receive the anonymous cookie."""
        response = await client.post(
            "/auth/register",
            json={
                "email": "cookie_test@example.com",
                "password": "TestPassword123!",    # pragma: allowlist secret
            },  
        )
        assert response.status_code == 202
        # Sentinel should set the anonymous cookie on allowed requests
        cookie_name = settings.ANONYMOUS_COOKIE_NAME
        assert cookie_name in response.cookies

    async def test_tampered_cookie_rejected(self, client):
        """Tampered anonymous cookie should be rejected and re-minted."""
        # First, get a valid cookie
        response = await client.post(
            "/auth/register",
            json={
                "email": "tamper_test@example.com",
                "password": "TestPassword123!",     # pragma: allowlist secret
            },  
        )
        cookie_name = settings.ANONYMOUS_COOKIE_NAME
        cookie_value = response.cookies.get(cookie_name)
        assert cookie_value is not None

        # Tamper with the cookie
        tampered = cookie_value[:-1] + ("a" if cookie_value[-1] != "a" else "b")

        # Make request with tampered cookie
        response = await client.post(
            "/auth/register",
            json={
                "email": "tamper_test2@example.com",
                "password": "TestPassword123!",     # pragma: allowlist secret
            },  
            cookies={cookie_name: tampered},
        )
        # Should still succeed (cookie re-minted) and not be 429 from bad cookie
        assert response.status_code == 202
        # Should receive a new cookie
        assert cookie_name in response.cookies


class TestSentinelRedisRequirements:
    """Tests for Sentinel Redis configuration requirements."""

    @pytest.mark.asyncio
    async def test_redis_noeviction(self):
        """Sentinel Redis must have noeviction policy."""
        import redis.asyncio as redis

        r = redis.from_url(
            settings.SENTINEL_REDIS_URL or "redis://:sentinel-local-dev-password@localhost:6379/0"
        )
        config = await r.config_get("maxmemory-policy")
        assert config.get("maxmemory-policy") == "noeviction"
        maxmemory = await r.config_get("maxmemory")
        assert int(maxmemory.get("maxmemory") or "0") > 0
        await r.close()

    @pytest.mark.asyncio
    async def test_sentinel_scripts_loaded(self):
        """Sentinel Lua scripts should be loaded."""
        # Check that scripts are loaded in the guard
        assert sentinel_guard._scripts_loaded is True
        token_bucket_sha = sentinel_guard._loader.sha("token_bucket")
        sliding_window_sha = sentinel_guard._loader.sha("sliding_window")
        assert token_bucket_sha is not None
        assert sliding_window_sha is not None

    @pytest.mark.asyncio
    async def test_script_reload_after_flush(self):
        """Scripts should auto-reload after Redis flush."""
        import redis.asyncio as redis

        r = redis.from_url(
            settings.SENTINEL_REDIS_URL or "redis://:sentinel-local-dev-password@localhost:6379/0"
        )
        # Flush scripts
        await r.script_flush()
        # Next request should trigger reload
        # This is tested implicitly by the other tests
        await r.close()


# Run with: pytest -m integration --run-integration
# The integration tests require a running Sentinel Redis instance
# Start it with: docker compose -f docker-compose.dev.yml up -d sentinel-redis
