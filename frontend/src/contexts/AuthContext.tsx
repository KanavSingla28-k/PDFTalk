'use client';

import React, { createContext, useContext, useEffect, useState, useRef, useCallback } from 'react';
import { useRouter, usePathname } from 'next/navigation';
import { refreshToken, logout as apiLogout } from '@/lib/auth.api';
import { configureApiClient } from '@/lib/api';
import { env } from '@/env';
import type { LoginResponse } from '@/lib/auth.api';

interface User {
  id: string;
  email: string;
}

interface AuthState {
  user: User | null;
  accessToken: string | null;
  isLoading: boolean;
}

interface AuthContextValue extends AuthState {
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

const PUBLIC_ROUTES = [
  '/auth/login',
  '/auth/register',
  '/auth/verify-email',
  '/auth/forgot-password',
  '/auth/reset-password',
  '/admin',
];

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();

  const [state, setState] = useState<AuthState>({
    user: null,
    accessToken: null,
    isLoading: true, // true on mount to wait for session restore
  });

  // Keep latest token in a ref so the API layer always gets the freshest one
  // without needing to re-configure the callback closure.
  const accessTokenRef = useRef<string | null>(null);
  
  // Keep track of the active refresh timer so we can clear it
  const refreshTimerRef = useRef<NodeJS.Timeout | null>(null);

  // ─── Helpers ────────────────────────────────────────────────────────────────

  const clearSession = useCallback(() => {
    setState({ user: null, accessToken: null, isLoading: false });
    accessTokenRef.current = null;
    if (refreshTimerRef.current) {
      clearTimeout(refreshTimerRef.current);
      refreshTimerRef.current = null;
    }
  }, []);

  const logout = useCallback(() => {
    clearSession();
    // Navigate immediately — don't wait for the revocation round-trip
    router.push('/auth/login');
    // Revoke server-side refresh token in the background (best-effort)
    apiLogout().catch(() => {
      // Ignore errors — local session is already cleared
    });
  }, [clearSession, router]);

  const scheduleRefresh = useCallback((expiresInSeconds: number) => {
    if (refreshTimerRef.current) {
      clearTimeout(refreshTimerRef.current);
    }
    // Refresh 60 seconds before expiration
    const timeoutMs = Math.max(0, (expiresInSeconds - 60) * 1000);
    
    refreshTimerRef.current = setTimeout(async () => {
      try {
        const data = await refreshToken();
        accessTokenRef.current = data.access_token;
        setState((prev) => ({ ...prev, accessToken: data.access_token }));
        scheduleRefresh(data.expires_in);
      } catch {
        // Silent refresh failed -> session dead
        clearSession();
        router.push('/auth/login');
      }
    }, timeoutMs);
  }, [clearSession, router]);

  const doRefreshFn = useCallback(async () => {
    // This is the callback given to the API layer to use when it encounters a 401
    const data = await refreshToken();
    accessTokenRef.current = data.access_token;
    setState((prev) => ({ ...prev, accessToken: data.access_token }));
    scheduleRefresh(data.expires_in);
    return data.access_token;
  }, [scheduleRefresh]);

  // ─── Setup API Layer ────────────────────────────────────────────────────────

  useEffect(() => {
    configureApiClient({
      getAccessToken: () => accessTokenRef.current,
      refreshToken: doRefreshFn,
      logout: logout,
    });
  }, [doRefreshFn, logout]);

  // ─── Session Restore on Mount ───────────────────────────────────────────────

  useEffect(() => {
    let mounted = true;

    async function restoreSession() {
      try {
        const res = await fetch(
          `${env.NEXT_PUBLIC_API_URL}/auth/me`,
          {
            credentials: 'include',
            headers: accessTokenRef.current
              ? { Authorization: `Bearer ${accessTokenRef.current}` }
              : {},
          }
        );

        if (!res.ok || res.status === 204) {
          throw new Error('Not authenticated');
        }

        const data = await res.json();

        if (!mounted) return;

        const user = {
          id: data.id,
          email: data.email,
        };

        accessTokenRef.current = data.access_token ?? null;

        setState({
          user,
          accessToken: data.access_token ?? null,
          isLoading: false,
        });

        if (data.expires_in) {
          scheduleRefresh(data.expires_in);
        }
      } catch {
        clearSession();

        if (!mounted) return;

        const isPublicRoute = PUBLIC_ROUTES.some((route) =>
          pathname?.startsWith(route)
        );

        if (!isPublicRoute && pathname !== '/') {
          router.replace('/auth/login');
        }
      }
    }

    restoreSession();

    return () => {
      mounted = false;
      if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current);
    };
    // We intentionally only run this once on mount
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ─── Listen for Login Events ────────────────────────────────────────────────

  useEffect(() => {
    const handleLoginEvent = (event: Event) => {
      const customEvent = event as CustomEvent<LoginResponse>;
      const { access_token, expires_in, user } = customEvent.detail;

      accessTokenRef.current = access_token;
      setState({ user, accessToken: access_token, isLoading: false });
      scheduleRefresh(expires_in);
    };

    window.addEventListener('pdftalk:login', handleLoginEvent);
    return () => window.removeEventListener('pdftalk:login', handleLoginEvent);
  }, [scheduleRefresh]);

  // ─── Render ─────────────────────────────────────────────────────────────────

  return (
    <AuthContext.Provider value={{ ...state, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
