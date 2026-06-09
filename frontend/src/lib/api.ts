/**
 * api.ts — Core typed fetch wrapper for PDFTalk
 *
 * Responsibilities:
 *  - Attach Authorization header from in-memory token
 *  - Differentiated 401 handling (TOKEN_EXPIRED vs INVALID_TOKEN)
 *  - 5xx fallback for un-coded error responses (e.g. 502 S3 failure)
 *  - Expose Retry-After header on 429 via ApiError.retryAfter
 *  - Always send credentials: 'include' for httpOnly cookie on /auth/* paths
 */

import { env } from '@/env';

// ---------------------------------------------------------------------------
// ApiError — the single error type thrown by every function in this layer
// ---------------------------------------------------------------------------

export class ApiError extends Error {
  constructor(
    /** Screaming-snake error code from backend, or a synthetic one (see ERROR_CODES) */
    public readonly code: string,
    /** Human-readable message — safe to surface in a toast */
    public override readonly message: string,
    /** HTTP status code */
    public readonly status: number,
    /** Seconds from Retry-After header, present on 429 responses */
    public readonly retryAfter?: number,
  ) {
    super(message);
    this.name = 'ApiError';
    // Maintains proper prototype chain in transpiled ES5
    Object.setPrototypeOf(this, ApiError.prototype);
  }

  /** Returns true when caller should show a generic "retry later" message */
  get isRetryable(): boolean {
    return this.status === 429 || this.status >= 500;
  }
}

// ---------------------------------------------------------------------------
// Known error codes — kept here so all modules import from one place
// ---------------------------------------------------------------------------

export const ERROR_CODES = {
  // Auth
  INVALID_CREDENTIALS: 'INVALID_CREDENTIALS',
  EMAIL_NOT_VERIFIED: 'EMAIL_NOT_VERIFIED',
  TOKEN_EXPIRED: 'TOKEN_EXPIRED',
  INVALID_TOKEN: 'INVALID_TOKEN',
  ACCOUNT_INACTIVE: 'ACCOUNT_INACTIVE',
  // Rate / quota
  RATE_LIMIT_EXCEEDED: 'RATE_LIMIT_EXCEEDED',
  DAILY_QUOTA_EXCEEDED: 'DAILY_QUOTA_EXCEEDED',
  DAILY_QUERY_QUOTA_EXCEEDED: 'DAILY_QUERY_QUOTA_EXCEEDED',
  // Documents
  FILE_VALIDATION_FAILED: 'FILE_VALIDATION_FAILED',
  DOCUMENT_NOT_FOUND: 'DOCUMENT_NOT_FOUND',
  DOCUMENT_NOT_READY: 'DOCUMENT_NOT_READY',
  // AI
  AI_SERVICE_UNAVAILABLE: 'AI_SERVICE_UNAVAILABLE',
  // SSE-only
  STREAM_TIMEOUT: 'STREAM_TIMEOUT',
  STREAM_ERROR: 'STREAM_ERROR',
  // Synthetic — used when the backend returns a 5xx with no JSON error code
  UNKNOWN_5XX: 'UNKNOWN_5XX',
  // Synthetic — used for any other un-categorised error
  UNKNOWN: 'UNKNOWN',
} as const;

export type ErrorCode = (typeof ERROR_CODES)[keyof typeof ERROR_CODES];

