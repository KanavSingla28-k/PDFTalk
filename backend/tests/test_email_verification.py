"""
Unit + endpoint tests for services/email_verification.py.

What's tested:
  - Token generation produces a raw token and stores a hash (not the raw token).
  - `verify_token` succeeds for a valid, unexpired token.
  - `verify_token` raises ValueError for an unknown token.
  - `verify_token` raises ValueError for an expired token.
  - Tokens are one-time-use: second call to verify_token raises ValueError.
  - Old tokens are deleted when a new one is generated for the same user.
  - `purge_expired_tokens` deletes only expired rows.
  - `send_verification_email_for_user` enqueues a job on the RQ default queue
    with the correct to_email and a verification URL (not the raw user_id).
  - If the RQ queue raises, the exception propagates (coverage for queue-down path).

Email sending is fully mocked — no real Resend calls, no real Redis.
DB uses an in-memory SQLite via SQLAlchemy (swap for async Postgres in CI).

NOTE ON PATCHING:
  email_verification.send_verification_email_for_user() does NOT call a
  local `send_verification_email` helper.  It calls:
      default_queue.enqueue("app.utils.email.send_verification_email_sync", ...)
  Therefore all mocks target `app.services.email_verification.default_queue`,
  which is the object actually used at the call site.
"""

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.auth import EmailVerification
from app.services.email_verification import (
    generate_and_store_verification_token,
    purge_expired_tokens,
    send_verification_email_for_user,
    verify_token,
)

# ── Test DB setup (in-memory SQLite) ─────────────────────────────────────────

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def db() -> AsyncSession:
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


USER_ID = str(uuid.uuid4())
EMAIL = "test@example.com"


# ── Tests: generate_and_store_verification_token ──────────────────────────────


@pytest.mark.asyncio
async def test_generate_returns_raw_token(db):
    raw = await generate_and_store_verification_token(USER_ID, db)
    assert isinstance(raw, str)
    assert len(raw) > 20  # token_urlsafe(32) → ~43 chars


@pytest.mark.asyncio
async def test_stored_hash_is_not_raw_token(db):
    """The DB must store SHA-256(raw_token), never the raw token itself."""
    raw = await generate_and_store_verification_token(USER_ID, db)
    await db.commit()

    from sqlalchemy import select
    result = await db.execute(select(EmailVerification))
    record = result.scalar_one()

    assert record.token_hash != raw
    assert record.token_hash == _sha256(raw)


@pytest.mark.asyncio
async def test_old_token_replaced_on_regenerate(db):
    """Only one active token per user at a time."""
    await generate_and_store_verification_token(USER_ID, db)
    await db.commit()

    await generate_and_store_verification_token(USER_ID, db)
    await db.commit()

    from sqlalchemy import func, select
    import uuid as _uuid
    result = await db.execute(
        select(func.count()).select_from(EmailVerification)
        .where(EmailVerification.user_id == _uuid.UUID(USER_ID))
    )
    assert result.scalar() == 1


# ── Tests: verify_token ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_verify_valid_token(db):
    raw = await generate_and_store_verification_token(USER_ID, db)
    await db.commit()

    returned_user_id = await verify_token(raw, db)
    assert returned_user_id == USER_ID


@pytest.mark.asyncio
async def test_verify_consumes_token(db):
    """Token must be one-time-use: second call raises ValueError."""
    raw = await generate_and_store_verification_token(USER_ID, db)
    await db.commit()

    await verify_token(raw, db)
    await db.commit()

    with pytest.raises(ValueError, match="Invalid"):
        await verify_token(raw, db)


@pytest.mark.asyncio
async def test_verify_unknown_token_raises(db):
    with pytest.raises(ValueError, match="Invalid"):
        await verify_token("completely-unknown-token", db)


@pytest.mark.asyncio
async def test_verify_expired_token_raises(db):
    raw = await generate_and_store_verification_token(USER_ID, db)
    await db.commit()

    # Manually back-date the token so it's expired.
    from sqlalchemy import update
    import uuid as _uuid
    await db.execute(
        update(EmailVerification)
        .where(EmailVerification.user_id == _uuid.UUID(USER_ID))
        .values(expires_at=datetime.now(timezone.utc) - timedelta(hours=1))
    )
    await db.commit()

    with pytest.raises(ValueError, match="Invalid or expired"):
        await verify_token(raw, db)


# ── Tests: send_verification_email_for_user ───────────────────────────────────
#
# IMPORTANT: email_verification.py calls `default_queue.enqueue(...)`, NOT a
# local `send_verification_email` function.  We therefore patch
# `app.services.email_verification.default_queue` — the queue object that is
# imported at module level and used at the call site.


