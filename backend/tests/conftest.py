"""
Sets all required environment variables before any app module is imported.
This prevents Settings() from failing on missing fields during test collection.

These are dummy values — no real services are contacted in unit tests.
"""

import os
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.session import get_db
from app.main import app


# Set vars before any app import touches pydantic-settings
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://pdftalk:test@localhost/pdftalk_test")
os.environ.setdefault("REDIS_URL", "redis://:test@localhost:6379")

os.environ.setdefault("JWT_SECRET", "00000000000000000000000000000000000000000000000000000000000000ff")

os.environ.setdefault("RESEND_API_KEY", "re_test_000000000000000000000000000000000000")

os.environ.setdefault("OPENAI_API_KEY", "sk-test-000000000000000000000000000000000000000000000000")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "AKIAIOSFODNN7EXAMPLE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY")
os.environ.setdefault("S3_BUCKET_NAME", "pdftalk-test-bucket")

os.environ.setdefault("APP_URL", "http://localhost")


TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

import fakeredis.aioredis

@pytest.fixture(autouse=True)
def mock_redis(monkeypatch):
    fake_redis = fakeredis.aioredis.FakeRedis()

    def fake_get_redis():
        return fake_redis

    monkeypatch.setattr(
        "app.auth.rate_limit.get_redis",
        fake_get_redis,
    )

@pytest_asyncio.fixture(autouse=True)
def mock_email(monkeypatch):
    async def fake_send_email(*args, **kwargs):
        pass
    monkeypatch.setattr("app.services.email_verification.send_verification_email", fake_send_email)
    monkeypatch.setattr("app.utils.email.send_verification_email", fake_send_email)


# ---------------------------------------------------------------------------
# Shared async engine + session factory
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def db() -> AsyncSession:
    """
    In-memory SQLite session. Each test gets a fresh schema.
    Automatically rolled back / dropped after the test.
    """
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


# ---------------------------------------------------------------------------
# HTTP client with DB override
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def async_client(db: AsyncSession) -> AsyncClient:
    """
    httpx AsyncClient pointed at the FastAPI app.

    Overrides the `get_db` dependency so every request the client makes
    hits the same in-memory SQLite session as the test itself — no separate
    DB connection, no transaction isolation surprises.
    """

    async def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client

    # Clean up the override after the test so it doesn't bleed into others.
    app.dependency_overrides.pop(get_db, None)
