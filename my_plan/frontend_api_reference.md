# PDFTalk Backend — Frontend Integration Reference

> **Purpose:** Everything a frontend developer needs to know to build the PDFTalk UI without reading a single line of backend Python.
> **Base URL (dev):** `http://localhost:8000`
> **Base URL (prod):** Set via `APP_URL` env var.

---

## Table of Contents

1. [Authentication Model](#1-authentication-model)
2. [API Endpoints](#2-api-endpoints)
   - [POST /auth/register](#post-authregister)
   - [GET /auth/verify-email](#get-authverify-email)
   - [POST /auth/login](#post-authlogin)
   - [POST /auth/refresh](#post-authrefresh)
   - [POST /auth/logout](#post-authlogout)
   - [POST /documents/upload](#post-documentsupload)
   - [GET /documents/{document_id}/status](#get-documentsdocument_idstatus)
   - [GET /documents](#get-documents)
   - [DELETE /documents/{document_id}](#delete-documentsdocument_id)
   - [POST /query/ask](#post-queryask)
   - [GET /health](#get-health)
3. [Token Storage Contract](#3-token-storage-contract)
4. [Error Response Format](#4-error-response-format)
5. [All Error Codes Reference](#5-all-error-codes-reference)
6. [Rate Limits](#6-rate-limits)
7. [Document Status Lifecycle](#7-document-status-lifecycle)
8. [SSE Streaming Protocol](#8-sse-streaming-protocol)
9. [Password Rules](#9-password-rules)
10. [File Upload Rules](#10-file-upload-rules)
11. [CORS Configuration](#11-cors-configuration)
12. [Frontend Flow Diagrams](#12-frontend-flow-diagrams)

---

## 1. Authentication Model

PDFTalk uses a **two-token system**:

| Token | Lives Where | Lifetime | Purpose |
|---|---|---|---|
| **Access Token** (JWT) | React memory (state/context) — **never** localStorage | 15 minutes | Sent as `Authorization: Bearer <token>` on every API call |
| **Refresh Token** | `httpOnly` cookie — JS cannot read it | 7 days | Silently renews the access token via `POST /auth/refresh` |

**Key consequences for the frontend:**
- When the app loads (or after a page refresh), the access token in memory is gone. Call `POST /auth/refresh` immediately on mount to restore the session silently.
- The refresh cookie is `path=/auth`, so it is **only sent** on `/auth/*` requests — not on every document/query call.
- The refresh token is **one-time-use** and **rotated** on every call to `/auth/refresh`. Store the new access token returned in the response.

---

## 2. API Endpoints

### POST /auth/register

Create a new account. Also re-sends the verification email if the email is already registered but not yet verified.

**Request**
```json
{
  "email": "user@example.com",
  "password": "MySecure1!"
}
```

**Success Response — 202 Accepted**
```json
{
  "message": "Verification email sent"
}
```

> [!IMPORTANT]
> This endpoint **always returns 202** regardless of whether the email already exists. This is intentional to prevent user enumeration — never show "email already taken" to the user.

> [!NOTE]
> If email delivery fails (Resend API error), the API still returns 202 but logs internally. The user row is still created. Prompt the user to check their inbox or use a "resend" flow.

**Errors**

| Status | `error` code | When |
|---|---|---|
| 422 | Pydantic validation | Invalid email format or password doesn't meet requirements |
| 429 | `RATE_LIMIT_EXCEEDED` | More than 5 registrations per IP per hour |

---

### GET /auth/verify-email

The user clicks the link in their email. This is a **redirect endpoint** — the browser follows the link, the backend validates the token, and **redirects the browser** to the frontend.

**Query Param:** `?token=<raw_token_from_email>`

**Success -> HTTP 302 redirect to:**
```
{APP_URL}/login?verified=true
```

**Failure -> HTTP 302 redirect to:**
```
{APP_URL}/verify-email?error=invalid_token
{APP_URL}/verify-email?error=token_expired
```

**Frontend pages needed:**
- `/login` — read `?verified=true` and show a success toast: *"Email verified! You can now log in."*
- `/verify-email` — read `?error=invalid_token` or `?error=token_expired` and show appropriate message with a resend button.

**Errors**

| Status | When |
|---|---|
| 422 | `?token=` query param is missing entirely |

---

### POST /auth/login

Authenticate a user and receive tokens.

**Request**
```json
{
  "email": "user@example.com",
  "password": "MySecure1!"
}
```

**Success Response — 200 OK**

The response **body** contains the access token. A `Set-Cookie: refresh_token=...` header is also set (httpOnly, SameSite=Strict).

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 900,
  "user": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "email": "user@example.com"
  }
}
```

> [!NOTE]
> Store `access_token` in React state/context — **not** localStorage or sessionStorage. Store `user.id` and `user.email` in your auth context to save a network round-trip.

**Errors**

| Status | `error` code | When |
|---|---|---|
| 401 | `INVALID_CREDENTIALS` | Wrong email, wrong password, inactive account, or locked account. **Message is always generic** — do not surface the specific reason. |
| 403 | `EMAIL_NOT_VERIFIED` | Email exists but hasn't been verified yet. Show "resend verification" prompt. |
| 429 | `RATE_LIMIT_EXCEEDED` | More than 10 login attempts per IP per minute. |

---

### POST /auth/refresh

Exchange the refresh token cookie for a new access token. Call this **silently** when the access token expires (or on app mount when in-memory token is gone).

**Request body:** Empty (`{}` or no body)
**Cookie required:** `refresh_token` (sent automatically by the browser for `/auth/*`)

**Success Response — 200 OK**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 900
}
```

A new `Set-Cookie: refresh_token=...` header rotates the cookie.

**Errors**

| Status | `error` code | When |
|---|---|---|
| 401 | `"No refresh token provided."` | Cookie is missing — user is logged out. Redirect to `/login`. |
| 401 | `"Refresh token not found or expired."` | Token was already used or expired. Redirect to `/login`. |

> [!IMPORTANT]
> If you get a 401 from `/auth/refresh`, the session is dead — clear the in-memory access token and redirect the user to login. **Do not retry** the refresh call.

---

### POST /auth/logout

Revoke the session server-side and clear the cookie. Always call this when the user clicks "Log out".

**Request body:** Empty. Cookie is read automatically.

**Success Response — 204 No Content** (empty body)

> [!NOTE]
> This endpoint is idempotent — it returns 204 even if no cookie was present or the token was already expired. Safe to call unconditionally.

---

### POST /documents/upload

Upload a PDF, plain text, or Markdown file for AI ingestion.

**Request:** `multipart/form-data`

| Field | Type | Notes |
|---|---|---|
| `file` | File | Required. Max 50 MB. Allowed: `.pdf`, `.txt`, `.md` |

**Headers required:** `Authorization: Bearer <access_token>`

**Success Response — 202 Accepted**
```json
{
  "document_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "PENDING"
}
```

The document is queued for background processing. The frontend should **poll** `GET /documents/{document_id}/status` until status is `READY` or `FAILED`.

**Errors**

| Status | `error` code | `reason` field | When |
|---|---|---|---|
| 401 | `TOKEN_EXPIRED` | — | Access token expired |
| 401 | `INVALID_TOKEN` | — | No/bad token |
| 403 | `EMAIL_NOT_VERIFIED` | — | Account not verified |
| 422 | `FILE_VALIDATION_FAILED` | `file_too_large` | File > 50 MB |
| 422 | `FILE_VALIDATION_FAILED` | `unsupported_mime` | File type not allowed |
| 422 | `FILE_VALIDATION_FAILED` | `invalid_magic_bytes` | File has wrong binary signature (e.g. renamed file) |
| 429 | `RATE_LIMIT_EXCEEDED` | — | More than 5 uploads per user per minute |
| 429 | `DAILY_QUOTA_EXCEEDED` | — | User document quota reached (default: 20 docs) |
| 503 | `"Processing queue unavailable."` | — | Redis is down — tell user to retry |

---

### GET /documents/{document_id}/status

Poll this endpoint to check ingestion progress.

**Headers required:** `Authorization: Bearer <access_token>`

**Success Response — 200 OK**
```json
{
  "document_id": "550e8400-e29b-41d4-a716-446655440000",
  "filename": "my-report.pdf",
  "status": "READY",
  "error_message": null,
  "chunk_count": 47,
  "file_size_bytes": 2097152,
  "mime_type": "application/pdf",
  "created_at": "2026-06-09T10:00:00Z",
  "updated_at": "2026-06-09T10:00:35Z"
}
```

**`status` values:** `PENDING` | `PROCESSING` | `READY` | `FAILED`

When `status == "FAILED"`, `error_message` will contain a short description of what went wrong (e.g. "Document has 650,000 tokens; limit is 500,000").

**Errors**

| Status | `error` code | When |
|---|---|---|
| 404 | `DOCUMENT_NOT_FOUND` | Document doesn't exist **or** belongs to another user (same error — no resource enumeration) |

**Recommended polling strategy:**
```
Poll every 2s for first 30s -> every 5s after -> give up at 5 min
```

---

### GET /documents

Paginated list of the current user's documents.

**Headers required:** `Authorization: Bearer <access_token>`

**Query Params**

| Param | Type | Default | Notes |
|---|---|---|---|
| `status` | string | (none) | Filter: `PENDING`, `PROCESSING`, `READY`, `FAILED` |
| `limit` | int | 10 | 1-100 |
| `offset` | int | 0 | >= 0 |

**Success Response — 200 OK**
```json
{
  "items": [
    {
      "document_id": "550e8400-e29b-41d4-a716-446655440000",
      "filename": "annual-report.pdf",
      "status": "READY",
      "error_message": null,
      "chunk_count": 84,
      "file_size_bytes": 5242880,
      "mime_type": "application/pdf",
      "created_at": "2026-06-09T10:00:00Z",
      "updated_at": "2026-06-09T10:00:45Z"
    }
  ],
  "total": 1,
  "limit": 10,
  "offset": 0,
  "pages": 1
}
```

---

### DELETE /documents/{document_id}

Permanently delete a document and all its AI chunks. Deletes from S3 first, then the database.

**Headers required:** `Authorization: Bearer <access_token>`

**Success Response — 204 No Content** (empty body)

**Errors**

| Status | `error` code | When |
|---|---|---|
| 404 | `DOCUMENT_NOT_FOUND` | Doesn't exist or belongs to another user |
| 502 | — | S3 deletion failed (AWS outage). Document is **not** deleted from DB. Tell user to retry. |

---

### POST /query/ask

Ask a question against one or more uploaded, `READY` documents. Returns a **Server-Sent Events (SSE)** stream.

**Headers required:**
```
Authorization: Bearer <access_token>
Accept: text/event-stream
```

**Request Body**
```json
{
  "document_ids": [
    "550e8400-e29b-41d4-a716-446655440000",
    "660e8400-e29b-41d4-a716-446655440001"
  ],
  "question": "What was the revenue in Q3?"
}
```

**Validation:**
- `document_ids`: 1-10 UUIDs, must not be empty
- `question`: 1-1000 characters, stripped of leading/trailing whitespace

**Pre-stream errors (normal HTTP responses):**

| Status | `error` code | When |
|---|---|---|
| 401/403 | Auth codes | Token invalid/expired, account inactive/unverified |
| 404 | `DOCUMENT_NOT_FOUND` | Any document ID doesn't exist or not owned by user |
| 409 | `DOCUMENT_NOT_READY` | Any document is `PENDING`, `PROCESSING`, or `FAILED` |
| 422 | Pydantic | Empty list, too many docs, empty/too-long question |
| 429 | `DAILY_QUERY_QUOTA_EXCEEDED` | User hit daily query limit (default: 500/day) |
| 503 | `AI_SERVICE_UNAVAILABLE` | OpenAI circuit breaker is open |

**Success Response — 200 OK** with `Content-Type: text/event-stream`

See [Section 8 - SSE Streaming Protocol](#8-sse-streaming-protocol) for full details.

---

### GET /health

Check backend service health. No auth required.

**Success Response — 200 OK (all services healthy)**
```json
{
  "status": "ok",
  "timestamp": "2026-06-09T10:00:00Z",
  "checks": {
    "db":    { "status": "ok", "latency_ms": 3 },
    "redis": { "status": "ok", "latency_ms": 1 },
    "s3":    { "status": "ok", "latency_ms": 45 }
  }
}
```

**Degraded Response — 503** (any service failing)
```json
{
  "status": "degraded",
  "timestamp": "2026-06-09T10:00:00Z",
  "checks": {
    "db":    { "status": "ok",    "latency_ms": 3 },
    "redis": { "status": "error", "latency_ms": 500, "detail": "Connection refused" },
    "s3":    { "status": "ok",    "latency_ms": 45 }
  }
}
```

---

## 3. Token Storage Contract

```
Store access_token in:   React Context, Zustand store, useState — in-memory only
Never store in:          localStorage, sessionStorage, cookies

Send on every API call:  Authorization: Bearer <access_token>
Refresh token:           httpOnly cookie, set/cleared automatically by the browser
```

**Session restore on app mount:**
```js
async function restoreSession() {
  try {
    const res = await fetch('/auth/refresh', {
      method: 'POST',
      credentials: 'include',  // send the httpOnly cookie
    })
    if (res.ok) {
      const { access_token, expires_in, user } = await res.json()
      setAccessToken(access_token)  // store in React state
      scheduleRefresh(expires_in)   // refresh 60s before expiry
    } else {
      redirectToLogin()
    }
  } catch {
    redirectToLogin()
  }
}
```

**Proactive token refresh (recommended over reactive):**
Set a timer to call `/auth/refresh` ~60 seconds before the access token expires (`expires_in - 60`). This prevents API calls from failing mid-session.

---

## 4. Error Response Format

All API errors (except SSE mid-stream errors) use this consistent JSON shape:

```json
{
  "error": "SCREAMING_SNAKE_CASE_CODE",
  "message": "Human-readable description"
}
```

File validation errors additionally include a `reason` field:
```json
{
  "error": "FILE_VALIDATION_FAILED",
  "reason": "file_too_large",
  "message": "File exceeds the maximum allowed size of 50 MB."
}
```

Pydantic validation errors (422) use FastAPI's default format:
```json
{
  "detail": [
    {
      "loc": ["body", "email"],
      "msg": "value is not a valid email address",
      "type": "value_error.email"
    }
  ]
}
```

Rate limit responses include a `Retry-After` header (seconds):
```
HTTP 429 Too Many Requests
Retry-After: 47
```

---

## 5. All Error Codes Reference

| `error` code | HTTP | Meaning | Suggested UI |
|---|---|---|---|
| `INVALID_CREDENTIALS` | 401 | Wrong email or password (generic) | "Invalid email or password" |
| `EMAIL_NOT_VERIFIED` | 403 | Account exists but not verified | Show "Resend verification email" button |
| `TOKEN_EXPIRED` | 401 | Access token has expired | Silently call `/auth/refresh`, then retry |
| `INVALID_TOKEN` | 401 | Token malformed or missing | Redirect to `/login` |
| `ACCOUNT_INACTIVE` | 403 | Account has been deactivated | "Your account is deactivated. Contact support." |
| `RATE_LIMIT_EXCEEDED` | 429 | Too many requests from this user/IP | Show cooldown timer using `Retry-After` header |
| `DAILY_QUOTA_EXCEEDED` | 429 | Token quota hit (ingestion) | "Daily usage limit reached. Try again tomorrow." |
| `DAILY_QUERY_QUOTA_EXCEEDED` | 429 | Query quota hit | "Daily query limit reached. Try again tomorrow." |
| `FILE_VALIDATION_FAILED` | 422 | Upload failed validation | Show reason: `file_too_large` / `unsupported_mime` / `invalid_magic_bytes` |
| `DOCUMENT_NOT_FOUND` | 404 | Document missing or not owned by user | "Document not found." |
| `DOCUMENT_NOT_READY` | 409 | Document is still processing/failed | "Document is not ready yet." |
| `AI_SERVICE_UNAVAILABLE` | 503 | OpenAI circuit breaker open | "AI service temporarily unavailable. Try again shortly." |

**SSE-only error codes** (sent as terminal SSE events, not HTTP status codes):

| SSE `error` code | Meaning | Suggested UI |
|---|---|---|
| `STREAM_TIMEOUT` | OpenAI took too long between tokens | "Response timed out. Please try again." |
| `STREAM_ERROR` | Unexpected error mid-generation | "Something went wrong. Please try again." |
| `DAILY_QUOTA_EXCEEDED` | Token quota hit mid-stream | "Daily usage limit reached." |
| `AI_SERVICE_UNAVAILABLE` | OpenAI went down mid-stream | "AI service unavailable. Try again shortly." |

---

## 6. Rate Limits

| Endpoint | Limit | Window | Key |
|---|---|---|---|
| `POST /auth/register` | 5 requests | per hour | per IP address |
| `POST /auth/login` | 10 requests | per minute | per IP address |
| `POST /documents/upload` | 5 uploads | per minute | per user |
| `POST /query/ask` | 20 queries | per minute | per user |

When rate limited:
```
HTTP 429 Too Many Requests
Retry-After: <seconds>

{ "error": "RATE_LIMIT_EXCEEDED", "message": "..." }
```

---

## 7. Document Status Lifecycle

```
Upload -> PENDING -> PROCESSING -> READY    (can be queried)
                              -> FAILED    (error_message field populated)
```

| Status | `chunk_count` | `error_message` | Can query? |
|---|---|---|---|
| `PENDING` | `null` | `null` | No |
| `PROCESSING` | `null` | `null` | No |
| `READY` | Integer (e.g. `47`) | `null` | Yes |
| `FAILED` | `null` | Short error string | No |

**Common FAILED reasons** (in `error_message`):
- `"Extraction produced no chunks — document may be empty."`
- `"Document has 650,000 tokens; limit is 500,000. Split the document into smaller files."`
- Corrupt or encrypted PDF errors

When a document is `FAILED`, the user should be able to delete it and re-upload.

---

## 8. SSE Streaming Protocol

`POST /query/ask` returns `Content-Type: text/event-stream`. Every line is in SSE format:

```
data: <content>\n\n
```

### Token events (one per word/piece):
```
data: The\n\n
data:  total\n\n
data:  revenue\n\n
data:  in Q3 was $4.2M.\n\n
```

### Done event (clean end of stream):
```
data: [DONE]\n\n
```

### Error events (terminal — stream closes after this):
```
data: {"error": "STREAM_TIMEOUT", "message": "The response took too long..."}\n\n
data: {"error": "DAILY_QUOTA_EXCEEDED", "message": "..."}\n\n
data: {"error": "AI_SERVICE_UNAVAILABLE", "message": "..."}\n\n
data: {"error": "STREAM_ERROR", "message": "An unexpected error occurred..."}\n\n
```

**How to detect an error event:** check if the data starts with `{` (JSON) vs being plain text.

**Recommended client implementation:**
```js
async function streamAnswer(documentIds, question, accessToken, onToken, onDone, onError) {
  const res = await fetch('/query/ask', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${accessToken}`,
      'Accept': 'text/event-stream',
    },
    body: JSON.stringify({ document_ids: documentIds, question }),
    credentials: 'include',
  })

  // Pre-stream HTTP errors (404, 409, 429, 503, etc.)
  if (!res.ok) {
    const err = await res.json()
    onError(err)
    return
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n\n')
    buffer = lines.pop()  // keep incomplete last chunk

    for (const line of lines) {
      if (!line.startsWith('data: ')) continue
      const data = line.slice(6)  // strip "data: "

      if (data === '[DONE]') {
        onDone()
        return
      }
      if (data.startsWith('{')) {
        onError(JSON.parse(data))  // terminal SSE error
        return
      }
      onToken(data)  // append token to UI
    }
  }
}
```

> [!IMPORTANT]
> Always pass `credentials: 'include'` so the browser sends the httpOnly refresh cookie on `/auth/*` requests.

---

## 9. Password Rules

All passwords must satisfy **all** of the following (validate client-side before submitting):

| Rule | Requirement |
|---|---|
| Minimum length | 8 or more characters |
| Uppercase letter | At least one `A-Z` |
| Lowercase letter | At least one `a-z` |
| Number | At least one `0-9` |
| Special character | At least one of: `! @ # $ % ^ & * ( ) _ + - = [ ] { } ; ' : " \ | , . < > / ?` |

Show inline validation on the registration form — don't wait for the API to reject it.

**Example regex checks:**
```js
const rules = {
  minLength:   (p) => p.length >= 8,
  hasUpper:    (p) => /[A-Z]/.test(p),
  hasLower:    (p) => /[a-z]/.test(p),
  hasNumber:   (p) => /\d/.test(p),
  hasSpecial:  (p) => /[!@#$%^&*()_+\-=\[\]{};':"\\|,.<>\/?]/.test(p),
}
```

---

## 10. File Upload Rules

| Rule | Value |
|---|---|
| Max file size | **50 MB** |
| Allowed MIME types | `application/pdf`, `text/plain`, `text/markdown` |
| PDF validation | First 4 bytes must be `%PDF` (no renamed files) |
| Max documents per user | **20** (default, configurable) |
| Max tokens per document | **500,000** (~$0.01 at embedding cost) |

**Important distinction:**
- **File size and MIME** are checked synchronously at upload time (422 returned immediately).
- **Token limit (500k)** is checked during background processing — upload returns 202 but document ends up `FAILED` if the limit is exceeded.

**Allowed file extensions to show in the file picker:**
```
.pdf, .txt, .md
```

---

## 11. CORS Configuration

The backend only allows requests from `APP_URL` (the configured frontend origin).

```
Allowed Origins: [APP_URL]           e.g. "http://localhost:3000" in dev
Allowed Methods: GET, POST, DELETE
Allowed Headers: Authorization, Content-Type
Credentials:     true  (cookies allowed)
Max Age:         600 seconds (preflight cache)
```

No wildcard origins. Ensure your frontend dev server URL exactly matches `APP_URL` in the backend `.env.local`.

---

## 12. Frontend Flow Diagrams

### Registration and Verification Flow

```
User fills register form
  -> POST /auth/register
  <- 202 (always, even if email already exists)
  -> Show: "Check your inbox for a verification email"

User clicks email link -> browser navigates to GET /auth/verify-email?token=...
  -> Backend validates token
  <- 302 redirect to /login?verified=true          [success]
  <- 302 redirect to /verify-email?error=token_expired   [expired]
  <- 302 redirect to /verify-email?error=invalid_token   [tampered/used]

Frontend /login reads ?verified=true
  -> Show success toast: "Email verified! You can now log in."

Frontend /verify-email reads ?error=
  -> Show error message + "Resend verification email" button
  -> Resend button calls POST /auth/register again with same email
```

### Login and Session Lifecycle

```
App mounts
  -> POST /auth/refresh (cookie sent automatically)
  <- 200 { access_token, expires_in } -> session restored silently
  <- 401                              -> redirect to /login

User logs in:
  -> POST /auth/login { email, password }
  <- 200 { access_token, expires_in, user }
     -> store access_token in React state
     -> schedule refresh at (expires_in - 60) seconds
  <- 403 EMAIL_NOT_VERIFIED -> show "Resend verification" prompt
  <- 401 INVALID_CREDENTIALS -> show generic "Invalid email or password"
  <- 429 RATE_LIMIT_EXCEEDED -> show cooldown timer

Token refresh (silent, every ~14 min):
  -> POST /auth/refresh
  <- 200 { access_token } -> replace in state, reschedule
  <- 401                  -> session dead, redirect to /login

User logs out:
  -> POST /auth/logout
  <- 204 -> clear state, redirect to /login
```

### Document Upload and Polling Flow

```
User selects file
  -> POST /documents/upload (multipart/form-data)
  <- 202 { document_id, status: "PENDING" }
     -> start polling GET /documents/{document_id}/status
  <- 422 FILE_VALIDATION_FAILED { reason: "file_too_large" }
     -> show: "File must be under 50 MB"
  <- 422 FILE_VALIDATION_FAILED { reason: "unsupported_mime" }
     -> show: "Only PDF, TXT, and MD files are supported"
  <- 429 RATE_LIMIT_EXCEEDED
     -> show cooldown timer
  <- 503 queue unavailable
     -> show: "Upload queue is busy. Please try again shortly."

Polling GET /documents/{document_id}/status:
  <- status: "PENDING"     -> show "Queued..." spinner
  <- status: "PROCESSING"  -> show "Processing..." spinner
  <- status: "READY"       -> document available, enable for querying
  <- status: "FAILED"      -> show error_message, offer delete + re-upload
```

### Query / Chat Flow

```
User selects READY documents, types question
  -> POST /query/ask { document_ids, question }

Pre-stream validation errors (normal HTTP):
  <- 404 DOCUMENT_NOT_FOUND    -> "One or more documents not found"
  <- 409 DOCUMENT_NOT_READY    -> "Document is still processing. Please wait."
  <- 429 DAILY_QUERY_QUOTA_EXCEEDED -> "Daily query limit reached. Try tomorrow."
  <- 503 AI_SERVICE_UNAVAILABLE    -> "AI service unavailable. Try again shortly."

  <- 200 OK (SSE stream begins)
     -> show empty chat bubble, start appending tokens as they arrive
     -> on "data: [DONE]" -> mark complete, enable send button
     -> on "data: { error: ... }" -> show error in chat, stop streaming
        STREAM_TIMEOUT       -> "Response timed out. Please try again."
        DAILY_QUOTA_EXCEEDED -> "Daily usage limit reached."
        AI_SERVICE_UNAVAILABLE -> "AI service went down. Please try again."
        STREAM_ERROR         -> "Something went wrong. Please try again."
```
