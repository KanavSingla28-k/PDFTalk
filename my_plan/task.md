# Frontend & Launch Task List (Tasks 46 - 63)

This task list integrates `pdftalk_mvp_tasklist.md` with `frontend_api_reference.md`. All gaps, missing error paths, and design decisions identified in review have been incorporated.

---

## Phase 10 — Frontend

---

### T-46: Next.js Scaffold & Foundation ✅

- `[x]` Initialize Next.js 15 App Router in `frontend/`.
- `[x]` Configure TypeScript, ESLint, Prettier, and TailwindCSS.
- `[x]` Install `react-hook-form`, `zod`, and `@hookform/resolvers`.
- `[x]` Configure `next.config.ts` with `NEXT_PUBLIC_API_URL` (`http://localhost:8000` in dev).
- `[x]` Set up `src/middleware.ts` for protected route redirects (unauthenticated → `/login`).

---

### T-47: API Client Layer ✅

> **Sequencing note:** Build this before T-48 and T-49. All pages depend on this layer.

- `[x]` Create `src/lib/api.ts` — typed base fetch wrapper with the following behaviour:
  - Attach `Authorization: Bearer <token>` from in-memory state on every call.
  - Parse response body and throw a typed `ApiError` on all non-2xx responses.
  - **401 handling (differentiated):**
    - If `error === "TOKEN_EXPIRED"`: silently call `POST /auth/refresh` (`credentials: 'include'`) and **retry the original request once**.
    - If `error === "INVALID_TOKEN"`: do **not** retry — clear state and redirect to `/login` immediately.
    - Any other `401`: treat as `INVALID_TOKEN` (redirect, no retry).
  - **5xx fallback:** Named error codes (`AI_SERVICE_UNAVAILABLE`, etc.) are handled explicitly. For `502` responses with no error code body (e.g. S3 deletion failure on `DELETE /documents/{id}`), surface a generic "Service error. Please try again." — do not crash.
  - **`ACCOUNT_INACTIVE` (403):** Map explicitly → "Your account has been deactivated. Contact support."
  - Read `Retry-After` header on `429` responses and expose it to callers.
  - Pass `credentials: 'include'` on all requests so the browser sends the httpOnly refresh cookie on `/auth/*`.

- `[x]` Split into separate modules:
  - `src/lib/auth.api.ts` — register, login, refresh, logout
  - `src/lib/documents.api.ts` — upload, status, list, delete
  - `src/lib/query.api.ts` — ask (SSE streaming)

- `[x]` Define and export a typed `ApiError` class:
  ```ts
  class ApiError extends Error {
    constructor(
      public code: string,        // e.g. "TOKEN_EXPIRED", "UNKNOWN_5XX"
      public message: string,
      public status: number,
      public retryAfter?: number, // seconds from Retry-After header
    ) { super(message) }
  }
  ```

---

### T-48: Auth Pages & Email Verification UI ✅

> **Sequencing note:** All forms on these pages must work **without** an authenticated user — specifically the resend verification button. Do NOT gate any call here behind `AuthContext`.

- `[x]` **`/register` page**
  - Zod-validated form: email + password with inline client-side password rules feedback:
    - ≥ 8 chars, 1 uppercase, 1 lowercase, 1 number, 1 special char
    - Show per-rule status (✓/✗) as the user types — don't wait for submit.
  - Call `POST /auth/register`. On `202 Accepted`, show a **confirmation screen** (not a toast) that says "Check your inbox for a verification email."
  - **Resend flow on confirmation screen:** The confirmation screen must include a "Resend verification email" button that calls `POST /auth/register` again with the same email. (This is the same endpoint — the backend re-sends if unverified.) This button must be present here, not only on `/verify-email`.
  - Handle `429 RATE_LIMIT_EXCEEDED` with cooldown timer using `Retry-After` header.

- `[x]` **`/login` page**
  - Zod-validated form: email + password.
  - Call `POST /auth/login`. On success (`200 OK`):
    - Store `access_token` in `AuthContext` (in-memory only).
    - Store `user.id` and `user.email` in `AuthContext`.
    - Schedule proactive token refresh timer.
    - Redirect to `/dashboard/documents`.
  - Handle `403 EMAIL_NOT_VERIFIED` → show "Your email isn't verified yet." + "Resend verification email" button (calls `POST /auth/register` with entered email).
  - Handle `401 INVALID_CREDENTIALS` → generic "Invalid email or password." (never specific).
  - Handle `429 RATE_LIMIT_EXCEEDED` → show cooldown timer.
  - Read `?verified=true` query param on mount → show success toast: "Email verified! You can now log in."

- `[x]` **`/verify-email` page**
  - **Case 1 — Error from backend redirect:** Read `?error=` query param:
    - `invalid_token` → "This verification link is invalid or has already been used."
    - `token_expired` → "This verification link has expired."
    - Show a "Resend verification email" button (prompt for email, then call `POST /auth/register`).
  - **Case 2 — No query param at all (direct navigation):** If the user navigates to `/verify-email` with no `?token=` or `?error=` params, show a neutral message: "Check your inbox for a verification link." with a resend option. Do **not** call the backend or show an error.
  - **Case 3 — Backend 422 (missing token param):** If for some reason the request hits this page after a backend `422`, treat it the same as Case 2 (the backend redirect handles this, so this is a fallback).