@pytest.mark.asyncio
async def test_send_enqueues_job_on_default_queue(db):
    """Happy path: a job is placed on the RQ default queue with correct args."""
    fake_queue = MagicMock()

    with patch("app.services.email_verification.default_queue", fake_queue):
        await send_verification_email_for_user(USER_ID, EMAIL, db)
        await db.commit()

    # The queue must have been called exactly once.
    fake_queue.enqueue.assert_called_once()

    pos_args, kw_args = fake_queue.enqueue.call_args

    from app.utils.email import send_verification_email_sync
    # First positional arg is the worker function object.
    assert pos_args[0] == send_verification_email_sync

    # kwargs must carry to_email and a verification_url containing the token.
    job_kwargs = kw_args.get("kwargs", {})
    assert job_kwargs["to_email"] == EMAIL
    assert "verify-email?token=" in job_kwargs["verification_url"]
    # The raw user_id must NOT appear in the URL — it should be the token.
    assert USER_ID not in job_kwargs["verification_url"]


@pytest.mark.asyncio
async def test_send_stores_token_hash_in_db(db):
    """Token row must be persisted in the DB when the job is enqueued."""
    fake_queue = MagicMock()

    with patch("app.services.email_verification.default_queue", fake_queue):
        await send_verification_email_for_user(USER_ID, EMAIL, db)
        await db.commit()

    from sqlalchemy import select
    import uuid as _uuid
    result = await db.execute(
        select(EmailVerification)
        .where(EmailVerification.user_id == _uuid.UUID(USER_ID))
    )
    record = result.scalar_one()
    assert record is not None
    assert record.token_hash  # non-empty hash stored


@pytest.mark.asyncio
async def test_send_queue_failure_propagates(db):
    """
    If the RQ queue raises (e.g. Redis is down), the exception must propagate
    so the caller (registration endpoint) can handle it — not silently dropped.
    """
    fake_queue = MagicMock()
    fake_queue.enqueue.side_effect = ConnectionError("Redis is down")

    with patch("app.services.email_verification.default_queue", fake_queue):
        with pytest.raises(ConnectionError, match="Redis is down"):
            await send_verification_email_for_user(USER_ID, EMAIL, db)


@pytest.mark.asyncio
async def test_send_does_not_commit(db):
    """
    send_verification_email_for_user must NOT commit — that's the caller's job.
    We verify the token row is only flushed (visible in the same session) but
    the caller can still roll back if needed.
    """
    fake_queue = MagicMock()

    with patch("app.services.email_verification.default_queue", fake_queue):
        await send_verification_email_for_user(USER_ID, EMAIL, db)
        # Do NOT commit here — simulate caller aborting after enqueue.
        await db.rollback()

    # After rollback, no token row should exist.
    from sqlalchemy import select
    import uuid as _uuid
    result = await db.execute(
        select(EmailVerification)
        .where(EmailVerification.user_id == _uuid.UUID(USER_ID))
    )
    assert result.scalar_one_or_none() is None


# ── Tests: purge_expired_tokens ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_purge_removes_only_expired(db):
    now = datetime.now(timezone.utc)

    # Insert one valid and one expired token.
    db.add(EmailVerification(
        user_id=uuid.uuid4(),
        token_hash=_sha256("valid-token"),
        expires_at=now + timedelta(hours=12),
    ))
    db.add(EmailVerification(
        user_id=uuid.uuid4(),
        token_hash=_sha256("expired-token"),
        expires_at=now - timedelta(hours=1),
    ))
    await db.commit()

    deleted = await purge_expired_tokens(db)
    await db.commit()

    assert deleted == 1

    from sqlalchemy import select
    result = await db.execute(select(EmailVerification))
    remaining = result.scalars().all()
    assert len(remaining) == 1
    assert remaining[0].token_hash == _sha256("valid-token")



# ── T-19: Endpoint redirect shape tests ───────────────────────────────────────
#
# These tests exercise the GET /auth/verify-email route via httpx AsyncClient.
# They check only the redirect URL shape — DB state is covered by the service
# tests above.


@pytest.mark.asyncio
async def test_endpoint_valid_token_redirects_to_login(async_client, db):
    raw = await generate_and_store_verification_token(USER_ID, db)
    await db.commit()

    response = await async_client.get(
        f"/auth/verify-email?token={raw}",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"].endswith("/login?verified=true")


@pytest.mark.asyncio
async def test_endpoint_invalid_token_redirects_with_error_slug(async_client):
    response = await async_client.get(
        "/auth/verify-email?token=totallyfaketoken",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert "error=invalid_token" in response.headers["location"]


@pytest.mark.asyncio
async def test_endpoint_expired_token_redirects_with_error_slug(async_client, db):
    import uuid as _uuid
    raw = await generate_and_store_verification_token(USER_ID, db)
    await db.commit()

    # Back-date the token.
    from sqlalchemy import update
    await db.execute(
        update(EmailVerification)
        .where(EmailVerification.user_id == _uuid.UUID(USER_ID))
        .values(expires_at=datetime.now(timezone.utc) - timedelta(hours=1))
    )
    await db.commit()

    response = await async_client.get(
        f"/auth/verify-email?token={raw}",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert "error=token_expired" in response.headers["location"]


@pytest.mark.asyncio
async def test_endpoint_missing_token_param_returns_422(async_client):
    """FastAPI rejects the request before it reaches our handler."""
    response = await async_client.get("/auth/verify-email")
    assert response.status_code == 422
