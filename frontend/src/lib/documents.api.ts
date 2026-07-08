/**
 * documents.api.ts — Document endpoint wrappers
 *
 * Endpoints covered:
 *  POST   /documents/initiate-upload   — Phase 1: get presigned S3 PUT URL
 *  POST   /documents/confirm-upload    — Phase 3: confirm file landed in S3
 *  GET    /documents/{document_id}/status
 *  GET    /documents
 *  DELETE /documents/{document_id}
 *
 * Upload flow (replaces old multipart POST /documents/upload):
 *   1. initiateUpload(metadata)  → { document_id, upload_url, expires_in_seconds }
 *   2. uploadToS3WithProgress(upload_url, file, onProgress)  → S3 PUT (browser → S3 direct)
 *   3. confirmUpload(document_id) → { document_id, status: 'PENDING' }
 *
 * All of this is wrapped transparently in uploadDocument(file, onProgress) so
 * existing call sites don't change.
 */

import { apiRequest, apiFetch, ApiError, ERROR_CODES, ERROR_MESSAGES } from '@/lib/api';

// ---------------------------------------------------------------------------
// Shared types
// ---------------------------------------------------------------------------

export type DocumentStatus = 'PENDING_UPLOAD' | 'PENDING' | 'PROCESSING' | 'READY' | 'FAILED';

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

// ---------------------------------------------------------------------------
// Upload — Presigned URL flow (3 steps)
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

// --- Internal types for the presigned URL endpoints ---

interface InitiateUploadPayload {
  filename: string;
  file_size_bytes: number;
  mime_type: string;
}

interface InitiateUploadResponse {
  document_id: string;
  upload_url: string;       // Presigned S3 PUT URL — valid for 15 minutes
  s3_key: string;
  expires_in_seconds: number;
}

interface ConfirmUploadResponse {
  document_id: string;
  status: 'PENDING';
}

/**
 * Step 1 — POST /documents/initiate-upload
 *
 * Sends file metadata only (no bytes). Backend validates quota + MIME + size,
 * creates a PENDING_UPLOAD document row, and returns a presigned S3 PUT URL.
 *
 * Throws ApiError on:
 *   422  FILE_VALIDATION_FAILED — size or MIME type rejected
 *   429  RATE_LIMIT_EXCEEDED
 *   507  Quota exceeded
 */
async function initiateUpload(payload: InitiateUploadPayload): Promise<InitiateUploadResponse> {
  return apiRequest<InitiateUploadResponse>('/documents/initiate-upload', {
    method: 'POST',
    body: JSON.stringify(payload),
    headers: { 'Content-Type': 'application/json' },
  });
}

/**
 * Step 2 — PUT <presigned S3 URL>
 *
 * Uploads the file directly to S3 using XHR so we get real upload progress.
 * The `upload_url` is already signed — no Authorization header should be added.
 *
 * @param uploadUrl  Presigned S3 PUT URL from initiateUpload()
 * @param file       The File to upload
 * @param onProgress Called with percentage 0–100 as bytes are sent
 */
export function uploadToS3WithProgress(
  uploadUrl: string,
  file: File,
  onProgress?: (percent: number) => void,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();

    if (onProgress) {
      xhr.upload.addEventListener('progress', (evt) => {
        if (evt.lengthComputable) {
          onProgress(Math.round((evt.loaded / evt.total) * 100));
        }
      });
    }

    xhr.addEventListener('load', () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        onProgress?.(100);
        resolve();
      } else {
        // S3 error bodies are XML; extract the Code element if present
        const codeMatch = xhr.responseText.match(/<Code>([^<]+)<\/Code>/);
        const s3Code = codeMatch ? codeMatch[1] : 'S3Error';
        reject(
          new ApiError(
            s3Code,
            `S3 upload failed (HTTP ${xhr.status}). Please try again.`,
            xhr.status,
          ),
        );
      }
    });

    xhr.addEventListener('error', () =>
      reject(new ApiError('NETWORK_ERROR', 'Network error during upload. Please check your connection.', 0)),
    );
    xhr.addEventListener('abort', () =>
      reject(new ApiError('UPLOAD_ABORTED', 'Upload was cancelled.', 0)),
    );

    xhr.open('PUT', uploadUrl);
    // Content-Type must match what was passed to initiateUpload — S3 validates this.
    // Do NOT add an Authorization header: the URL is already signed.
    xhr.setRequestHeader('Content-Type', file.type);
    xhr.send(file);
  });
}

/**
 * Step 3 — POST /documents/confirm-upload
 *
 * Called after the S3 PUT completes. Backend runs HeadObject to verify the
 * file exists, transitions PENDING_UPLOAD → PENDING, and enqueues the ingest job.
 *
 * Throws ApiError on:
 *   404  Document not found (ownership check failed)
 *   409  File not yet in S3 (S3 PUT may have failed silently)
 *   502  Unexpected S3 error
 *   503  Queue unavailable
 */
async function confirmUpload(documentId: string): Promise<ConfirmUploadResponse> {
  return apiRequest<ConfirmUploadResponse>('/documents/confirm-upload', {
    method: 'POST',
    body: JSON.stringify({ document_id: documentId }),
    headers: { 'Content-Type': 'application/json' },
  });
}

/**
 * uploadDocument — Full 3-step presigned URL upload flow.
 *
 * Drop-in replacement for the old multipart uploadDocument(). The signature
 * is backward-compatible: the only addition is the optional `onProgress`
 * callback which receives 0–100 during the S3 PUT phase.
 *
 * The upload phase breakdown:
 *   1. initiateUpload  (~200ms) — API validates metadata, returns presigned URL
 *   2. S3 PUT          (bulk)   — file bytes go directly from browser to S3;
 *                                 onProgress fires throughout this phase
 *   3. confirmUpload   (~300ms) — API verifies S3 object, enqueues ingest job
 *
 * Throws:
 *   UploadApiError (code=FILE_VALIDATION_FAILED) — bad MIME or file too large
 *   ApiError (status=507)  — quota exceeded
 *   ApiError (status=409)  — S3 PUT succeeded but file not found in S3 on confirm
 *   ApiError (status=503)  — queue unavailable
 *   ApiError (NETWORK_ERROR) — network failure during S3 PUT
 */
export async function uploadDocument(
  file: File,
  onProgress?: (percent: number) => void,
): Promise<UploadResponse> {
  // --- Step 1: Initiate ---
  let initiated: InitiateUploadResponse;
  try {
    initiated = await initiateUpload({
      filename: file.name,
      file_size_bytes: file.size,
      mime_type: file.type || 'application/octet-stream',
    });
  } catch (err) {
    if (err instanceof ApiError && err.code === ERROR_CODES.FILE_VALIDATION_FAILED) {
      const details = err.details as { reason?: string } | undefined;
      throw new UploadApiError(err.code, err.message, err.status, err.retryAfter, details?.reason);
    }
    throw err;
  }

  // --- Step 2: S3 PUT (direct, with progress) ---
  await uploadToS3WithProgress(initiated.upload_url, file, onProgress);

  // --- Step 3: Confirm ---
  const confirmed = await confirmUpload(initiated.document_id);

  return {
    document_id: confirmed.document_id,
    status: 'PENDING',
  };
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

/**
 * GET /documents/{document_id}/download-url
 *
 * Fetches a presigned S3 GET URL to download the document.
 */
export async function getDocumentDownloadUrl(documentId: string): Promise<{ url: string }> {
  return apiRequest<{ url: string }>(`/documents/${documentId}/download-url`);
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