---

### T-49: Auth Context & Protected Routes ✅

> **Design decision — `user` population on refresh:**
> `POST /auth/refresh` returns `{ access_token, token_type, expires_in }` only — **no `user` field**.
> On app mount (session restore via refresh), we do not have the user object.
> **Chosen approach:** On successful refresh, keep `user` as `null` until a page that needs it fetches it, OR store `{ id, email }` in a `SameSite=Strict` non-httpOnly cookie that the frontend sets itself after login. The simpler MVP approach: store user in `sessionStorage` only (acceptable since it doesn't contain a token, only non-secret user info), restore from `sessionStorage` on mount alongside the refresh call.
> **If a `GET /auth/me` endpoint is added to the backend later**, switch to that.

- `[x]` Create `src/contexts/AuthContext.tsx` holding:
  ```ts
  interface AuthState {
    user: { id: string; email: string } | null;
    accessToken: string | null;
    isLoading: boolean;
  }
  ```
- `[x]` Store `access_token` **only in React state** — never localStorage, sessionStorage, or cookies.
- `[x]` Store `user` object in `sessionStorage` (non-sensitive) to survive page refresh.
- `[x]` **Session restore on app mount:**
  1. Set `isLoading = true`.
  2. Call `POST /auth/refresh` with `credentials: 'include'`.
  3. On `200`: save `access_token` in state, restore `user` from `sessionStorage`, schedule refresh timer.
  4. On `401`: clear all state, redirect to `/login`.
- `[x]` **Proactive token refresh timer:** Call `/auth/refresh` at `(expires_in - 60)` seconds.
  - **Multi-tab race condition (note / defer for post-MVP):** If two tabs are open, both will attempt refresh simultaneously. The token is one-time-use — the second tab's refresh will get `401` and log the user out. Standard mitigation is `BroadcastChannel` to sync the new token across tabs. **For MVP: defer this.** Document that users with multiple tabs open may experience unexpected logouts; fix before v1.1.
- `[x]` **Logout:** Call `POST /auth/logout`, clear `accessToken` from state, clear `user` from `sessionStorage`, redirect to `/login`.
- `[x]` Create `useAuth()` hook that reads from `AuthContext`.

---

### T-50: Document Upload UI (`/dashboard/upload`) ✅

- `[x]` Drag-and-drop file picker using `react-dropzone`.
  - Accept only `.pdf`, `.txt`, `.md` extensions.
  - Show accepted/rejected state visually.
- `[x]` **Client-side pre-validation before upload:**
  - File size ≤ 50 MB (reject immediately with inline error).
  - File extension in allowed list.
- `[x]` Upload via `POST /documents/upload` (`multipart/form-data`) with Bearer token.
- `[x]` Handle all upload error responses:
  - `422 FILE_VALIDATION_FAILED` + `reason: "file_too_large"` → "File must be under 50 MB."
  - `422 FILE_VALIDATION_FAILED` + `reason: "unsupported_mime"` → "Only PDF, TXT, and MD files are supported."
  - `422 FILE_VALIDATION_FAILED` + `reason: "invalid_magic_bytes"` → "This file appears to be corrupt or renamed. Please check the file and try again."
  - `429 RATE_LIMIT_EXCEEDED` → show cooldown timer from `Retry-After` header.
  - `429 DAILY_QUOTA_EXCEEDED` → "You've reached your daily document limit. Try again tomorrow."
  - **`503` (Redis/queue unavailable)** → "Upload queue is temporarily unavailable. Please try again shortly."
- `[x]` On success (`202 Accepted`): navigate to `/dashboard/documents` and begin polling for the new document's status.

---

### T-51: Document List & Status UI (`/dashboard/documents`) ✅

- `[x]` Fetch paginated document list via `GET /documents` on mount.
- `[x]` Display each document with status badge: `PENDING` / `PROCESSING` / `READY` / `FAILED`.
- `[x]` **Polling for non-terminal statuses (exact strategy from API reference):**
  - Poll `GET /documents/{document_id}/status` every **2s for the first 30s**.
  - Then switch to every **5s**.
  - **Hard timeout at 5 minutes:** Stop polling and show: "Processing is taking longer than expected. Please check back later or try re-uploading."
- `[x]` For `FAILED` documents: show `error_message` from the API response and offer "Delete & Re-upload" option.
- `[x]` **Delete document** via `DELETE /documents/{document_id}`:
  - On `204 No Content`: remove document from list.
  - **On `502` (S3 deletion failure):** Show toast "Deletion failed due to a storage error. Please try again." The document remains in the list — do **not** remove it from UI state (API guarantees DB integrity). *(previously missing)*
  - On `404`: show "Document not found." and remove from list.
- `[x]` Link `READY` documents to `/dashboard/chat?doc={document_id}`.

---

### T-52: Chat / Q&A UI — SSE Streaming (`/dashboard/chat`) ✅

- `[x]` **Document selector:** Multi-select of user's `READY` documents only. Max 10 selections enforced with inline feedback.
- `[x]` **Question input:**
  - Max 1000 characters.
  - **Live character counter** (e.g. "247 / 1000") visible below the input. *(previously missing)*
  - Disable submit when input is empty or over limit.
- `[x]` Call `POST /query/ask` with headers: `Authorization: Bearer <token>`, `Accept: text/event-stream`.
- `[x]` **Handle pre-stream HTTP errors (before stream opens):**
  - `404 DOCUMENT_NOT_FOUND` → "One or more selected documents could not be found."
  - `409 DOCUMENT_NOT_READY` → "A selected document is still processing. Please wait."
  - `429 DAILY_QUERY_QUOTA_EXCEEDED` → "You've reached your daily query limit. Try again tomorrow."
  - `503 AI_SERVICE_UNAVAILABLE` → "The AI service is temporarily unavailable. Please try again shortly."
  - Any other `4xx/5xx` → generic "Something went wrong. Please try again."
- `[x]` **SSE stream reading — use the buffer-accumulation pattern (non-negotiable):**
  ```ts
  // CORRECT: accumulate buffer and split on \n\n
  // Naive line-by-line split WILL break when SSE events span multiple TCP chunks.
  let buffer = '';
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split('\n\n');
    buffer = parts.pop()!; // keep the incomplete trailing part
    for (const part of parts) {
      if (!part.startsWith('data: ')) continue;
      const data = part.slice(6);
      // ... handle data
    }
  }
  ```
- `[x]` **Handle SSE stream events:**
  - `data: {"type": "token", "content": "Hello"}` → append to chat bubble.
  - `data: {"error": "AI_SERVICE_UNAVAILABLE", "message": "..."}` → show inline error inside chat bubble (e.g., "[Error] AI service went down mid-response.") and close stream cleanly.
  - `data: [DONE]` → close stream cleanly.

---

### T-53: Global UI Elements & Polish ✅

- `[x]` **Global React Error Boundary** wrapping the full app — show a fallback UI instead of a blank crash.
- `[x]` **Toast notification system** (`sonner` / `apiToast` helper):
  - Map every named `ApiError` code to a user-friendly message (including `ACCOUNT_INACTIVE`, `502` fallback).
  - Use `Retry-After` header to show cooldown timers on `429` responses natively via the helper.
- `[x]` Ensure all pages are **responsive** (mobile, tablet, desktop).
- `[x]` **Accessibility:** Semantic HTML5, ARIA labels on interactive elements, keyboard navigation, colour contrast ≥ 4.5:1.

---

## Phase 11 — Docker + Production

- `[ ]` **T-54: Dockerize FastAPI** (Backend)
- `[ ]` **T-55: Dockerize RQ worker** (Backend)
- `[ ]` **T-56: Production Docker Compose**
  - `[ ]` Wire up `nginx` service to serve static Next.js `out/` directory.
- `[ ]` **T-57: Production Nginx config**
  - `[ ]` Static frontend serving (`root /usr/share/nginx/html;`, `try_files $uri $uri.html /index.html;`).
  - `[ ]` SSE proxy config for `/api/query/ask`: `proxy_buffering off`, `proxy_read_timeout 300s`, `proxy_http_version 1.1`.
- `[ ]` **T-58: GitHub Actions CI Pipeline**
  - `[ ]` Frontend jobs: `pnpm install --frozen-lockfile`, `pnpm type-check`, `pnpm lint`, `pnpm test`.
- `[ ]` **T-59: GitHub Actions CD Pipeline** (Backend-led, deploys built frontend static files)

---

## Phase 12 — Testing & Launch

- `[ ]` **T-60: Backend unit tests**
- `[ ]` **T-61: Backend integration tests**
- `[ ]` **T-62: Backup automation**
- `[ ]` **T-63: Production smoke test + launch checklist**
  - `[ ]` End-to-end smoke test: Register → Verify email → Login → Upload PDF → Poll to READY → Ask question → Assert non-empty streamed answer → Logout.
  - `[ ]` Execute final security and launch checklist (see `pdftalk_mvp_tasklist.md` T-63).

---

## Open Design Decisions

| # | Decision | Status | Chosen Approach |
|---|---|---|---|
| 1 | How to populate `user` in AuthContext after `POST /auth/refresh` (which returns no user field) | **Resolved for MVP** | Store `{ id, email }` in `sessionStorage` after login; restore on mount alongside refresh call. Revisit if `GET /auth/me` is added. |
| 2 | Multi-tab token refresh race condition (one-time-use refresh token) | **Deferred to post-MVP** | Both tabs attempt refresh; second tab gets `401` and forces re-login. Fix with `BroadcastChannel` in v1.1. |
| 3 | Resend verification button must work without auth | **Resolved** | `POST /auth/register` requires no auth token. All pages in T-48 call it directly — no AuthContext dependency. |
