import type { Metadata } from 'next';
import Link from 'next/link';

export const metadata: Metadata = {
  title: { template: '%s — PDFTalk', default: 'PDFTalk' },
};

/**
 * Auth layout — shared shell for /auth/login, /auth/register, /auth/verify-email.
 * Renders a centred card on a subtle gradient background.
 */
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="flex min-h-screen flex-col items-center justify-center px-4 py-12"
      style={{ background: 'linear-gradient(135deg, #f0f4ff 0%, #fafafa 60%, #f0f4ff 100%)' }}
    >
      {/* Brand wordmark */}
      <Link
        href="/auth/login"
        className="mb-8 flex items-center gap-2 text-2xl font-bold tracking-tight"
        style={{ color: 'var(--brand-600)' }}
      >
        {/* Simple PDF icon */}
        <svg
          width="32"
          height="32"
          viewBox="0 0 32 32"
          fill="none"
          aria-hidden="true"
        >
          <rect width="32" height="32" rx="8" fill="var(--brand-500)" />
          <path
            d="M9 8h9l5 5v11a1 1 0 01-1 1H9a1 1 0 01-1-1V9a1 1 0 011-1z"
            fill="white"
            fillOpacity="0.9"
          />
          <path d="M18 8l5 5h-4a1 1 0 01-1-1V8z" fill="white" fillOpacity="0.5" />
          <path
            d="M12 17h8M12 20h5"
            stroke="var(--brand-500)"
            strokeWidth="1.5"
            strokeLinecap="round"
          />
        </svg>
        PDFTalk
      </Link>

      {/* Card */}
      <div
        className="w-full max-w-md rounded-2xl bg-white p-8 shadow-lg"
        style={{
          boxShadow: 'var(--shadow-xl)',
          border: '1px solid var(--gray-200)',
        }}
      >
        {children}
      </div>

      {/* Footer */}
      <p className="mt-8 text-sm" style={{ color: 'var(--gray-500)' }}>
        © {new Date().getFullYear()} PDFTalk. All rights reserved.
      </p>
    </div>
  );
}
