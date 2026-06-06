import redis
from rq import Queue
from app.core.config import settings

# Synchronous Redis connection — RQ does not support redis.asyncio
_redis_conn = redis.Redis.from_url(settings.REDIS_URL, decode_responses=False)

ingest_queue = Queue("ingest", connection=_redis_conn)