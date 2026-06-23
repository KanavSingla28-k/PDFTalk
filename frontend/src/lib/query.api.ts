/**
 * query.api.ts — Chat / Q&A streaming endpoint wrapper
 *
 * Endpoint: POST /query/ask
 *
 * This endpoint returns Server-Sent Events (SSE) over a fetch ReadableStream,
 * NOT a regular JSON response. EventSource cannot be used because it only
 * supports GET requests.
 *
 * SSE event types:
 *   data: {plain text token}   — append to chat bubble
 *   data: [DONE]               — stream ended cleanly
 *   data: {"error": "..."}     — terminal error mid-stream (JSON object)
 *   data: {"type":"fallback"}  — LLM used graceful redirect (show suggestion chips)
 */

import { apiFetch, ApiError, ERROR_CODES, ERROR_MESSAGES } from '@/lib/api';

// ---------------------------------------------------------------------------
// Request / Response types
// ---------------------------------------------------------------------------

export interface AskRequest {
  chat_id: string;
  question: string;
}

export type StreamEventType = 'token' | 'done' | 'error' | 'meta' | 'fallback';

export interface StreamToken {
  type: 'token';
  content: string;
}

export interface StreamDone {
  type: 'done';
}

export interface StreamError {
  type: 'error';
  code: string;
  message: string;
}

export interface StreamMeta {
  type: 'meta';
  missing_document_ids: string[];
}

/** Emitted when the LLM used its graceful Rule-5 fallback response. */
export interface StreamFallback {
  type: 'fallback';
}

export type StreamEvent = StreamToken | StreamDone | StreamError | StreamMeta | StreamFallback;

// ---------------------------------------------------------------------------
// SSE stream reader
// ---------------------------------------------------------------------------

/**
 * Streams the answer to a question from the given documents.
 *
 * Uses the buffer-accumulation pattern (mandatory — naive line splits break
 * when SSE events span multiple TCP chunks):
 *
 *   buffer += decoder.decode(chunk, { stream: true })
 *   split on '\n\n' → process each complete SSE frame
 *   keep the trailing incomplete fragment in the buffer
 *
 * @param request    The question and document IDs
 * @param onEvent    Called for every SSE event (token, done, or error)
 * @param signal     AbortSignal to cancel mid-stream (e.g. user clicks Stop)
 */
