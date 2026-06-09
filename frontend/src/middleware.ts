import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

export function middleware(request: NextRequest) {
  // Add routes that don't require authentication here
  const publicRoutes = ['/login', '/register', '/verify-email'];
  const isPublicRoute = publicRoutes.some(route => request.nextUrl.pathname.startsWith(route));

  // A very basic check for refresh token presence;
  // Proper validation happens on the backend API or in Next.js Server Components.
  const hasRefreshToken = request.cookies.has('refresh_token');

  if (!hasRefreshToken && !isPublicRoute && !request.nextUrl.pathname.startsWith('/_next') && request.nextUrl.pathname !== '/') {
    return NextResponse.redirect(new URL('/login', request.url));
  }
  
  if (hasRefreshToken && isPublicRoute) {
    return NextResponse.redirect(new URL('/dashboard/documents', request.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    '/((?!api|_next/static|_next/image|favicon.ico).*)',
  ],
};
