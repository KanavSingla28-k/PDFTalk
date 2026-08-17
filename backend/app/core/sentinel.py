from urllib.parse import quote

from sentinel.config import AppConfig, SentinelConfig
from sentinel.http import SentinelGuard
from sentinel.models import AlgorithmType, FailMode, Policy
from sentinel.redis import ScriptLoader, SentinelRedis

from app.core.config import settings


ENDPOINT_ID = "pdftalk.documents.upload"


def _build_config() -> SentinelConfig:
    if not settings.SENTINEL_REDIS_PASSWORD:
        raise ValueError("SENTINEL_REDIS_PASSWORD must be configured")

    redis_password = quote(settings.SENTINEL_REDIS_PASSWORD, safe="")

    redis_url = f"redis://:{redis_password}@sentinel-redis:6379/0"

    return SentinelConfig(
        app=AppConfig(
            redis_url=redis_url,
            jwt_secret=settings.JWT_SECRET_KEY,
            jwt_algorithm_allowlist=frozenset({settings.JWT_ALGORITHM}),
        ),
        policies={
            ENDPOINT_ID: Policy(
                endpoint_id=ENDPOINT_ID,
                algorithm=AlgorithmType.SLIDING_WINDOW,
                fail_mode=FailMode.FAIL_CLOSED,
                fallback_rate_per_process_micro=1,
                policy_version=1,
                limit=3,
                window_size_micro=60_000_000,
            )
        },
    )


config = _build_config()
redis = SentinelRedis(config.app.redis_url)
loader = ScriptLoader(redis.client)
guard = SentinelGuard(config, redis, loader)
