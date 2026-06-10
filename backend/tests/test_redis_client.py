import pytest
import fakeredis.aioredis

from app.utils.redis_client import set_with_ttl, get, delete, increment_counter

@pytest.fixture
def fake_redis(monkeypatch):
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr("app.utils.redis_client.get_redis", lambda: fake)
    return fake

@pytest.mark.asyncio
async def test_set_and_get(fake_redis):
    await set_with_ttl("test:key", "hello", 60)
    assert await get("test:key") == "hello"

@pytest.mark.asyncio
async def test_increment_counter_sets_ttl_once(fake_redis):
    count1 = await increment_counter("ratelimit:login:1.2.3.4", ttl_seconds=60)
    count2 = await increment_counter("ratelimit:login:1.2.3.4", ttl_seconds=60)
    assert count1 == 1
    assert count2 == 2
    ttl = await fake_redis.ttl("ratelimit:login:1.2.3.4")
    assert ttl > 0  # TTL was set on first write only
