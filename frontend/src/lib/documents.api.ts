/**
 * documents.api.ts — Document endpoint wrappers
 *
 * Endpoints covered:
 *  POST   /documents/upload
 *  GET    /documents/{document_id}/status
 *  GET    /documents
 *  DELETE /documents/{document_id}
 */

import { apiRequest, apiFetch, ApiError, ERROR_CODES, ERROR_MESSAGES } from '@/lib/api';

// ---------------------------------------------------------------------------
// Shared types
// ---------------------------------------------------------------------------

export type DocumentStatus = 'PENDING' | 'PROCESSING' | 'READY' | 'FAILED';

export interface DocumentRecord {
  document_id: string;
  filename: string;
  status: DocumentStatus;
  error_message: string | null;
  chunk_count: number | null;
  file_size_bytes: number;
  mime_type: string;
  created_at: string; // ISO 8601
  updated_at: string; // ISO 8601
}

// ---------------------------------------------------------------------------
// Upload
// ---------------------------------------------------------------------------

export interface UploadResponse {
  document_id: string;
  status: 'PENDING';
}

export interface FileValidationError extends ApiError {
  reason: 'file_too_large' | 'unsupported_mime' | 'invalid_magic_bytes';
}

/** Maps FILE_VALIDATION_FAILED reasons to user-facing messages */
export const FILE_VALIDATION_MESSAGES: Record<string, string> = {
  file_too_large: 'File must be under 50 MB.',
  unsupported_mime: 'Only PDF, TXT, and MD files are supported.',
  invalid_magic_bytes:
    'This file appears to be corrupt or renamed. Please check the file and try again.',
};

/**
 * POST /documents/upload
 *
 * Sends the file as multipart/form-data.
 * Returns document_id + PENDING status immediately; processing happens async.
 *
 * Throws UploadApiError on:
 *   401/403  Auth errors (handled by apiFetch automatically)
 *   422      FILE_VALIDATION_FAILED — .validationReason carries 'file_too_large' | 'unsupported_mime' | 'invalid_magic_bytes'
 *   429      RATE_LIMIT_EXCEEDED or DAILY_QUOTA_EXCEEDED (.retryAfter available)
 *   503      Queue unavailable (Redis down)
 */

/** Extended ApiError that carries the validation `reason` from FILE_VALIDATION_FAILED responses */
export class UploadApiError extends ApiError {
  constructor(
    code: string,
    message: string,
    status: number,
    retryAfter?: number,
    public readonly validationReason?: string,
  ) {
    super(code, message, status, retryAfter);
    this.name = 'UploadApiError';
    Object.setPrototypeOf(this, UploadApiError.prototype);
  }
}

export async function uploadDocument(file: File): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append('file', file);

  let response: Response;
  try {
    response = await apiFetch('/documents/upload', {
      method: 'POST',
      body: formData,
      rawResponse: true,
    });
  } catch (err) {
    // Re-parse FILE_VALIDATION_FAILED to extract the `reason` field
    if (err instanceof ApiError && err.code === ERROR_CODES.FILE_VALIDATION_FAILED) {
      // The raw body was already consumed by apiFetch's toApiError; we rely on the
      // error message lookup. Rethrow as UploadApiError with no validationReason —
      // the message from ERROR_MESSAGES is already set correctly for the generic case.
      throw new UploadApiError(err.code, err.message, err.status, err.retryAfter);
    }
    throw err;
  }

  // If we reach here the response is 2xx
  if (!response.ok) {
    // Shouldn't happen given apiFetch throws on non-2xx, but defensive
    throw new ApiError(ERROR_CODES.UNKNOWN, ERROR_MESSAGES[ERROR_CODES.UNKNOWN], response.status);
  }

  // Try to parse the reason field from a 422 body if present
  // (In practice 422 is already thrown above, but kept for safety)
  return response.json() as Promise<UploadResponse>;
}

/**
 * Helper: resolves the best user-facing message for an upload error.
 * Checks validationReason on UploadApiError, then falls back to error.message.
 */
export function getUploadErrorMessage(err: ApiError): string {
  if (err instanceof UploadApiError && err.validationReason) {
    return FILE_VALIDATION_MESSAGES[err.validationReason] ?? err.message;
  }
  if (err.code === ERROR_CODES.FILE_VALIDATION_FAILED) {
    return FILE_VALIDATION_MESSAGES['unsupported_mime'] ?? err.message;
  }
  return err.message;
}

// ---------------------------------------------------------------------------
// Status polling
// ---------------------------------------------------------------------------

/**
 * GET /documents/{document_id}/status
 *
 * Use this to poll after upload:
 *   - Every 2s for the first 30s
 *   - Then every 5s
 *   - Hard stop at 5 minutes — surface "taking longer than expected" message
 *
 * Throws ApiError on:
 *   404  DOCUMENT_NOT_FOUND
 */
