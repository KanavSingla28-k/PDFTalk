"""
Sets all required environment variables before any app module is imported.
This prevents Settings() from failing on missing fields during test collection.

These are dummy values — no real services are contacted in unit tests.

IMPORTANT: os.environ.setdefault() calls MUST appear before any app import,
because Settings() is instantiated at module-level in config.py the moment
any app module is imported.
"""

import os
import uuid
import pytest
import pytest_asyncio
import tempfile
import shutil
import atexit
import fakeredis.aioredis
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.session import get_db
from app.main import app

# ---------------------------------------------------------------------------
# Environment setup — MUST be first, before any app.* import
# ---------------------------------------------------------------------------
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://pdftalk:test@localhost/pdftalk_test")
os.environ.setdefault("REDIS_URL", "redis://:test@localhost:6379")

os.environ.setdefault("JWT_SECRET_KEY", "00000000000000000000000000000000000000000000000000000000000000ff")

os.environ.setdefault("RESEND_API_KEY", "re_test_000000000000000000000000000000000000")
os.environ.setdefault("FROM_EMAIL", "noreply@test.example.com")

os.environ.setdefault("OPENAI_API_KEY", "sk-test-000000000000000000000000000000000000000000000000")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "AKIAIOSFODNN7EXAMPLE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY")
os.environ.setdefault("S3_BUCKET_NAME", "pdftalk-test-bucket")

os.environ.setdefault("APP_URL", "http://localhost")
_temp_dir = tempfile.mkdtemp(prefix="pdftalk_prometheus_")
os.environ["PROMETHEUS_MULTIPROC_DIR"] = _temp_dir
atexit.register(lambda: shutil.rmtree(_temp_dir, ignore_errors=True))

# ---------------------------------------------------------------------------
# App imports — safe after env vars are in place
# ---------------------------------------------------------------------------


TEST_DB_URL = "sqlite+aiosqlite:///:memory:"



@pytest.fixture(autouse=True)
def mock_redis(monkeypatch):
    fake_redis = fakeredis.aioredis.FakeRedis()

    def fake_get_redis():
        return fake_redis

    monkeypatch.setattr(
        "app.utils.rate_limit.get_redis",
        fake_get_redis,
    )

@pytest.fixture(autouse=True)
def mock_email(monkeypatch):
    """Prevent any real RQ enqueue calls during tests.

    The email_verification service calls ``default_queue.enqueue(...)`` directly
    (not a local send_verification_email function), so we patch the queue object
    itself.  We also patch the sync email helper used inside RQ workers so that
    any test which invokes it directly doesn't hit Resend.
    """
    from unittest.mock import MagicMock
    fake_queue = MagicMock()
    monkeypatch.setattr("app.services.email_verification.default_queue", fake_queue)
    monkeypatch.setattr("app.workers.queues.default_queue", fake_queue)
    # Also stub the sync worker-side helper so tests that call it don't hit Resend.
    monkeypatch.setattr("app.utils.email.send_verification_email_sync", MagicMock())


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


# ---------------------------------------------------------------------------
# Auth fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def verified_user(db: AsyncSession):
    """
    Insert a verified, active User row and return the ORM object.

    Imports are deferred so model registration order doesn't bite us
    during collection — the DB schema is created before this runs.
    """
    from app.auth.password import hash_password
    from app.models.user import User  # adjust path if your User lives elsewhere

    user = User(
        id=uuid.uuid4(),
        email="testuser@example.com",
        email_lower="testuser@example.com",
        password_hash=hash_password("TestPassword1"),
        is_verified=True,
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@pytest_asyncio.fixture
async def auth_headers(verified_user) -> dict:
    """
    Return an Authorization header dict carrying a valid access token
    for the verified_user fixture.

    Uses create_access_token directly — no HTTP round-trip needed,
    and avoids coupling these fixtures to the login endpoint.
    """
    from app.auth.tokens import create_access_token  # adjust path if needed

    token = create_access_token(user_id=str(verified_user.id))
    return {"Authorization": f"Bearer {token}"}
