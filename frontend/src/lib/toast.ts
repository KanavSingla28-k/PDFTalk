'use client';

import { toast } from 'sonner';
import { ApiError, ERROR_CODES } from '@/lib/api';

/**
 * A wrapper around `sonner` toast that specifically handles `ApiError` instances.
 * Automatically maps standard error codes to user-friendly messages,
 * and handles HTTP 429 Retry-After cooldowns natively.
 */
export const apiToast = {
  /** Display a success message */
  success: (message: string) => toast.success(message),

  /** Display an error, automatically resolving ApiError codes */
  error: (err: unknown) => {
    if (err instanceof ApiError) {
      if (err.code === ERROR_CODES.RATE_LIMIT_EXCEEDED && err.retryAfter) {
        toast.error(`Too many requests. Try again in ${err.retryAfter} seconds.`);
        return;
      }
      
      // Special override for account inactive to make it more visible
      if (err.code === ERROR_CODES.ACCOUNT_INACTIVE) {
        toast.error(err.message, {
          duration: 10000,
          description: 'Please contact support to reactivate your account.',
        });
        return;
      }
      
      // Deduplicate auth errors so we don't spam the screen when multiple requests fail
      if (err.code === ERROR_CODES.INVALID_TOKEN || err.code === ERROR_CODES.TOKEN_EXPIRED) {
        toast.error(err.message, { id: 'auth-error' });
        return;
      }
      
      // Fallback 502 S3 deletion and standard 5xx errors are mapped automatically
      // inside `toApiError` -> `ERROR_MESSAGES[ERROR_CODES.UNKNOWN_5XX]`
      toast.error(err.message);
      return;
    }

    if (err instanceof Error) {
      toast.error(err.message);
      return;
    }

    if (typeof err === 'string') {
      toast.error(err);
      return;
    }

    toast.error('An unexpected error occurred. Please try again.');
  },

  /** Display an info message */
  info: (message: string) => toast.info(message),
};
