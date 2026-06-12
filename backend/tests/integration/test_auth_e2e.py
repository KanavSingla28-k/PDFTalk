import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.user import User
from app.models.auth import EmailVerification

pytestmark = pytest.mark.integration

@pytest.mark.asyncio
async def test_full_auth_lifecycle(async_client: AsyncClient, db: AsyncSession):
    email = "lifecycle@example.com"
    password = "SecurePassword123!"     # pragma: allowlist secret

    # 1. Register
    reg_resp = await async_client.post(
        "/auth/register",
        json={"email": email, "password": password}
    )
    assert reg_resp.status_code == 202

    # Verify user is created but unverified
    result = await db.execute(select(User).where(User.email_lower == email.lower()))
    user = result.scalar_one()
    assert user.is_verified is False

    # Attempt to login before verifying (Failure Path)
    login_fail = await async_client.post(
        "/auth/login",
        json={"email": email, "password": password}
    )
    assert login_fail.status_code == 403
    assert login_fail.json()["error"] == "EMAIL_NOT_VERIFIED"

    # 2. Extract Token from DB to simulate email reception
    token_result = await db.execute(select(EmailVerification).where(EmailVerification.user_id == user.id))
    verification_entry = token_result.scalar_one()
    
    # We must generate the raw token. Wait, EmailVerification only stores the hashed token.
    # Because we patched out the email queue in conftest.py, we didn't capture the raw token.
    # To work around this, we can just manually set the user to verified or manually create a new token.
    # The integration goal is to hit the endpoint. Let's create a token explicitly.
    from app.services.email_verification import generate_and_store_verification_token
    raw_token = await generate_and_store_verification_token(str(user.id), db)
    await db.commit()

    # 3. Verify Email
    verify_resp = await async_client.get(
        f"/auth/verify-email?token={raw_token}",
        follow_redirects=False
    )
    assert verify_resp.status_code == 302
    assert "verified=true" in verify_resp.headers["location"]

    await db.refresh(user)
    assert user.is_verified is True

    # Attempt login with wrong credentials (Failure Path)
    login_wrong = await async_client.post(
        "/auth/login",
        json={"email": email, "password": "WrongPassword!"}   # pragma: allowlist secret
    )   
    assert login_wrong.status_code == 401

    # 4. Login Successfully
    login_success = await async_client.post(
        "/auth/login",
        json={"email": email, "password": password}
    )
    assert login_success.status_code == 200
    access_token = login_success.json()["access_token"]
    assert access_token is not None
    assert "refresh_token" in login_success.cookies

    old_refresh_cookie = login_success.cookies.get("refresh_token")

    # 5. Refresh Token
    refresh_resp = await async_client.post("/auth/refresh")
    assert refresh_resp.status_code == 200
    new_access_token = refresh_resp.json()["access_token"]
    assert new_access_token != access_token
    
    # 6. Logout
    logout_resp = await async_client.post("/auth/logout")
    assert logout_resp.status_code == 204

    # Refresh should fail now
    refresh_fail = await async_client.post("/auth/refresh")
    assert refresh_fail.status_code == 401
