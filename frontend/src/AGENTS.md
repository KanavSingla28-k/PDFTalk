# Frontend Src AGENTS.md

Context for the frontend source directory (`frontend/src`).

## Purpose

Contains the application logic, UI components, and API integration for the Next.js frontend.

## Structure

- **`app/`**: Next.js App Router pages.
  - `auth/`: Login, register, forgot password, reset password.
  - `dashboard/`: Main application interface (protected).
  - `admin/`: Admin override interfaces.
- **`components/`**: Reusable React components.
  - Includes complex UI like `ChatSidebar` and `Citation` renderer.
  - Base UI components in `ui/`.
- **`contexts/`**: React Context providers.
  - `AuthContext.tsx`: Manages in-memory access token, refresh timers, and session restore (`/auth/me`). Injects token callbacks into `api.ts`.
  - `ChatContext.tsx`: Manages chat state and handles SSE streaming from the backend.
- **`lib/`**: API clients and utilities.
  - `api.ts`: Core fetch wrapper (handles 401s, silent refresh, `ApiError` mapping).
  - Domain-specific API clients (e.g., `auth.api.ts`, `documents.api.ts` (handles 3-phase presigned upload), `query.api.ts` (SSE reader)).
- **`env.ts`**: Zod validation for `NEXT_PUBLIC_*` environment variables.
- **`middleware.ts`**: Next.js edge middleware. Guards routes based on `refresh_token` cookie presence to prevent unauthenticated access to the dashboard.

## Invariants

- **Token Storage**: The access token is stored *only* in React memory (via `AuthContext`), never in `localStorage` (mitigates XSS). The refresh token is an `httpOnly` cookie managed entirely by the backend and browser.
- **EventSource**: The frontend uses `fetch` with a `ReadableStream` rather than the native `EventSource` for the `POST /query/ask` endpoint, because `EventSource` does not support POST requests or custom headers (like `Authorization: Bearer`).

## Related Context

- Parent context: `../AGENTS.md`
