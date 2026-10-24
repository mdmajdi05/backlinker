import * as React from "react";
import type { AuthTokens, User } from "@autobacklinker/shared-types";
import {
  api,
  apiClient,
  getSessionMode,
  onSessionModeChange,
  setApiBaseUrl,
  setApiToken,
  setLocalToken,
  setSessionMode,
  type SessionMode,
} from "./api";

export type AuthStatus = "loading" | "anonymous" | "authenticated";

export interface AuthContextValue {
  status: AuthStatus;
  user: User | null;
  token: string | null;
  mode: SessionMode;
  error: string | null;
  busy: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (name: string, email: string, password: string) => Promise<void>;
  logout: () => void;
  /** Use the machine token issued by the local backend sidecar. */
  useLocalSession: (token: string | null) => void;
  refreshUser: () => Promise<void>;
}

const AuthContext = React.createContext<AuthContextValue>({
  status: "loading",
  user: null,
  token: null,
  mode: "local",
  error: null,
  busy: false,
  login: async () => undefined,
  register: async () => undefined,
  logout: () => undefined,
  useLocalSession: () => undefined,
  refreshUser: async () => undefined,
});

function messageOf(error: unknown): string {
  if (error && typeof error === "object" && "message" in error) {
    return String((error as { message: unknown }).message);
  }
  return "Unexpected error";
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = React.useState<AuthStatus>("loading");
  const [user, setUser] = React.useState<User | null>(null);
  const [token, setToken] = React.useState<string | null>(apiClient.token);
  const [mode, setMode] = React.useState<SessionMode>(getSessionMode());
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  const refreshUser = React.useCallback(async () => {
    if (getSessionMode() !== "cloud") {
      // The local session is a machine session without a user account.
      setUser(null);
      setStatus("authenticated");
      return;
    }
    if (!apiClient.token) {
      setUser(null);
      setStatus("anonymous");
      return;
    }
    try {
      const me = await api.auth(apiClient).me();
      setUser(me);
      setStatus("authenticated");
      setError(null);
    } catch (err) {
      setUser(null);
      setStatus("anonymous");
      setError(messageOf(err));
    }
  }, []);

  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      // The desktop app is a local application: the local session needs no
      // account and no sign in - the sign in screen belongs to the optional
      // cloud connection.
      if (getSessionMode() !== "cloud") {
        if (!cancelled) {
          setUser(null);
          setStatus("authenticated");
        }
        return;
      }
      if (!apiClient.token) {
        if (!cancelled) setStatus("anonymous");
        return;
      }
      try {
        const me = await api.auth(apiClient).me();
        if (cancelled) return;
        setUser(me);
        setStatus("authenticated");
      } catch {
        if (cancelled) return;
        setUser(null);
        setStatus("anonymous");
        setApiToken(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // The transport decides where the client talks to - the UI follows.
  React.useEffect(() => {
    const handler = () => {
      const next = getSessionMode();
      setMode(next);
      setToken(apiClient.token);
      if (next === "local") {
        // The local session is a machine session, it is always available.
        setUser(null);
        setStatus("authenticated");
        setError(null);
        return;
      }
      // A hosted backend needs an account of its own.
      setUser(null);
      setStatus("anonymous");
      void refreshUser();
    };
    return onSessionModeChange(handler);
  }, [refreshUser]);

  React.useEffect(() => {
    const handler = () => {
      // The local machine session is not affected by a 401 of a single
      // endpoint - only a cloud session is invalidated.
      if (getSessionMode() !== "cloud") return;
      setToken(null);
      setUser(null);
      setStatus("anonymous");
    };
    window.addEventListener("autobacklinker:unauthorized", handler);
    return () =>
      window.removeEventListener("autobacklinker:unauthorized", handler);
  }, []);

  const login = React.useCallback(async (email: string, password: string) => {
    setBusy(true);
    setError(null);
    try {
      const result: AuthTokens = await api.auth(apiClient).login({
        email,
        password,
      });
      setApiToken(result.access_token);
      setToken(result.access_token);
      setLocalToken(null);
      setUser(result.user);
      // The mode follows the target: signing in against the local sidecar
      // keeps the local session, a hosted backend is the cloud mode.
      const next = getSessionMode();
      setMode(next);
      setSessionMode(next);
      setStatus("authenticated");
    } catch (err) {
      setError(messageOf(err));
      throw err;
    } finally {
      setBusy(false);
    }
  }, []);

  const register = React.useCallback(
    async (name: string, email: string, password: string) => {
      setBusy(true);
      setError(null);
      try {
        const result: AuthTokens = await api.auth(apiClient).register({
          name,
          email,
          password,
        });
        setApiToken(result.access_token);
        setToken(result.access_token);
        setLocalToken(null);
        setUser(result.user);
        const next = getSessionMode();
        setMode(next);
        setSessionMode(next);
        setStatus("authenticated");
      } catch (err) {
        setError(messageOf(err));
        throw err;
      } finally {
        setBusy(false);
      }
    },
    [],
  );

  const logout = React.useCallback(() => {
    // Signing out belongs to the cloud session: the local session is a
    // machine session of this computer and has no account to sign out of.
    if (getSessionMode() !== "cloud") return;
    // The credentials are cleared, the target stays: the sign in screen of a
    // hosted backend still talks to that backend.
    setApiToken(null);
    setLocalToken(null);
    setToken(null);
    setUser(null);
    setStatus("anonymous");
    setError(null);
  }, []);

  const useLocalSession = React.useCallback((localToken: string | null) => {
    if (!localToken) return;
    // A local session never overrides an explicit cloud login.
    if (getSessionMode() === "cloud") return;
    // The bundled backend expects the machine token in the
    // `X-Local-Token` header - not as a bearer token.
    setLocalToken(localToken);
    setMode("local");
    setUser(null);
    setStatus("authenticated");
    setError(null);
  }, []);

  const value = React.useMemo<AuthContextValue>(
    () => ({
      status,
      user,
      token,
      mode,
      error,
      busy,
      login,
      register,
      logout,
      useLocalSession,
      refreshUser,
    }),
    [
      status,
      user,
      token,
      mode,
      error,
      busy,
      login,
      register,
      logout,
      useLocalSession,
      refreshUser,
    ],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  return React.useContext(AuthContext);
}

/** Points the shared client at a different backend. */
export function useBackendUrl(url: string): void {
  React.useEffect(() => {
    setApiBaseUrl(url);
  }, [url]);
}
