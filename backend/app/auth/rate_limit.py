"""
Sliding-window rate limiter — FastAPI dependency.

Usage
-----
Instantiate with a limit and window, then include as a dependency on any route:

    from app.auth.rate_limit import RateLimiter

    login_limiter = RateLimiter(limit=10, window_seconds=60)

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
import logging
from typing import Callable

from fastapi import Depends, Request, status

from app.exceptions import RateLimitExceededError
from app.utils.redis_client import get_redis

logger = logging.getLogger(__name__)


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

    # Per-user limit for authenticated routes (user_id injected by caller):
    upload_limiter = RateLimiter(
        limit=5,
        window_seconds=60,
        key_prefix="upload",
        identifier_fn=lambda req: req.state.user_id,  # set by auth middleware
    )
    """

    def __init__(
        self,
        limit: int,
        window_seconds: int,
        key_prefix: str,
        identifier_fn: Callable[[Request], str] | None = None,
    ) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self.key_prefix = key_prefix
        self._identifier_fn = identifier_fn or self._default_identifier

    # ------------------------------------------------------------------
    # FastAPI dependency — called on every request to a guarded route
    # ------------------------------------------------------------------

    async def __call__(self, request: Request) -> None:
        """
        Check the rate limit. Raises HTTP 429 if exceeded.

        FastAPI calls this automatically when the limiter is used as a
        Depends(). The return value is None — it's a guard, not a provider.
        """
        identifier = self._identifier_fn(request)
        redis = get_redis()

        redis_key = f"ratelimit:{self.key_prefix}:{identifier}"
        now_ms = int(time.time() * 1000)
        window_start_ms = now_ms - (self.window_seconds * 1000)

        # Sliding window pipeline — atomic via pipeline(transaction=True)
        async with redis.pipeline(transaction=True) as pipe:
            # 1. Remove timestamps older than the current window
            pipe.zremrangebyscore(redis_key, 0, window_start_ms)
            # 2. Count remaining entries in the window
            pipe.zcard(redis_key)
            # 3. Add current timestamp (score = member = now_ms for uniqueness)
            pipe.zadd(redis_key, {str(now_ms): now_ms})
            # 4. Refresh TTL so the key doesn't linger after activity stops
            pipe.expire(redis_key, self.window_seconds)
            results = await pipe.execute()

        current_count: int = results[1]  # zcard result (before the new entry)

        if current_count >= self.limit:
            # Calculate seconds until the oldest entry falls out of the window.
            # This is the minimum time the client must wait before retrying.
            oldest_score_result = await redis.zrange(redis_key, 0, 0, withscores=True)
            if oldest_score_result:
                oldest_ms = int(oldest_score_result[0][1])
                retry_after = max(
                    1,
                    int((oldest_ms + self.window_seconds * 1000 - now_ms) / 1000),
                )
            else:
                retry_after = self.window_seconds

            logger.warning(
                "Rate limit exceeded",
                extra={
                    "key_prefix": self.key_prefix,
                    "identifier": identifier,
                    "limit": self.limit,
                    "window_seconds": self.window_seconds,
                },
            )

            raise RateLimitExceededError(retry_after)

    # ------------------------------------------------------------------
    # Identifier helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _default_identifier(request: Request) -> str:
        """
        Extract the client IP from the request.

        Prefers X-Forwarded-For (set by Nginx) over the direct client IP,
        since the API sits behind an Nginx reverse proxy in production.
        Takes only the first (leftmost) IP from the header to avoid spoofing
        via a crafted multi-value X-Forwarded-For header.
        """
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            # "1.2.3.4, 10.0.0.1" → "1.2.3.4"  (first = original client)
            return forwarded_for.split(",")[0].strip()
        return request.client.host if request.client else "unknown"