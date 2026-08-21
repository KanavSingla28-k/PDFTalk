# Auth AGENTS.md

Context for authentication logic (`backend/app/auth`).

## Purpose

Handles token creation, validation, and JWT lifecycle management.

## Core Mechanisms

- **JWT Access Tokens**: Issued via `tokens.py`. Valid for 15 minutes, signed using HS256. Contains claims `sub`, `iat`, `exp`, `jti`, `type`.
- **Refresh Tokens**: Opaque tokens, SHA-256 hashed and stored in the database. Sent to the client as an `httpOnly` cookie. **Rotated on every use**.
- **Dependencies (`dependencies.py`)**:
  - `get_current_user()`: Validates token signature only. Fast path, no DB access.
  - `get_verified_user()`: Validates token and fetches user from the DB to ensure `is_active` and `is_verified` are true.
- **Passwords (`password.py`)**: Handled via bcrypt. Includes a timing-safe dummy hash mechanism for unknown emails during login to prevent user enumeration.

## Known Bugs

- A non-UUID JWT `sub` causes an unhandled 500 error in `dependencies.py:78`.

## Related Context

- Parent context: `../AGENTS.md`
- API Routers: `../routers/AGENTS.md` (specifically `auth.py`)
