/**
 * auth.api.ts — Auth endpoint wrappers
 *
 * Endpoints covered:
 *  POST /auth/register
 *  POST /auth/login
 *  POST /auth/refresh
 *  POST /auth/logout
 */

import { apiRequest, apiFetch } from '@/lib/api';

// ---------------------------------------------------------------------------
// Request / Response shapes
// ---------------------------------------------------------------------------

export interface RegisterRequest {
  email: string;
  password: string;
}

export interface RegisterResponse {
  message: string; // "Verification email sent"
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: 'bearer';
  expires_in: number; // seconds — always 900 (15 min)
  user: {
    id: string;
    email: string;
  };
}

export interface RefreshResponse {
  access_token: string;
  token_type: 'bearer';
  expires_in: number;
  // NOTE: No `user` field — see T-49 design decision in task.md
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

/**
 * POST /auth/register
 *
 * Always returns 202 regardless of whether the email already exists.
 * Re-calling with the same email re-sends the verification email if unverified.
 * This doubles as the "resend verification" mechanism — no separate endpoint needed.
 *
 * Throws ApiError on 422 (validation) or 429 (rate limit).
 */
export async function register(data: RegisterRequest): Promise<RegisterResponse> {
  return apiRequest<RegisterResponse>('/auth/register', {
    method: 'POST',
    body: JSON.stringify(data),
    skipAuth: true, // unauthenticated — no token needed or expected
  });
}

/**
 * POST /auth/login
 *
 * On success: returns access token + user in the body.
 * Also sets an httpOnly refresh_token cookie (path=/auth/refresh) automatically.
 *
 * Throws ApiError on:
 *   401 INVALID_CREDENTIALS
 *   403 EMAIL_NOT_VERIFIED
 *   429 RATE_LIMIT_EXCEEDED
 */
export async function login(data: LoginRequest): Promise<LoginResponse> {
  return apiRequest<LoginResponse>('/auth/login', {
    method: 'POST',
    body: JSON.stringify(data),
    skipAuth: true, // unauthenticated
  });
}

/**
 * POST /auth/refresh
 *
 * Silently exchanges the httpOnly refresh_token cookie for a new access token.
 * The cookie is rotated on every call (one-time-use).
 *
 * Called:
 *  1. On app mount to restore session (silent)
 *  2. By apiFetch() when it receives TOKEN_EXPIRED (silent, then retry)
 *  3. By the proactive refresh timer in AuthContext
 *
 * NOTE: Uses skipAuth=true AND rawResponse=false — this call itself must
 * not trigger the 401 retry loop or we get infinite recursion.
 *
 * Throws ApiError on 401 (cookie missing or expired) — caller should redirect to /login.
 */
export async function refreshToken(): Promise<RefreshResponse> {
  // We bypass apiFetch's auth-retry entirely — fetch directly with credentials.
  // This prevents infinite loops when the refresh itself returns 401.
  const baseUrl = process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, '') ?? '';
  const response = await fetch(`${baseUrl}/auth/refresh`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
  });

  if (!response.ok) {
    // Refresh 401 means session is dead — throw a simple error; AuthContext handles redirect
    const body = await response.json().catch(() => ({}));
    throw new Error(body?.message ?? 'Session expired');
  }

  return response.json() as Promise<RefreshResponse>;
}

/**
 * POST /auth/logout
 *
 * Revokes the refresh token server-side and clears the cookie.
 * Returns 204 No Content. Idempotent — safe to call even if already logged out.
 */
export async function logout(): Promise<void> {
  // Fire and forget — we clear local state regardless of whether this succeeds
  await apiFetch('/auth/logout', {
    method: 'POST',
    skipAuth: false, // send token if available so backend can associate the session
  }).catch(() => {
    // Best-effort: if the request fails (e.g. network error), we still clear local state
  });
}
