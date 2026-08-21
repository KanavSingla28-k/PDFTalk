import pytest
from httpx import AsyncClient
from app.core.config import settings


@pytest.mark.asyncio
async def test_admin_auth_missing_token(async_client: AsyncClient, monkeypatch):
    # Set ADMIN_TOKEN to None
    monkeypatch.setattr(settings, "ADMIN_TOKEN", None)

    response = await async_client.post(
        "/internal/alerts/webhook",
        json={"alerts": []},
        headers={"Authorization": "Bearer some-token"},
    )
    assert response.status_code == 500
    assert "ADMIN_TOKEN is not configured on the server." in response.json()["detail"]


@pytest.mark.asyncio
async def test_admin_auth_invalid_token(async_client: AsyncClient, monkeypatch):
    # Set ADMIN_TOKEN to a specific token
    monkeypatch.setattr(settings, "ADMIN_TOKEN", "super-secret-admin-token")

    response = await async_client.post(
        "/internal/alerts/webhook",
        json={"alerts": []},
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Forbidden"


@pytest.mark.asyncio
async def test_admin_auth_valid_token(async_client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_TOKEN", "super-secret-admin-token")

    response = await async_client.post(
        "/internal/alerts/webhook",
        json={"alerts": []},
        headers={"Authorization": "Bearer super-secret-admin-token"},
    )
    assert response.status_code == 204
