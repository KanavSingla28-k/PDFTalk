# Frontend AGENTS.md

Context for the Next.js frontend application.

## Purpose

This directory contains the Next.js 15.5 application using the App Router (`src/app/`). It is the client UI for PDFTalk.

## Architecture

- **Framework**: Next.js 15.5 (React 19.2, TypeScript 5).
- **Styling**: Tailwind CSS 4.
- **Routing**: App Router (`src/app/`).
- **Data Fetching & State**:
  - Context API (`src/contexts/`) for global state (Auth, Chat).
  - Custom fetch wrapper (`src/lib/api.ts`) handling tokens and 401 retries.
  - React Hook Form + Zod for form validation.
- **Components**: Radix UI primitives and custom components (`src/components/`).

## Critical Mechanisms

- **Routing Guard**: `src/middleware.ts` intercepts requests. It strictly checks for the presence of the `refresh_token` cookie to guard protected routes (`/dashboard`). Real token validation happens server-side via `/auth/me`.
- **API Client**: `src/lib/api.ts` implements a custom `fetch` wrapper that:
  - Injects the `Authorization: Bearer <token>` header from memory.
  - Always includes `credentials: 'include'` for `httpOnly` cookie support on `/auth/*` routes.
  - Automatically handles silent refresh on a 401 `TOKEN_EXPIRED` error (retrying exactly once).
  - Forces logout on `INVALID_TOKEN` or other 401 errors.
  - Maps backend errors to a custom `ApiError` class.

## Directory Structure & Child Contexts

- `src/`: Source code. See `src/AGENTS.md`.
- `public/`: Static assets.

## Related Context

- Root Architecture: `../AGENTS.md`
- Backend API Contracts: `../backend/app/routers/AGENTS.md`
