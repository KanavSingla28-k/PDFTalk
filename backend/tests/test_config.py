import pytest
from pydantic import ValidationError
from app.core.config import Settings

def test_settings_jwt_secret_key_too_short():
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            DATABASE_URL="postgresql+asyncpg://pdftalk:test@localhost/pdftalk_test",  # pragma: allowlist secret
            REDIS_URL="redis://:test@localhost:6379",
            FROM_EMAIL="noreply@test.example.com",
            AWS_ACCESS_KEY_ID="AKIAIOSFODNN7EXAMPLE",  # pragma: allowlist secret
            AWS_SECRET_ACCESS_KEY="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",  # pragma: allowlist secret
            S3_BUCKET_NAME="pdftalk-test-bucket",  # pragma: allowlist secret
            APP_URL="http://localhost",
            PROMETHEUS_MULTIPROC_DIR="/tmp/prometheus_multiproc",
            JWT_SECRET_KEY="short-secret"  # pragma: allowlist secret
        )
    assert "JWT_SECRET_KEY" in str(exc_info.value)
    assert "JWT_SECRET_KEY must be at least 32 characters long" in str(exc_info.value)

def test_settings_jwt_secret_key_valid():
    settings = Settings(
        DATABASE_URL="postgresql+asyncpg://pdftalk:test@localhost/pdftalk_test",  # pragma: allowlist secret
        REDIS_URL="redis://:test@localhost:6379",
        FROM_EMAIL="noreply@test.example.com",
        AWS_ACCESS_KEY_ID="AKIAIOSFODNN7EXAMPLE",  # pragma: allowlist secret
        AWS_SECRET_ACCESS_KEY="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",  # pragma: allowlist secret
        S3_BUCKET_NAME="pdftalk-test-bucket",  # pragma: allowlist secret
        APP_URL="http://localhost",
        PROMETHEUS_MULTIPROC_DIR="/tmp/prometheus_multiproc",
        JWT_SECRET_KEY="a" * 32
    )
    assert settings.JWT_SECRET_KEY == "a" * 32

def test_settings_missing_prometheus_multiproc_dir(monkeypatch):
    # Ensure it's not loaded from the environment
    monkeypatch.delenv("PROMETHEUS_MULTIPROC_DIR", raising=False)
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            _env_file=None,
            DATABASE_URL="postgresql+asyncpg://pdftalk:test@localhost/pdftalk_test",  # pragma: allowlist secret
            REDIS_URL="redis://:test@localhost:6379",
            FROM_EMAIL="noreply@test.example.com",
            AWS_ACCESS_KEY_ID="AKIAIOSFODNN7EXAMPLE",  # pragma: allowlist secret
            AWS_SECRET_ACCESS_KEY="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",  # pragma: allowlist secret
            S3_BUCKET_NAME="pdftalk-test-bucket",  # pragma: allowlist secret
            APP_URL="http://localhost",
            JWT_SECRET_KEY="a" * 32
        )
    assert "PROMETHEUS_MULTIPROC_DIR" in str(exc_info.value)
    assert "Field required" in str(exc_info.value)
