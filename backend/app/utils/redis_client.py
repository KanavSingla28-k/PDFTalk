import hashlib
from datetime import date
from typing import cast
import redis.asyncio as aioredis
from app.core.config import settings

# Single connection pool — shared across the app lifetime
_pool: aioredis.ConnectionPool | None = None


def get_pool() -> aioredis.ConnectionPool:
    global _pool
    if _pool is None:
        _pool = aioredis.ConnectionPool.from_url(
            settings.REDIS_URL,
            max_connections=20,
            decode_responses=True,
        )
    return _pool


def get_redis() -> aioredis.Redis:
    return aioredis.Redis(connection_pool=get_pool())

async def set_with_ttl(key: str, value: str, ttl_seconds: int) -> None:
    r = get_redis()
    await r.set(key, value, ex=ttl_seconds)


async def get(key: str) -> str | None:
    r = get_redis()
    return cast(str | None, await r.get(key))


async def delete(key: str) -> None:
    r = get_redis()
    await r.delete(key)


async def increment_counter(key: str, ttl_seconds: int | None = None) -> int:
    r = get_redis()
    count = await r.incr(key)
    if count == 1 and ttl_seconds:
        # Only set TTL on the first write — avoids resetting the window on every hit
        await r.expire(key, ttl_seconds)
    return count

# Key builders — central place for all Redis key patterns
def key_refresh_token(token_hash: str) -> str:
    return f"token:refresh:{token_hash}"

def key_rate_limit_login(ip: str) -> str:
    return f"ratelimit:login:{ip}"

def key_rate_limit_register(ip: str) -> str:
    return f"ratelimit:register:{ip}"

def key_account_lockout(user_id: str) -> str:
    return f"lockout:{user_id}"

def key_daily_token_quota(user_id: str) -> str:
    today = date.today().strftime("%Y%m%d")
    return f"quota:tokens:{user_id}:{today}"

def key_email_verify(token_hash: str) -> str:
    return f"emailverify:{token_hash}"

async def increment_counter_by(key: str, amount: int, ttl_seconds: int | None = None) -> int:
    """Like increment_counter but adds `amount` instead of 1. Used for token quota tracking."""
    r = get_redis()
    count = await r.incrby(key, amount)
    if count == amount and ttl_seconds:
        # First write — set TTL. Same logic as increment_counter.
        await r.expire(key, ttl_seconds)
    return count


# Circuit breaker key builders
def key_circuit_breaker_failures() -> str:
    return "cb:openai:failures"

def key_circuit_breaker_open_until() -> str:
    return "cb:openai:open_until"