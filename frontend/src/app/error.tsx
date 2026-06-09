'use client';

import { useEffect } from 'react';
import { Button } from '@/components/ui';

export default function ErrorBoundary({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Optionally log the error to an error reporting service
    console.error('App Route Error:', error);
  }, [error]);

  return (
    <div className="flex min-h-[400px] flex-col items-center justify-center rounded-xl border border-[var(--error-200)] bg-[var(--error-50)] p-8 text-center m-6 shadow-sm">
      <div className="flex h-16 w-16 items-center justify-center rounded-full bg-[var(--error-100)] text-[var(--error-600)] mb-6">
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <circle cx="12" cy="12" r="10" />
          <line x1="12" y1="8" x2="12" y2="12" />
          <line x1="12" y1="16" x2="12.01" y2="16" />
        </svg>
      </div>
      <h2 className="text-xl font-bold tracking-tight text-[var(--gray-900)] mb-2">
        Something went wrong
      </h2>
      <p className="text-sm text-[var(--gray-600)] mb-6 max-w-md">
        An unexpected error occurred while rendering this page. We've been notified and are looking into it.
      </p>
      <div className="flex gap-4">
        <Button onClick={() => reset()}>
          Try again
        </Button>
        <Button variant="secondary" onClick={() => window.location.href = '/'}>
          Return home
        </Button>
      </div>
    </div>
  );
}
