import pytest
from app.core.config import settings
from app.core.sentinel import _build_sentinel_config

def test_sentinel_config_prefers_url_over_password(monkeypatch):
    monkeypatch.setattr(settings, "SENTINEL_REDIS_URL", "redis://:x@localhost:6380/0")
    monkeypatch.setattr(settings, "SENTINEL_REDIS_PASSWORD", "unused")
    config = _build_sentinel_config()
    assert config.app.redis_url == "redis://:x@localhost:6380/0"

def test_sentinel_config_falls_back_to_password(monkeypatch):
    monkeypatch.setattr(settings, "SENTINEL_REDIS_URL", None)
    monkeypatch.setattr(settings, "SENTINEL_REDIS_PASSWORD", "p@ss/word")
    config = _build_sentinel_config()
    # verify host and URL-encoded password
    assert "sentinel-redis:6379" in config.app.redis_url
    assert "p%40ss%2Fword" in config.app.redis_url

def test_sentinel_config_raises_when_neither_set(monkeypatch):
    monkeypatch.setattr(settings, "SENTINEL_REDIS_URL", None)
    monkeypatch.setattr(settings, "SENTINEL_REDIS_PASSWORD", None)
    with pytest.raises(ValueError, match="Either SENTINEL_REDIS_URL or SENTINEL_REDIS_PASSWORD must be configured"):
        _build_sentinel_config()
