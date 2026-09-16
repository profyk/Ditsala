"use client";

import { createContext, useContext, useEffect, useState, type PropsWithChildren } from "react";

import { authApi } from "./admin-api";

interface AuthState {
  token: string | null;
  email: string | null;
  role: string | null;
}

interface AuthContextValue extends AuthState {
  isLoading: boolean;
  login: (token: string, email: string, role: string) => void;
  logout: () => Promise<void>;
}

const STORAGE_KEY = "ditsala_admin_session";
const EMPTY_STATE: AuthState = { token: null, email: null, role: null };

const AuthContext = createContext<AuthContextValue | null>(null);

/**
 * Persisted to localStorage rather than sessionStorage — an 8-hour admin
 * access token (see core/security.py's admin-token section) surviving a
 * tab close is a reasonable tradeoff for an internal tool; the token
 * itself still expires server-side regardless of client storage.
 */
export function AuthProvider({ children }: PropsWithChildren) {
  const [state, setState] = useState<AuthState>(EMPTY_STATE);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw) {
      try {
        setState(JSON.parse(raw) as AuthState);
      } catch {
        window.localStorage.removeItem(STORAGE_KEY);
      }
    }
    setIsLoading(false);
  }, []);

  function login(token: string, email: string, role: string): void {
    const next = { token, email, role };
    setState(next);
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  }

  async function logout(): Promise<void> {
    if (state.token) {
      await authApi.logout(state.token).catch(() => undefined);
    }
    setState(EMPTY_STATE);
    window.localStorage.removeItem(STORAGE_KEY);
  }

  return (
    <AuthContext.Provider value={{ ...state, isLoading, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}
