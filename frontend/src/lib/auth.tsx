"use client";

import { createContext, useContext, useEffect, useMemo, useState, useCallback } from "react";

type AuthContextValue = {
  token: string | null;
  isAuthenticated: boolean;
  /** False until the client has tried to restore the session. */
  authHydrated: boolean;
  setToken: (token: string | null) => void;
  logout: () => void;
  refreshSession: () => Promise<boolean>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [token, setTokenState] = useState<string | null>(null);
  const [authHydrated, setAuthHydrated] = useState(false);

  // Sync token with api.ts module
  const syncToken = useCallback((newToken: string | null) => {
    setTokenState(newToken);
    setApiAccessToken(newToken);
  }, []);

  // Expose token setter globally for api.ts refresh logic
  useEffect(() => {
    if (typeof window !== "undefined") {
      (window as any).__setAuthToken = syncToken;
    }
    return () => {
      if (typeof window !== "undefined") {
        delete (window as any).__setAuthToken;
      }
    };
  }, [syncToken]);

  // Restore session on mount by trying to refresh with HTTP-only cookie
  useEffect(() => {
    refreshSession();
  }, []);

  const setToken = (value: string | null) => {
    syncToken(value);
  };

  const logout = useCallback(async () => {
    syncToken(null);
    try {
      await fetch("/api/v1/auth/logout", {
        method: "POST",
        credentials: "include", // Include cookies
      });
    } catch {
      // Ignore errors on logout
    }
    // Clear any stale data
    if (typeof window !== "undefined") {
      localStorage.removeItem("token"); // Clean up old tokens if any
    }
  }, [syncToken]);

  const refreshSession = useCallback(async (): Promise<boolean> => {
    try {
      const response = await fetch("/api/v1/auth/refresh", {
        method: "POST",
        credentials: "include", // Include HTTP-only cookie
      });

      if (response.ok) {
        const data = await response.json();
        syncToken(data.access_token);
        setAuthHydrated(true);
        return true;
      } else {
        // Refresh failed - user needs to log in again
        syncToken(null);
        setAuthHydrated(true);
        return false;
      }
    } catch {
      syncToken(null);
      setAuthHydrated(true);
      return false;
    }
  }, [syncToken]);

  const value = useMemo(
    () => ({
      token,
      isAuthenticated: Boolean(token),
      authHydrated,
      setToken,
      logout,
      refreshSession,
    }),
    [token, authHydrated, logout, refreshSession]
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
