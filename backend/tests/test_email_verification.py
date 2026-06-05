"""
Unit tests for services/email_verification.py.

What's tested:
  - Token generation produces a raw token and stores a hash (not the raw token).
  - `verify_token` succeeds for a valid, unexpired token.
  - `verify_token` raises ValueError for an unknown token.
  - `verify_token` raises ValueError for an expired token.
  - Tokens are one-time-use: second call to verify_token raises ValueError.
  - Old tokens are deleted when a new one is generated for the same user.
  - `purge_expired_tokens` deletes only expired rows.

Email sending is fully mocked — no real Resend calls.
DB uses an in-memory SQLite via SQLAlchemy (swap for async Postgres in CI).
"""

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

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
    raw = await generate_and_store_verification_token(USER_ID, db)
    await db.commit()

    from sqlalchemy import select
    result = await db.execute(select(EmailVerification))
    record = result.scalar_one()

    # The DB must store the hash, never the raw token.
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
    """Token must be one-time-use."""
    raw = await generate_and_store_verification_token(USER_ID, db)
    await db.commit()

    await verify_token(raw, db)
    await db.commit()

    with pytest.raises(ValueError, match="Invalid" or "Expired"):
        await verify_token(raw, db)


@pytest.mark.asyncio
async def test_verify_unknown_token_raises(db):
    with pytest.raises(ValueError, match="Invalid" or "Expired"):
        await verify_token("completely-unknown-token", db)


@pytest.mark.asyncio
async def test_verify_expired_token_raises(db):
    raw = await generate_and_store_verification_token(USER_ID, db)
    await db.commit()

    # Manually back-date the token so it's expired.
    from sqlalchemy import select, update
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


@pytest.mark.asyncio
@patch("app.services.email_verification.send_verification_email", new_callable=AsyncMock)
async def test_send_calls_email_util(mock_send, db):
    await send_verification_email_for_user(USER_ID, EMAIL, db)
    await db.commit()

    mock_send.assert_awaited_once()
    call_kwargs = mock_send.call_args
    assert call_kwargs.kwargs["to_email"] == EMAIL
    assert USER_ID not in call_kwargs.kwargs["verification_url"]  # raw token, not user_id
    assert "verify-email?token=" in call_kwargs.kwargs["verification_url"]


@pytest.mark.asyncio
@patch("app.services.email_verification.send_verification_email", new_callable=AsyncMock)
async def test_send_failure_propagates(mock_send, db):
    mock_send.side_effect = RuntimeError("Resend API down")
    with pytest.raises(RuntimeError, match="Resend API down"):
        await send_verification_email_for_user(USER_ID, EMAIL, db)


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


# ── T-19: Per-user expired-token sweep on verify ──────────────────────────────


@pytest.mark.asyncio
async def test_verify_sweeps_other_expired_tokens_for_same_user(db):
    """
    When a valid token is consumed, all other expired tokens for the same user
    are deleted as a side-effect (on-use cleanup, no cron needed).
    """
    import uuid as _uuid
    user_uuid = _uuid.UUID(USER_ID)
    now = datetime.now(timezone.utc)

    # Add two stale tokens for the same user alongside the valid one.
    stale_1 = EmailVerification(
        user_id=user_uuid,
        token_hash=_sha256("stale-token-1"),
        expires_at=now - timedelta(hours=2),
    )
    stale_2 = EmailVerification(
        user_id=user_uuid,
        token_hash=_sha256("stale-token-2"),
        expires_at=now - timedelta(hours=5),
    )
    db.add_all([stale_1, stale_2])
    await db.commit()

    # Now generate and immediately verify a fresh token.
    raw = await generate_and_store_verification_token(USER_ID, db)
    await db.commit()
    await verify_token(raw, db)
    await db.commit()

    # All three rows (2 stale + 1 consumed) must be gone.
    from sqlalchemy import select
    result = await db.execute(
        select(EmailVerification).where(EmailVerification.user_id == user_uuid)
    )
    assert result.scalars().all() == []


@pytest.mark.asyncio
async def test_sweep_does_not_touch_other_users_expired_tokens(db):
    """
    The per-user sweep is scoped to the verifying user.
    Another user's expired tokens must not be deleted.
    """
    import uuid as _uuid
    other_user_id = _uuid.uuid4()
    now = datetime.now(timezone.utc)

    other_expired = EmailVerification(
        user_id=other_user_id,
        token_hash=_sha256("other-user-expired"),
        expires_at=now - timedelta(hours=1),
    )
    db.add(other_expired)
    await db.commit()

    # Verify the primary user's token.
    raw = await generate_and_store_verification_token(USER_ID, db)
    await db.commit()
    await verify_token(raw, db)
    await db.commit()

    # Other user's expired row must still be present.
    from sqlalchemy import select
    result = await db.execute(
        select(EmailVerification).where(EmailVerification.id == other_expired.id)
    )
    assert result.scalar_one_or_none() is not None


# ── T-19: Endpoint redirect shape tests ───────────────────────────────────────
#
# These tests exercise the GET /auth/verify-email route via httpx AsyncClient.
# They check only the redirect URL shape — DB state is covered by the service
# tests above.
#
# Requires a `async_client` fixture in conftest.py that yields an httpx
# AsyncClient pointed at the test app (same pattern as T-18 endpoint tests).


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
