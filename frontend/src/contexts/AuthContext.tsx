'use client';

import React, { createContext, useContext, useEffect, useState, useRef, useCallback } from 'react';
import { useRouter, usePathname } from 'next/navigation';
import { refreshToken, logout as apiLogout } from '@/lib/auth.api';
import { configureApiClient } from '@/lib/api';
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
    sessionStorage.removeItem('pdftalk_user');
    if (typeof window !== 'undefined') {
      document.cookie = "pdftalk_logged_in=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT; SameSite=Strict";
    }
    if (refreshTimerRef.current) {
      clearTimeout(refreshTimerRef.current);
      refreshTimerRef.current = null;
    }
  }, []);

  const logout = useCallback(async () => {
    clearSession();
    await apiLogout();
    router.push('/auth/login');
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
        if (typeof window !== 'undefined') {
          document.cookie = "pdftalk_logged_in=true; path=/; max-age=604800; SameSite=Strict";
        }
        scheduleRefresh(data.expires_in);
      } catch (err) {
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
    if (typeof window !== 'undefined') {
      document.cookie = "pdftalk_logged_in=true; path=/; max-age=604800; SameSite=Strict";
    }
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
        const data = await refreshToken();
        if (!mounted) return;

        accessTokenRef.current = data.access_token;
        
        // Restore user from sessionStorage as per T-49 design decision
        const storedUser = sessionStorage.getItem('pdftalk_user');
        const user = storedUser ? JSON.parse(storedUser) : null;

        setState({ user, accessToken: data.access_token, isLoading: false });
        if (typeof window !== 'undefined') {
          document.cookie = "pdftalk_logged_in=true; path=/; max-age=604800; SameSite=Strict";
        }
        scheduleRefresh(data.expires_in);
        
      } catch (err) {
        clearSession();
        if (!mounted) return;
        
        // Only redirect to login if we're on a protected route
        const isPublicRoute = PUBLIC_ROUTES.some((route) => pathname?.startsWith(route));
        if (!isPublicRoute && pathname !== '/') {
          router.push('/auth/login');
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
      if (typeof window !== 'undefined') {
        document.cookie = "pdftalk_logged_in=true; path=/; max-age=604800; SameSite=Strict";
      }
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
