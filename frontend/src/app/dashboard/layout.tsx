'use client';

import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useAuth } from '@/contexts/AuthContext';
import { Spinner } from '@/components/ui';

const NAV_ITEMS = [
  {
    href: '/dashboard/documents',
    label: 'My Documents',
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
        <polyline points="14 2 14 8 20 8" />
        <line x1="16" y1="13" x2="8" y2="13" />
        <line x1="16" y1="17" x2="8" y2="17" />
        <polyline points="10 9 9 9 8 9" />
      </svg>
    ),
  },
  {
    href: '/dashboard/upload',
    label: 'Upload',
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <polyline points="16 16 12 12 8 16" />
        <line x1="12" y1="12" x2="12" y2="21" />
        <path d="M20.39 18.39A5 5 0 0018 9h-1.26A8 8 0 103 16.3" />
      </svg>
    ),
  },
  {
    href: '/dashboard/chat',
    label: 'Chat',
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" />
      </svg>
    ),
  },
];

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const { user, isLoading, logout } = useAuth();
  const pathname = usePathname();
  const router = useRouter();

  // While session is restoring, or if unauthenticated (redirecting), show loader
  if (isLoading || !user) {
    return (
      <div className="flex min-h-screen items-center justify-center" style={{ background: 'var(--gray-50)' }}>
        <div className="flex flex-col items-center gap-3">
          <Spinner size={32} className="text-[var(--brand-500)]" />
          <p className="text-sm" style={{ color: 'var(--gray-500)' }}>Loading…</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen flex-col" style={{ background: 'var(--gray-50)' }}>
      {/* Top navigation bar */}
      <header
        className="sticky top-0 z-40 flex h-16 items-center border-b px-6"
        style={{
          background: 'white',
          borderColor: 'var(--gray-200)',
          boxShadow: 'var(--shadow-xs)',
        }}
      >
        {/* Brand */}
        <Link
          href="/dashboard/documents"
          className="flex items-center gap-2 text-lg font-bold tracking-tight mr-8"
          style={{ color: 'var(--brand-600)' }}
        >
          <svg width="26" height="26" viewBox="0 0 32 32" fill="none" aria-hidden="true">
            <rect width="32" height="32" rx="8" fill="var(--brand-500)" />
            <path d="M9 8h9l5 5v11a1 1 0 01-1 1H9a1 1 0 01-1-1V9a1 1 0 011-1z" fill="white" fillOpacity="0.9" />
            <path d="M18 8l5 5h-4a1 1 0 01-1-1V8z" fill="white" fillOpacity="0.5" />
            <path d="M12 17h8M12 20h5" stroke="var(--brand-500)" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
          PDFTalk
        </Link>

        {/* Nav items */}
        <nav className="flex items-center gap-1" aria-label="Main navigation">
          {NAV_ITEMS.map((item) => {
            const isActive = pathname?.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={[
                  'flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
                  isActive
                    ? 'bg-[var(--brand-50)] text-[var(--brand-700)]'
                    : 'text-[var(--gray-600)] hover:bg-[var(--gray-100)] hover:text-[var(--gray-900)]',
                ].join(' ')}
                aria-current={isActive ? 'page' : undefined}
              >
                {item.icon}
                {item.label}
              </Link>
            );
          })}
        </nav>

        {/* Right side: user + logout */}
        <div className="ml-auto flex items-center gap-3">
          {user && (
            <span className="text-sm" style={{ color: 'var(--gray-500)' }}>
              {user.email}
            </span>
          )}
          <button
            onClick={() => logout()}
            className="rounded-lg px-3 py-2 text-sm font-medium transition-colors text-[var(--gray-600)] hover:bg-[var(--gray-100)] hover:text-[var(--gray-900)]"
            id="logout-btn"
          >
            Sign out
          </button>
        </div>
      </header>

      {/* Page content */}
      <main className="flex-1 px-6 py-8 mx-auto w-full max-w-5xl">
        {children}
      </main>
    </div>
  );
}
