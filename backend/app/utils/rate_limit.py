"""
Sliding-window rate limiter — FastAPI dependency.

Usage
-----
Instantiate with a limit and window, then include as a dependency on any route:

    from app.utils.rate_limit import RateLimiter

    login_limiter = RateLimiter(limit=10, window_seconds=60, key_prefix="login")

    @router.post("/login")
    async def login(
        request: Request,
        _: None = Depends(login_limiter),
        ...
    ):
        ...

Algorithm — Redis sliding window
---------------------------------
For each (key_prefix, identifier) pair:

  1. Compute the start of the current window:
       window_start = now_ms - window_ms
  2. Remove all entries older than the window:
       ZREMRANGEBYSCORE key 0 window_start
  3. Count remaining entries:
       ZCARD key
  4. If count >= limit → 429, else add current timestamp:
       ZADD key now_ms now_ms
  5. Reset TTL to the window length so the key auto-expires:
       EXPIRE key window_seconds

This is O(log N) per request and naturally handles bursty traffic without
the "reset spike" problem of fixed windows (where everyone retries the
moment the window resets).

Key format
----------
  ratelimit:{prefix}:{identifier}

  prefix      — e.g. "login", "register", "upload"
  identifier  — IP address (for auth endpoints) or user_id (for data endpoints)

The caller chooses which identifier to pass; this class is agnostic.

Returning 429
-------------
The response includes a Retry-After header (seconds until the oldest request
falls out of the window) so well-behaved clients know when to retry.
"""

import time
import structlog
from typing import Callable
import uuid
from fastapi import Request, HTTPException
from redis.exceptions import RedisError

from app.exceptions import RateLimitExceededError
from app.utils.redis_client import get_redis

logger = structlog.get_logger(__name__)


class RateLimiter:
    """
    Reusable FastAPI dependency that enforces a sliding-window rate limit.

    Parameters
    ----------
    limit : int
        Maximum number of requests allowed within the window.
    window_seconds : int
        Length of the sliding window in seconds.
    key_prefix : str
        Namespace prefix for the Redis key (e.g. "login", "register").
        Prevents collisions between different limiters sharing the same
        identifier (e.g. the same IP hitting both /login and /register).
    identifier_fn : Callable[[Request], str] | None
        How to derive the rate-limit identifier from the request.
        Defaults to the client's IP address. Pass a custom function to
        rate-limit by user ID instead (for authenticated endpoints).

    Example
    -------
    # Per-IP limit for unauthenticated routes:
    login_limiter = RateLimiter(limit=10, window_seconds=60, key_prefix="login")

    # Per-user limit for authenticated routes:
    upload_limiter = RateLimiter(
        limit=5,
        window_seconds=60,
        key_prefix="upload",
        identifier_fn=user_id_from_request,
    )
    """

    def __init__(
        self,
        limit: int,
        window_seconds: int,
        key_prefix: str,
        identifier_fn: Callable[[Request], str] | None = None,
        fail_open: bool = False,
    ) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self.key_prefix = key_prefix
        self._identifier_fn = identifier_fn or self._default_identifier
        self.fail_open = fail_open

    # ------------------------------------------------------------------
    # FastAPI dependency — called on every request to a guarded route
    # ------------------------------------------------------------------

    async def __call__(self, request: Request) -> None:
        """
        Check the rate limit. Raises RateLimitExceededError (HTTP 429) if exceeded.

        FastAPI calls this automatically when the limiter is used as a
        Depends(). The return value is None — it's a guard, not a provider.
        """
        identifier = self._identifier_fn(request)
        redis = get_redis()

        redis_key = f"ratelimit:{self.key_prefix}:{identifier}"
        now_ms = int(time.time() * 1000)
        window_start_ms = now_ms - (self.window_seconds * 1000)

        try:
            # Phase 1: remove expired entries + count current window atomically.
            # ZADD is intentionally NOT in this pipeline — we only add the
            # request timestamp if the count is within the limit (below).
            async with redis.pipeline(transaction=True) as pipe:
                pipe.zremrangebyscore(redis_key, 0, window_start_ms)
                pipe.zcard(redis_key)
                pipe.zrange(redis_key, 0, 0, withscores=True)
                results = await pipe.execute()

            current_count: int = results[1]  # zcard result (after stale removal)
            oldest_score_result = results[2]

            if current_count >= self.limit:
                # Request rejected — do NOT add to the sorted set.
                # Calculate seconds until the oldest entry falls out of the window.
                if oldest_score_result:
                    oldest_ms = int(oldest_score_result[0][1])
                    retry_after = max(
                        1,
                        int((oldest_ms + self.window_seconds * 1000 - now_ms) / 1000),
                    )
                else:
                    retry_after = self.window_seconds

                logger.warning(
                    "rate_limit.exceeded",
                    key_prefix=self.key_prefix,
                    identifier=identifier,
                    limit=self.limit,
                    window_seconds=self.window_seconds,
                )

                raise RateLimitExceededError(retry_after)

            # Phase 2: request is allowed — record it and refresh the TTL.
            async with redis.pipeline(transaction=True) as pipe:
                pipe.zadd(redis_key, {uuid.uuid4().hex: now_ms})
                pipe.expire(redis_key, self.window_seconds)
                await pipe.execute()
        except RedisError as exc:
            logger.error("rate_limiter.redis_error", error=str(exc))
            if self.fail_open:
                return
            raise HTTPException(status_code=503, detail="Service Unavailable")

    # ------------------------------------------------------------------
    # Identifier helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _default_identifier(request: Request) -> str:
        """
        Extract the client IP from the request.

        Prefers X-Real-IP (forcefully set by Nginx) to prevent IP spoofing.
        Falls back to X-Forwarded-For, then the direct client IP.
        """
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip.strip()

        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            # If multiple proxies exist, the closest client to Nginx is appended last.
            # However, since X-Real-IP is preferred, this is merely a fallback.
            return forwarded_for.split(",")[0].strip()

        return request.client.host if request.client else "unknown"


# ------------------------------------------------------------------
# Identifier function for authenticated (user-scoped) rate limits
# ------------------------------------------------------------------

def user_id_from_request(request: Request) -> str:
    """
    Extract the user_id from a Bearer access token in the Authorization header.

    Used as `identifier_fn` for rate limiters on authenticated endpoints
    (upload, query) so the limit is per-user rather than per-IP. This
    prevents a user on a shared IP (e.g. office NAT) from being penalised
    for another user's traffic — and prevents a single user from evading
    the limit by rotating IPs.

    Decodes the token without hitting the database — the JWT is self-contained.
    Raises TokenInvalidError / TokenExpiredError (both map to HTTP 401 via the
    global exception handler) if the token is absent or malformed. In practice
    this path is only reached after get_current_user already validated the token,
    so a failure here means the token became invalid between the two calls —
    an edge case that correctly results in a 401, not a 429.
    """
    from app.auth.tokens import decode_access_token  # local import to avoid circular

    auth_header = request.headers.get("Authorization", "")
    token = auth_header.removeprefix("Bearer ").strip()
    # decode_access_token raises TokenInvalidError/TokenExpiredError on failure;
    # both are caught by the global exception handler and returned as 401.
    return decode_access_token(token)