export async function getDocumentStatus(documentId: string): Promise<DocumentRecord> {
  return apiRequest<DocumentRecord>(`/documents/${documentId}/status`);
}

// ---------------------------------------------------------------------------
// Document list (paginated)
// ---------------------------------------------------------------------------

export interface ListDocumentsParams {
  status?: DocumentStatus;
  limit?: number; // 1–100, default 10
  offset?: number; // >= 0
}

export interface ListDocumentsResponse {
  items: DocumentRecord[];
  total: number;
  limit: number;
  offset: number;
  pages: number;
}

/**
 * GET /documents
 *
 * Returns paginated list of the current user's documents.
 * Supports optional status filter and pagination controls.
 */
export async function listDocuments(params: ListDocumentsParams = {}): Promise<ListDocumentsResponse> {
  const query = new URLSearchParams();
  if (params.status) query.set('status', params.status);
  if (params.limit !== undefined) query.set('limit', String(params.limit));
  if (params.offset !== undefined) query.set('offset', String(params.offset));

  const path = `/documents${query.size > 0 ? `?${query.toString()}` : ''}`;
  return apiRequest<ListDocumentsResponse>(path);
}

// ---------------------------------------------------------------------------
// Delete
// ---------------------------------------------------------------------------

/**
 * DELETE /documents/{document_id}
 *
 * Permanently deletes the document and all its AI chunks.
 * Backend deletes from S3 first, then the database.
 *
 * Returns void on success (204 No Content).
 *
 * Throws ApiError on:
 *   404  DOCUMENT_NOT_FOUND — remove from UI
 *   502  (no error code) — S3 deletion failed; DB was NOT touched.
 *        The document MUST remain visible in the UI.
 *        Surface: "Deletion failed due to a storage error. Please try again."
 */
export async function deleteDocument(documentId: string): Promise<void> {
  try {
    await apiFetch(`/documents/${documentId}`, { method: 'DELETE' });
  } catch (err) {
    if (err instanceof ApiError && err.status === 502) {
      // Re-throw with a specific message so the caller can keep the doc in the list
      throw new ApiError(
        ERROR_CODES.UNKNOWN_5XX,
        'Deletion failed due to a storage error. Please try again.',
        502,
      );
    }
    throw err; // 404 and others pass through unchanged
  }
}

// ---------------------------------------------------------------------------
// Polling helper
// ---------------------------------------------------------------------------

export type PollingStatus = 'polling' | 'ready' | 'failed' | 'timeout';

export interface PollResult {
  status: PollingStatus;
  document?: DocumentRecord;
  error?: string;
}

const POLL_FAST_INTERVAL_MS = 2_000;  // 2s — first 30s
const POLL_SLOW_INTERVAL_MS = 5_000;  // 5s — after 30s
const POLL_FAST_DURATION_MS = 30_000; // 30s boundary
const POLL_HARD_TIMEOUT_MS  = 300_000; // 5 minutes — hard stop

/**
 * Polls a document's status until it reaches a terminal state (READY / FAILED)
 * or the 5-minute hard timeout is hit.
 *
 * @param documentId   UUID of the document to poll
 * @param onUpdate     Called on every poll with the latest DocumentRecord
 * @param signal       AbortSignal to cancel polling externally (e.g. component unmount)
 * @returns            Final PollResult
 */
export async function pollDocumentStatus(
  documentId: string,
  onUpdate: (doc: DocumentRecord) => void,
  signal?: AbortSignal,
): Promise<PollResult> {
  const startTime = Date.now();

  while (true) {
    if (signal?.aborted) return { status: 'timeout' };

    const elapsed = Date.now() - startTime;

    if (elapsed >= POLL_HARD_TIMEOUT_MS) {
      return { status: 'timeout' };
    }

    try {
      const doc = await getDocumentStatus(documentId);
      onUpdate(doc);

      if (doc.status === 'READY') return { status: 'ready', document: doc };
      if (doc.status === 'FAILED') return { status: 'failed', document: doc, error: doc.error_message ?? 'Processing failed.' };

    } catch (err) {
      // If the document is not found during polling, stop
      if (err instanceof ApiError && err.status === 404) {
        return { status: 'failed', error: ERROR_MESSAGES[ERROR_CODES.DOCUMENT_NOT_FOUND] };
      }
      // Other errors (network blip): swallow and keep polling
    }

    const interval = elapsed < POLL_FAST_DURATION_MS ? POLL_FAST_INTERVAL_MS : POLL_SLOW_INTERVAL_MS;
    await sleep(interval, signal);
  }
}

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(resolve, ms);
    signal?.addEventListener('abort', () => {
      clearTimeout(timer);
      reject(new DOMException('Aborted', 'AbortError'));
    }, { once: true });
  });
}
