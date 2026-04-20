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

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [token, setTokenState] = useState<string | null>(null);
  const [authHydrated, setAuthHydrated] = useState(false);

  useEffect(() => {
    try {
      const stored = localStorage.getItem("token");
      if (stored) {
        setTokenState(stored);
      }
    } catch {
      // localStorage can throw (private mode, storage disabled, etc.); still unblock the shell.
    } finally {
      setAuthHydrated(true);
    }
  }, []);

  const setToken = (value: string | null) => {
    setTokenState(value);
    try {
      if (value) {
        localStorage.setItem("token", value);
      } else {
        localStorage.removeItem("token");
      }
    } catch {
      // Persistence is best-effort; session still works for the current tab.
    }
  };

  const logout = () => setToken(null);

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
