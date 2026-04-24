"use client";

import { createContext, useContext, useEffect, useMemo, useState } from "react";

type AuthContextValue = {
  token: string | null;
  isAuthenticated: boolean;
  /** False until the client has read `token` from localStorage (avoids a bogus redirect to /login on hard navigation). */
  authHydrated: boolean;
  setToken: (token: string | null) => void;
  logout: () => void;
};

const AuthContext = createContext<AuthContextValue | null>(null);

// Refresh token 5 minutes before it expires (assuming 60 min expiry)
const REFRESH_MARGIN_MS = 5 * 60 * 1000;

function parseJwtPayload(token: string): Record<string, unknown> | null {
  try {
    const base64Url = token.split('.')[1];
    const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/');
    const json = decodeURIComponent(escape(atob(base64)));
    return JSON.parse(json) as Record<string, unknown>;
  } catch {
    return null;
  }
}

function getTokenExpiryMs(token: string): number | null {
  const payload = parseJwtPayload(token);
  if (!payload || typeof payload.exp !== "number") return null;
  // exp is in seconds, convert to ms
  return payload.exp * 1000;
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [token, setTokenState] = useState<string | null>(null);
  const [authHydrated, setAuthHydrated] = useState(false);

  // Restore session on mount
  useEffect(() => {
    const stored = localStorage.getItem("token");
    if (stored) {
      setTokenState(stored);
    }
    setAuthHydrated(true);
  }, []);

  // Periodic token refresh
  useEffect(() => {
    if (!token) return;
    
    const scheduleRefresh = () => {
      const expMs = getTokenExpiryMs(token);
      if (!expMs) return;
      
      const now = Date.now();
      const msUntilExpiry = expMs - now;
      const msUntilRefresh = msUntilExpiry - REFRESH_MARGIN_MS;
      
      if (msUntilRefresh <= 0) {
        // Token already expired or about to expire, try to refresh now
        refreshToken();
        return;
      }
      
      // Schedule refresh
      const timer = setTimeout(() => {
        refreshToken();
      }, msUntilRefresh);
      
      return () => clearTimeout(timer);
    };
    
    return scheduleRefresh();
  }, [token]);

  const refreshToken = async () => {
    try {
      const response = await fetch("/api/v1/auth/refresh", {
        method: "POST",
        credentials: "include",
      });
      
      if (response.ok) {
        const data = await response.json();
        const newToken = data.access_token;
        if (newToken) {
          localStorage.setItem("token", newToken);
          setTokenState(newToken);
        }
      }
    } catch {
      // Silently fail - the next API call will get 401 and redirect to login
    }
  };

  const setToken = (value: string | null) => {
    setTokenState(value);
    if (value) {
      localStorage.setItem("token", value);
    } else {
      localStorage.removeItem("token");
    }
  };

  const logout = () => {
    setToken(null);
    fetch("/api/v1/auth/logout", {
      method: "POST",
      credentials: "include",
    }).catch(() => {});
  };

  const value = useMemo(
    () => ({
      token,
      isAuthenticated: Boolean(token),
      authHydrated,
      setToken,
      logout
    }),
    [token, authHydrated]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return context;
}