export async function streamAnswer(
  request: AskRequest,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  // -------------------------------------------------------------------------
  // 1. Open the connection — pre-stream HTTP errors are normal JSON responses
  // -------------------------------------------------------------------------
  let response: Response;
  try {
    response = await apiFetch('/query/ask', {
      method: 'POST',
      headers: {
        'Accept': 'text/event-stream',
      },
      body: JSON.stringify(request),
      rawResponse: true,
      signal,
    });
  } catch (err) {
    // ApiError from apiFetch (404, 409, 429, 503, auth errors, etc.)
    if (err instanceof ApiError) {
      onEvent({
        type: 'error',
        code: err.code,
        message: err.message,
      });
      return;
    }
    // AbortError — user cancelled, silently stop
    if (err instanceof DOMException && err.name === 'AbortError') return;
    // Unknown error
    onEvent({
      type: 'error',
      code: ERROR_CODES.UNKNOWN,
      message: ERROR_MESSAGES[ERROR_CODES.UNKNOWN],
    });
    return;
  }

  // -------------------------------------------------------------------------
  // 2. Read the SSE stream with the buffer-accumulation pattern
  // -------------------------------------------------------------------------
  if (!response.body) {
    onEvent({
      type: 'error',
      code: ERROR_CODES.UNKNOWN,
      message: 'Stream body is empty.',
    });
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  try {
    while (true) {
      // Respect external cancellation
      if (signal?.aborted) break;

      const { done, value } = await reader.read();
      if (done) break;

      // CRITICAL: { stream: true } tells TextDecoder not to flush the internal
      // state between chunks — required for multi-byte UTF-8 characters that
      // span chunk boundaries.
      buffer += decoder.decode(value, { stream: true });

      // Split on the SSE frame delimiter (\n\n).
      // The last element is always an incomplete frame — keep it in the buffer.
      const frames = buffer.split('\n\n');
      buffer = frames.pop() ?? ''; // keep trailing incomplete frame

      for (const frame of frames) {
        let dataStr = '';
        let eventName = 'message';
        
        const lines = frame.split('\n');
        for (const line of lines) {
            if (line.startsWith('event: ')) {
                eventName = line.slice(7).trim();
            } else if (line.startsWith('data: ')) {
                dataStr = line.slice(6);
            }
        }
        
        if (!dataStr) continue;

        if (eventName === 'meta') {
            try {
                const parsed = JSON.parse(dataStr);
                onEvent({ type: 'meta', missing_document_ids: parsed.missing_document_ids || [] });
            } catch (e) {}
            continue;
        }

        // Clean end of stream
        if (dataStr === '[DONE]') {
          onEvent({ type: 'done' });
          return;
        }

        // JSON payload (could be sources, terminal error, or token)
        if (dataStr.startsWith('{')) {
          try {
            const parsed = JSON.parse(dataStr) as { type?: string; error?: string; message?: string; content?: string };
            
            // Handle token events first
            if (parsed.type === 'token') {
              onEvent({ type: 'token', content: parsed.content || '' });
              continue;
            }
            
            // Backend signals LLM used its graceful fallback (Rule 5)
            if (parsed.type === 'fallback') {
              onEvent({ type: 'fallback' });
              continue;
            }

            // Backend sends source citations at the end of the stream
            if (parsed.type === 'sources') {
              // TODO: emit 'sources' event if UI needs to display citations
              continue;
            }

            const code = parsed.error ?? ERROR_CODES.UNKNOWN;
            
            if (code === ERROR_CODES.TOKEN_EXPIRED || code === ERROR_CODES.INVALID_TOKEN) {
              window.location.href = '/auth/login';
              return;
            }

            const message =
              parsed.message ??
              ERROR_MESSAGES[code] ??
              ERROR_MESSAGES[ERROR_CODES.UNKNOWN];
            onEvent({ type: 'error', code, message });
          } catch {
            onEvent({
              type: 'error',
              code: ERROR_CODES.STREAM_ERROR,
              message: ERROR_MESSAGES[ERROR_CODES.STREAM_ERROR],
            });
          }
          return; // Terminal — stream closes after an error event
        }

        // Fallback for plain text tokens (legacy format)
        onEvent({ type: 'token', content: dataStr });
      }
    }
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') return;
    onEvent({
      type: 'error',
      code: ERROR_CODES.STREAM_ERROR,
      message: ERROR_MESSAGES[ERROR_CODES.STREAM_ERROR],
    });
  } finally {
    reader.releaseLock();
  }
}

// ---------------------------------------------------------------------------
// SSE error code → user message mapping (in addition to ERROR_MESSAGES)
// ---------------------------------------------------------------------------

/** Maps SSE-specific terminal error codes to toast messages */
export const SSE_ERROR_MESSAGES: Record<string, string> = {
  [ERROR_CODES.STREAM_TIMEOUT]: 'Response timed out. Please try again.',
  [ERROR_CODES.STREAM_ERROR]: 'Something went wrong. Please try again.',
  [ERROR_CODES.DAILY_QUOTA_EXCEEDED]: 'Daily usage limit reached. Try again tomorrow.',
  [ERROR_CODES.AI_SERVICE_UNAVAILABLE]: 'AI service went down mid-response. Please try again.',
};

/**
 * Returns the most appropriate user-facing message for an SSE error event.
 * Falls back to the global ERROR_MESSAGES map, then to a generic fallback.
 */
export function getSseErrorMessage(code: string): string {
  return (
    SSE_ERROR_MESSAGES[code] ??
    ERROR_MESSAGES[code] ??
    ERROR_MESSAGES[ERROR_CODES.UNKNOWN]
  );
}
