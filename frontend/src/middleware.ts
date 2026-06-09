import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

// Routes that do NOT require authentication
const PUBLIC_ROUTES = ['/auth/login', '/auth/register', '/auth/verify-email'];

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  const isPublicRoute = PUBLIC_ROUTES.some((route) => pathname.startsWith(route));
  // Basic proxy signal: httpOnly refresh cookie presence means "probably logged in".
  // Real validation happens server-side / in AuthContext on the client.
  const hasRefreshToken = request.cookies.has('refresh_token');

  // Unauthenticated on a protected route → send to login
  if (!hasRefreshToken && !isPublicRoute && pathname !== '/') {
    const loginUrl = new URL('/auth/login', request.url);
    loginUrl.searchParams.set('next', pathname);
    return NextResponse.redirect(loginUrl);
  }

  // Authenticated trying to hit a public auth page → send to dashboard
  if (hasRefreshToken && isPublicRoute) {
    return NextResponse.redirect(new URL('/dashboard/documents', request.url));
  }

  // Root → redirect to login (or dashboard if authed — caught above)
  if (pathname === '/') {
    return NextResponse.redirect(new URL('/auth/login', request.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: ['/((?!api|_next/static|_next/image|favicon.ico).*)'],
};
