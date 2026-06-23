'use client';

import { Geist, Geist_Mono } from 'next/font/google';
import './globals.css';

const geistSans = Geist({ variable: '--font-geist-sans', subsets: ['latin'] });
const geistMono = Geist_Mono({ variable: '--font-geist-mono', subsets: ['latin'] });

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable} h-full`}>
      <body className="min-h-full flex items-center justify-center bg-[var(--gray-50)] p-6">
        <div className="flex w-full max-w-md flex-col items-center justify-center rounded-2xl border border-[var(--error-200)] bg-[var(--surface-card)] p-8 text-center shadow-lg">
          <div className="flex h-16 w-16 items-center justify-center rounded-full bg-[var(--error-100)] text-[var(--error-600)] mb-6">
            <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
              <line x1="12" y1="9" x2="12" y2="13" />
              <line x1="12" y1="17" x2="12.01" y2="17" />
            </svg>
          </div>
          <h2 className="text-xl font-bold tracking-tight text-[var(--gray-900)] mb-2">
            Critical Application Error
          </h2>
          <p className="text-sm text-[var(--gray-600)] mb-8">
            A fatal error occurred that prevents the application from loading. 
            We apologise for the inconvenience.
          </p>
          <div className="flex w-full flex-col gap-3">
            <button
              onClick={() => reset()}
              className="w-full rounded-xl bg-[var(--brand-500)] px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-[var(--brand-600)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--brand-500)]"
            >
              Reload application
            </button>
            <button
              onClick={() => window.location.href = '/'}
              className="w-full rounded-xl border border-[var(--gray-300)] bg-[var(--surface-card)] px-4 py-2.5 text-sm font-semibold text-[var(--gray-700)] transition-colors hover:bg-[var(--gray-50)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--brand-500)]"
            >
              Return to home
            </button>
          </div>
        </div>
      </body>
    </html>
  );
}
