from datetime import date
from typing import cast
import redis.asyncio as aioredis
from app.core.config import settings
import redis as sync_redis_lib

import asyncio

# Dictionary mapping event loops to their connection pools
_pools: dict[asyncio.AbstractEventLoop, aioredis.ConnectionPool] = {}

def get_pool() -> aioredis.ConnectionPool:
    loop = asyncio.get_running_loop()
    if loop not in _pools:
        _pools[loop] = aioredis.ConnectionPool.from_url(
            settings.REDIS_URL,
            max_connections=20,
            decode_responses=True,
        )
    return _pools[loop]

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

def key_daily_token_stats() -> str:
    today = date.today().strftime("%Y%m%d")
    return f"admin:stats:tokens:{today}"

def key_daily_query_quota(user_id: str) -> str:
    today = date.today().strftime("%Y%m%d")
    return f"quota:queries:{user_id}:{today}"
    
def key_email_verify(token_hash: str) -> str:
    return f"emailverify:{token_hash}"

async def increment_counter_by(
    key: str, 
    amount: int, 
    ttl_seconds: int | None = None,
    stats_zset_key: str | None = None,
    stats_member: str | None = None
) -> int:
    """Like increment_counter but adds `amount` instead of 1. Used for token quota tracking.

    Uses a pipeline to guarantee that the TTL is set exactly once — on the true first
    write — regardless of what `amount` is. Optionally tracks values in a ZSET for admin stats.
    """
    r = get_redis()
    pipe = r.pipeline(transaction=True)
    pipe.incrby(key, amount)
    pipe.persist(key)  # no-op if key already has a TTL; prevents window from sliding
    
    if stats_zset_key and stats_member:
        pipe.zincrby(stats_zset_key, amount, stats_member)
        
    results = await pipe.execute()
    count: int = results[0]
    
    if count == amount:
        # Guaranteed first write — PERSIST returned 1 (no prior TTL).
        if ttl_seconds:
            await r.expire(key, ttl_seconds)
        if stats_zset_key:
            # 2 days TTL is enough for today's stats to be viewable tomorrow
            await r.expire(stats_zset_key, 172800)
            
    return count


# Circuit breaker key builders
def key_circuit_breaker_failures() -> str:
    return "cb:openai:failures"

def key_circuit_breaker_open_until() -> str:
    return "cb:openai:open_until"

def get_sync_redis() -> sync_redis_lib.Redis:
    """
    Synchronous Redis client for use in RQ worker contexts (e.g. FailedJobRegistry).
    Not suitable for use inside async request handlers — use get_redis() there.
    """
    return sync_redis_lib.Redis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
    )