// Human-readable messages keyed by error code.
// Components should use these instead of hard-coding strings.
export const ERROR_MESSAGES: Record<string, string> = {
  [ERROR_CODES.INVALID_CREDENTIALS]: 'Invalid email or password.',
  [ERROR_CODES.EMAIL_NOT_VERIFIED]: 'Your email address has not been verified yet.',
  [ERROR_CODES.TOKEN_EXPIRED]: 'Your session has expired. Please log in again.',
  [ERROR_CODES.INVALID_TOKEN]: 'Your session is invalid. Please log in again.',
  [ERROR_CODES.ACCOUNT_INACTIVE]: 'Your account has been deactivated. Contact support.',
  [ERROR_CODES.RATE_LIMIT_EXCEEDED]: 'Too many requests. Please wait before trying again.',
  [ERROR_CODES.DAILY_QUOTA_EXCEEDED]: 'Daily document limit reached. Try again tomorrow.',
  [ERROR_CODES.DAILY_QUERY_QUOTA_EXCEEDED]: 'Daily query limit reached. Try again tomorrow.',
  [ERROR_CODES.FILE_VALIDATION_FAILED]: 'The file you uploaded is invalid.',
  [ERROR_CODES.DOCUMENT_NOT_FOUND]: 'Document not found.',
  [ERROR_CODES.DOCUMENT_NOT_READY]: 'Document is still processing. Please wait.',
  [ERROR_CODES.AI_SERVICE_UNAVAILABLE]: 'AI service is temporarily unavailable. Try again shortly.',
  [ERROR_CODES.UNKNOWN_5XX]: 'Service error. Please try again.',
  [ERROR_CODES.UNKNOWN]: 'An unexpected error occurred. Please try again.',
};

// ---------------------------------------------------------------------------
// Internal types
// ---------------------------------------------------------------------------

/** Shape of all non-2xx JSON error bodies from the backend */
interface BackendErrorBody {
  error?: string;
  message?: string;
  detail?: unknown; // Pydantic 422 errors use this key
}

/** Callback injected by AuthContext so the core fetch layer can trigger a refresh */
export type RefreshTokenFn = () => Promise<string>;

/** Callback injected by AuthContext so the core fetch layer can force logout */
export type LogoutFn = () => void;

// ---------------------------------------------------------------------------
// Module-level callbacks — set once by AuthContext on mount
// ---------------------------------------------------------------------------

let _getAccessToken: (() => string | null) | null = null;
let _refreshToken: RefreshTokenFn | null = null;
let _logout: LogoutFn | null = null;

/**
 * Call this once from AuthContext to wire the token management callbacks
 * into the API layer. Must be called before any authenticated request.
 */
