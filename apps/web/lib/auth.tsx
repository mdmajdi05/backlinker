"use client";

import * as React from "react";
import { api } from "@autobacklinker/api-client";
import type { LoginRequest, RegisterRequest, User } from "@autobacklinker/shared-types";
import { apiClient, setApiToken } from "./api";

const authApi = api.auth(apiClient);

interface AuthContextValue {
  user: User | null;
  token: string | null;
  loading: boolean;
  authenticated: boolean;
  /** True when the backend could not be reached at all (transport error). */
  offline: boolean;
  login: (payload: LoginRequest) => Promise<User>;
  register: (payload: RegisterRequest) => Promise<User>;
  logout: () => void;
  refresh: () => Promise<void>;
}

const AuthContext = React.createContext<AuthContextValue>({
  user: null,
  token: null,
  loading: true,
  authenticated: false,
  offline: false,
  login: async () => {
    throw new Error("not ready");
  },
  register: async () => {
    throw new Error("not ready");
  },
  logout: () => undefined,
  refresh: async () => undefined,
});

/** True for transport failures (the backend could not be reached at all). */
function isNetworkError(error: unknown): boolean {
  const status = (error as { status?: number } | null)?.status;
  return status === 0;
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = React.useState<User | null>(null);
  const [token, setToken] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [offline, setOffline] = React.useState(false);

  const loadUser = React.useCallback(async (activeToken: string | null) => {
    if (!activeToken) {
      setUser(null);
      setOffline(false);
      setLoading(false);
      return;
    }
    apiClient.setToken(activeToken);
    try {
      const me = await authApi.me();
      setUser(me);
      setOffline(false);
    } catch (err) {
      if (isNetworkError(err)) {
        // The backend is unreachable: keep the session so the workspace can
        // render its offline / error states instead of bouncing to the login.
        setOffline(true);
      } else {
        setApiToken(null);
        setUser(null);
        setOffline(false);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    let cancelled = false;
    const stored = window.localStorage.getItem("abk.token");
    setToken(stored);
    void (async () => {
      if (cancelled) return;
      await loadUser(stored);
    })();
    return () => {
      cancelled = true;
    };
  }, [loadUser]);

  const login = React.useCallback(
    async (payload: LoginRequest) => {
      const tokens = await authApi.login(payload);
      setApiToken(tokens.access_token);
      setToken(tokens.access_token);
      setUser(tokens.user);
      setLoading(false);
      return tokens.user;
    },
    [],
  );

  const register = React.useCallback(
    async (payload: RegisterRequest) => {
      const tokens = await authApi.register(payload);
      setApiToken(tokens.access_token);
      setToken(tokens.access_token);
      setUser(tokens.user);
      setLoading(false);
      return tokens.user;
    },
    [],
  );

  const logout = React.useCallback(() => {
    setApiToken(null);
    setToken(null);
    setUser(null);
    setOffline(false);
    window.location.assign("/login");
  }, []);

  const refresh = React.useCallback(async () => {
    setLoading(true);
    await loadUser(window.localStorage.getItem("abk.token"));
  }, [loadUser]);

  const value = React.useMemo<AuthContextValue>(
    () => ({
      user,
      token,
      loading,
      authenticated: Boolean(user) || (Boolean(token) && offline),
      offline,
      login,
      register,
      logout,
      refresh,
    }),
    [user, token, loading, offline, login, register, logout, refresh],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  return React.useContext(AuthContext);
}
