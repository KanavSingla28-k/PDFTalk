import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

// Routes that do NOT require authentication
const PUBLIC_ROUTES_REGEX = /^\/auth\/(login|register|verify-email|forgot-password|reset-password)/;

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  const isPublicRoute = PUBLIC_ROUTES_REGEX.test(pathname);
  // Check for the presence of the refresh_token cookie directly.
  // Real validation happens server-side / in AuthContext on the client.
  const hasSession = request.cookies.has('refresh_token');

  // Unauthenticated on a protected route → send to login
  if (!hasSession && !isPublicRoute && pathname !== '/') {
    const loginUrl = new URL('/auth/login', request.url);
    loginUrl.searchParams.set('next', pathname);
    return NextResponse.redirect(loginUrl);
  }

  // Authenticated trying to hit a public auth page → send to dashboard
  if (hasSession && isPublicRoute) {
    const response = NextResponse.redirect(new URL('/dashboard/documents', request.url));
    // Clear legacy path="/auth" cookie that causes infinite redirect loops
    response.cookies.delete({
      name: 'refresh_token',
      path: '/auth',
    });
    return response;
  }

  // Root → redirect to login (or dashboard if authed)
  if (pathname === '/') {
    const target = hasSession ? '/dashboard/documents' : '/auth/login';
    const response = NextResponse.redirect(new URL(target, request.url));
    if (hasSession) {
      response.cookies.delete({ name: 'refresh_token', path: '/auth' });
    }
    return response;
  }

  const response = NextResponse.next();
  return response;
}

export const config = {
  matcher: ['/((?!api|_next/static|_next/image|favicon.ico).*)'],
};
