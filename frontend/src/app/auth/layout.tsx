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
    <div className="flex min-h-screen bg-[var(--surface-bg)]">
      {/* Left Column: Form */}
      <div className="flex flex-1 flex-col justify-center px-4 py-12 sm:px-6 lg:flex-none lg:w-[480px] xl:w-[560px]">
        <div className="mx-auto w-full max-w-sm lg:w-96">
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

          {/* Form Content */}
          <div className="mt-8">
            {children}
          </div>

          {/* Footer */}
          <p className="mt-12 text-sm text-[var(--gray-500)] text-center lg:text-left">
            © {new Date().getFullYear()} PDFTalk. All rights reserved.
          </p>
        </div>
      </div>

      {/* Right Column: Illustration/Branding */}
      <div className="relative hidden w-0 flex-1 lg:block overflow-hidden bg-[var(--brand-50)]">
        <div className="absolute inset-0 h-full w-full object-cover">
          <svg className="absolute inset-0 h-full w-full" preserveAspectRatio="xMidYMid slice" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 1440 900">
            <g opacity="0.3">
              <path fill="var(--brand-200)" d="M-60 200c300-100 600 50 900-50s500-100 700 0v800H-60V200z" />
              <path fill="var(--brand-400)" opacity="0.4" d="M-60 400c400-150 700 100 1000 0s500-200 600 0v600H-60V400z" />
              <path fill="var(--brand-600)" opacity="0.2" d="M-60 600c500-200 800 150 1200 0s400-300 400-100v400H-60V600z" />
            </g>
          </svg>
        </div>
        <div className="absolute inset-0 flex flex-col justify-center px-16 lg:px-24 py-12 text-center lg:text-left">
          <h2 className="text-3xl lg:text-5xl font-bold tracking-tight text-[var(--gray-900)] max-w-2xl">
            Chat with your documents effortlessly.
          </h2>
          <p className="mt-6 text-lg text-[var(--gray-600)] max-w-xl">
            Upload your PDFs, Markdown files, or Text documents, and instantly extract insights, summaries, and answers using AI.
          </p>
          <div className="mt-12 grid grid-cols-2 gap-8 max-w-lg">
            <div className="bg-[var(--surface-card)]/60 backdrop-blur-md rounded-xl p-6 border border-white/50 shadow-sm">
              <div className="text-[var(--brand-600)] mb-3">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"></path><polyline points="13 2 13 9 20 9"></polyline></svg>
              </div>
              <h3 className="font-semibold text-[var(--gray-900)]">Instant Answers</h3>
              <p className="mt-1 text-sm text-[var(--gray-500)]">Extract specific information without reading the whole file.</p>
            </div>
            <div className="bg-[var(--surface-card)]/60 backdrop-blur-md rounded-xl p-6 border border-white/50 shadow-sm">
              <div className="text-[var(--brand-600)] mb-3">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"></circle><path d="M12 8v4"></path><path d="M12 16h.01"></path></svg>
              </div>
              <h3 className="font-semibold text-[var(--gray-900)]">Summarisation</h3>
              <p className="mt-1 text-sm text-[var(--gray-500)]">Get the gist of long documents in seconds.</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
