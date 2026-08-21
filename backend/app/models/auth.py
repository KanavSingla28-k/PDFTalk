from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator
from sqlalchemy import DateTime, ForeignKey, Index, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    __table_args__ = (
        Index("idx_refresh_tokens_user_id", "user_id"),
        # This index is on the lookup path for every token refresh request.
        # Must be fast — it's hit on every page load after access token expiry.
        Index("idx_refresh_tokens_token_hash", "token_hash"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    # SHA-256 hash of the raw token. Raw token is in the browser's httpOnly cookie only.
    # If this table leaks, attackers get hashes — not usable tokens.
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="refresh_tokens")


class EmailVerification(Base):
    __tablename__ = "email_verifications"
    __table_args__ = (Index("idx_email_verifications_token_hash", "token_hash"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    user: Mapped[User] = relationship(back_populates="email_verifications")


class PasswordReset(Base):
    __tablename__ = "password_resets"
    __table_args__ = (
        Index("idx_password_resets_user_id", "user_id"),
        Index("idx_password_resets_token_hash", "token_hash"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    user: Mapped[User] = relationship(back_populates="password_resets")


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>/?]", v):
            raise ValueError("Password must contain at least one special character")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one number")
        return v


class RegisterResponse(BaseModel):
    message: str


class ResendVerificationRequest(BaseModel):
    email: EmailStr


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>/?]", v):
            raise ValueError("Password must contain at least one special character")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one number")
        return v


class LoginRequest(BaseModel):
    """
    POST /auth/login request body.

    email is normalised to lowercase in the service layer, not here —
    keeping the schema clean and the normalisation logic in one place.
    """

    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    """
    POST /auth/login success response body.

    Security note on access_token placement
    ----------------------------------------
    The access token is returned in the JSON body (not a cookie) per the
    OAuth 2.0 Bearer Token spec. This is correct and intentional.

    The XSS exposure is real but mitigated by architecture, not by this
    endpoint:
      - The token has a 15-minute TTL — short enough to limit blast radius.
      - The frontend MUST store it in React memory (Context/state), never
        in localStorage or sessionStorage, which are readable by any JS.
      - The refresh token travels in an httpOnly cookie and is therefore
        completely inaccessible to JavaScript — including XSS payloads.
      - An XSS attacker who steals the in-memory access token gets at most
        15 minutes of access with no way to renew it.

    See T-47 for the frontend storage contract.

    user field
    ----------
    Included to save the frontend a round-trip to /auth/me immediately
    after login. Contains only safe, non-sensitive fields.
    """

    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds until access token expiry
    user: UserInfo


class UserInfo(BaseModel):
    """Minimal user payload safe to include in the login response body."""

    id: str
    email: str

    model_config = ConfigDict(
        from_attributes=True
    )  # allows construction from a SQLAlchemy User model


class MeResponse(BaseModel):
    """
    GET /auth/me response body.

    When the request carried a valid Bearer token, `access_token` and
    `expires_in` are None — the caller already has a valid token.

    When the request had no Bearer token but a valid refresh cookie,
    the endpoint silently rotates the refresh token and returns a fresh
    access token here so the frontend can restore its in-memory auth state
    in a single round trip.
    """

    id: str
    email: str
    access_token: str | None = None
    token_type: str = "bearer"
    expires_in: int | None = None  # seconds, only present on silent refresh

    model_config = ConfigDict(from_attributes=True)


class RefreshResponse(BaseModel):
    """
    Returned by POST /auth/refresh.

    Mirrors the token fields of LoginResponse without the user object —
    the caller only needs new tokens, not a repeated user lookup.
    """

    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds until the new access token expires


# Resolve forward reference
LoginResponse.model_rebuild()
