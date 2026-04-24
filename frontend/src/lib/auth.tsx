"use client";

import { createContext, useContext, useEffect, useMemo, useState } from "react";

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

  // Restore session on mount: check localStorage first, then try refresh token
  useEffect(() => {
    const stored = localStorage.getItem("token");
    if (stored) {
      setTokenState(stored);
      setAuthHydrated(true);
    } else {
      // No token in localStorage, try to refresh using HTTP-only cookie
      refreshSession();
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

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
    // Call logout endpoint to revoke refresh token
    fetch("/api/v1/auth/logout", {
      method: "POST",
      credentials: "include",
    }).catch(() => {});
  };

  const refreshSession = async (): Promise<boolean> => {
    try {
      const response = await fetch("/api/v1/auth/refresh", {
        method: "POST",
        credentials: "include",
      });

      if (response.ok) {
        const data = await response.json();
        setToken(data.access_token);
        setAuthHydrated(true);
        return true;
      } else {
        setToken(null);
        setAuthHydrated(true);
        return false;
      }
    } catch {
      setToken(null);
      setAuthHydrated(true);
      return false;
    }
  };

  const value = useMemo(
    () => ({
      token,
      isAuthenticated: Boolean(token),
      authHydrated,
      setToken,
      logout,
      refreshSession,
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
