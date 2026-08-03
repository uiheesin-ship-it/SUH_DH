"use client";
// Password login for the private app. The token (derived from the password by
// the backend) is kept in localStorage and sent as a Bearer header on every
// private call. No token → the login screen is shown instead of the app.
import { createContext, useCallback, useContext, useEffect, useState } from "react";

type AuthState = {
  token: string | null;
  ready: boolean;
  login: (password: string) => Promise<void>;
  logout: () => void;
};

const AuthCtx = createContext<AuthState | null>(null);
const KEY = "eai_token";

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    setToken(localStorage.getItem(KEY));
    setReady(true);
  }, []);

  const login = useCallback(async (password: string) => {
    const res = await fetch("/api/eai/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    });
    if (!res.ok) {
      const msg = res.status === 401 ? "비밀번호가 올바르지 않습니다." : `로그인 실패 (${res.status})`;
      throw new Error(msg);
    }
    const { token } = await res.json();
    localStorage.setItem(KEY, token);
    setToken(token);
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem(KEY);
    setToken(null);
  }, []);

  return <AuthCtx.Provider value={{ token, ready, login, logout }}>{children}</AuthCtx.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthCtx);
  if (!ctx) throw new Error("useAuth must be inside AuthProvider");
  return ctx;
}

// Authenticated fetch helper (adds Bearer, throws on non-OK).
export async function apiGet<T = any>(token: string | null, path: string): Promise<T> {
  const res = await fetch(path, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    cache: "no-store",
  });
  if (res.status === 401) throw new Error("로그인이 필요합니다.");
  if (!res.ok) throw new Error(`${path} → ${res.status}`);
  return res.json();
}