export function configureApiClient(config: {
  getAccessToken: () => string | null;
  refreshToken: RefreshTokenFn;
  logout: LogoutFn;
}): void {
  _getAccessToken = config.getAccessToken;
  _refreshToken = config.refreshToken;
  _logout = config.logout;
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

function buildUrl(path: string): string {
  const base = env.NEXT_PUBLIC_API_URL.replace(/\/$/, '');
  const normalised = path.startsWith('/') ? path : `/${path}`;
  return `${base}${normalised}`;
}

function parseRetryAfter(response: Response): number | undefined {
  const header = response.headers.get('Retry-After');
  if (!header) return undefined;
  const seconds = parseInt(header, 10);
  return isNaN(seconds) ? undefined : seconds;
}

async function parseErrorBody(response: Response): Promise<BackendErrorBody> {
  const contentType = response.headers.get('content-type') ?? '';
  if (!contentType.includes('application/json')) return {};
  try {
    return (await response.json()) as BackendErrorBody;
  } catch {
    return {};
  }
}

/**
 * Converts a non-2xx Response into a typed ApiError.
 * Handles all documented error codes + 502 fallback + 5xx fallback.
 */
async function toApiError(response: Response): Promise<ApiError> {
  const retryAfter = parseRetryAfter(response);
  const body = await parseErrorBody(response);
  const code = body.error ?? '';
  const serverMessage = body.message ?? '';

  // 502 with no error code body — S3 deletion failure and similar
  if (response.status === 502 && !code) {
    return new ApiError(
      ERROR_CODES.UNKNOWN_5XX,
      ERROR_MESSAGES[ERROR_CODES.UNKNOWN_5XX],
      502,
    );
  }

  // Any other 5xx with no recognised code
  if (response.status >= 500 && !code) {
    return new ApiError(
      ERROR_CODES.UNKNOWN_5XX,
      ERROR_MESSAGES[ERROR_CODES.UNKNOWN_5XX],
      response.status,
    );
  }

  // Named code from backend — use server message if we have no local copy
  const message = ERROR_MESSAGES[code] ?? serverMessage ?? ERROR_MESSAGES[ERROR_CODES.UNKNOWN];
  return new ApiError(code || ERROR_CODES.UNKNOWN, message, response.status, retryAfter);
}

// ---------------------------------------------------------------------------
// Core fetch wrapper
// ---------------------------------------------------------------------------

export interface FetchOptions extends Omit<RequestInit, 'headers'> {
  headers?: Record<string, string>;
  /** When true, the Authorization header is NOT attached (used for /auth/refresh itself) */
  skipAuth?: boolean;
  /** When true, the response is returned raw (used by query.api.ts for SSE) */
  rawResponse?: boolean;
}

/**
 * The single fetch wrapper every API module uses.
 * - Attaches auth token
 * - Handles 401 with differentiated TOKEN_EXPIRED vs INVALID_TOKEN logic
 * - On TOKEN_EXPIRED: calls refreshToken callback and retries once
 * - On INVALID_TOKEN / any other 401: calls logout callback immediately
 * - Throws ApiError on all non-2xx responses
 */
export async function apiFetch(path: string, options: FetchOptions = {}): Promise<Response> {
  const { skipAuth = false, rawResponse = false, headers = {}, ...rest } = options;

  const buildHeaders = (token: string | null): Record<string, string> => {
    const h: Record<string, string> = { 'Content-Type': 'application/json', ...headers };
    if (token && !skipAuth) {
      h['Authorization'] = `Bearer ${token}`;
    }
    // Remove Content-Type when body is FormData — browser sets it with boundary
    if (rest.body instanceof FormData) {
      delete h['Content-Type'];
    }
    return h;
  };

  const token = _getAccessToken?.() ?? null;
  const url = buildUrl(path);

  const response = await fetch(url, {
    ...rest,
    credentials: 'include', // always — needed for httpOnly refresh cookie on /auth/*
    headers: buildHeaders(token),
  });

  // Success path
  if (response.ok) return response;

  // -------------------------------------------------------------------------
  // 401 — Differentiated handling
  // -------------------------------------------------------------------------
  if (response.status === 401) {
    const body = await parseErrorBody(response);
    const errorCode = body.error ?? '';

    if (errorCode === ERROR_CODES.TOKEN_EXPIRED && _refreshToken) {
      // Silently refresh and retry the original request exactly once
      try {
        const newToken = await _refreshToken();
        const retryResponse = await fetch(url, {
          ...rest,
          credentials: 'include',
          headers: buildHeaders(newToken),
        });
        if (retryResponse.ok) return retryResponse;
        // Retry also failed — fall through to error
        throw await toApiError(retryResponse);
      } catch (err) {
        // Refresh itself returned 401 — session is dead
        if (err instanceof ApiError && err.status === 401) {
          _logout?.();
        }
        throw err;
      }
    }

    // INVALID_TOKEN or any other 401 — do not retry, force logout
    _logout?.();
    throw new ApiError(
      ERROR_CODES.INVALID_TOKEN,
      ERROR_MESSAGES[ERROR_CODES.INVALID_TOKEN],
      401,
    );
  }

  // -------------------------------------------------------------------------
  // All other error statuses
  // -------------------------------------------------------------------------
  throw await toApiError(response);
}

/**
 * Convenience wrapper for JSON responses.
 * Returns the parsed body typed as T.
 */
export async function apiRequest<T>(path: string, options: FetchOptions = {}): Promise<T> {
  const response = await apiFetch(path, options);
  // 204 No Content — nothing to parse
  if (response.status === 204) return undefined as unknown as T;
  return response.json() as Promise<T>;
}
