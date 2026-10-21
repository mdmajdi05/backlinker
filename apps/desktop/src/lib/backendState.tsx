import * as React from "react";
import {
  getAgentStatus,
  getBackendLogs,
  getBackendStatus,
  isTauri,
  restartBackend,
  startBackend,
  stopBackend,
  type AgentStatus,
  type BackendStatus,
} from "./backend";
import {
  setApiBaseUrl,
  ensureLocalAccount,
  getSessionMode,
  setTokenProvider,
} from "./api";
import { useAuth } from "./auth";

export interface BackendContextValue {
  status: BackendStatus | null;
  error: string | null;
  loading: boolean;
  native: boolean;
  logs: string[];
  agent: AgentStatus | null;
  refresh: () => Promise<void>;
  refreshLogs: () => Promise<void>;
  refreshAgent: () => Promise<void>;
  start: (port?: number) => Promise<void>;
  stop: () => Promise<void>;
  restart: () => Promise<void>;
}

const BackendContext = React.createContext<BackendContextValue>({
  status: null,
  error: null,
  loading: false,
  native: false,
  logs: [],
  agent: null,
  refresh: async () => undefined,
  refreshLogs: async () => undefined,
  refreshAgent: async () => undefined,
  start: async () => undefined,
  stop: async () => undefined,
  restart: async () => undefined,
});

const POLL_INTERVAL_MS = 4000;

/**
 * Supervises the local backend sidecar. The Rust side owns the process, this
 * provider only mirrors its state into React and keeps the API client pointed
 * at the right base URL.
 *
 * The client stays on the local sidecar: the base URL of the supervisor is
 * followed (the port can be changed), but a hosted backend is never selected
 * behind the back of the operator.
 */
export function BackendProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = React.useState<BackendStatus | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [logs, setLogs] = React.useState<string[]>([]);
  const [agent, setAgent] = React.useState<AgentStatus | null>(null);
  const { useLocalSession } = useAuth();
  const native = isTauri();

  const refresh = React.useCallback(async () => {
    if (!isTauri()) {
      setError(
        "The local backend is only managed by the desktop build (run `npm run tauri:dev`).",
      );
      // The browser preview still reaches the bundled backend over the
      // loopback interface - it only misses the supervisor.
      if (getSessionMode() === "local") void ensureLocalAccount();
      return;
    }
    try {
      const next = await getBackendStatus();
      setStatus(next);
      setError(null);
      if (next.localToken) {
        useLocalSession(next.localToken);
      }
      if (getSessionMode() === "local") {
        // The sidecar may run on another port - follow it.
        setApiBaseUrl(next.baseUrl);
        // The event stream of the backend authenticates with a JWT: make sure
        // the local account exists (and sign in with it).
        void ensureLocalAccount();
      }
    } catch (err) {
      setError(
        err && typeof err === "object" && "message" in err
          ? String((err as { message: unknown }).message)
          : "Cannot read the backend status",
      );
    }
  }, [useLocalSession]);

  // A request that was rejected with 401 refreshes the token once, so a
  // backend that was restarted in the meantime does not lock the user out.
  React.useEffect(() => {
    setTokenProvider(async () => {
      try {
        const next = await getBackendStatus();
        setStatus(next);
        if (next.localToken) {
          useLocalSession(next.localToken);
          if (getSessionMode() === "local") setApiBaseUrl(next.baseUrl);
        }
        return next.localToken ?? null;
      } catch {
        return null;
      }
    });
    return () => setTokenProvider(null);
  }, [useLocalSession]);

  const refreshLogs = React.useCallback(async () => {
    if (!isTauri()) return;
    try {
      const next = await getBackendLogs(200);
      // Keep the previous reference when nothing changed - the settings page
      // polls the log and a new array would trigger a re-render loop.
      setLogs((previous) =>
        previous.length === next.length &&
        previous.every((line, index) => line === next[index])
          ? previous
          : next,
      );
    } catch {
      /* log tail is best effort */
    }
  }, []);

  const refreshAgent = React.useCallback(async () => {
    if (!isTauri()) return;
    try {
      setAgent(await getAgentStatus());
    } catch {
      setAgent(null);
    }
  }, []);

  React.useEffect(() => {
    if (!native) return;
    void refresh();
    void refreshAgent();
    const timer = window.setInterval(() => {
      void refresh();
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [native, refresh, refreshAgent]);

  // The browser preview has no supervisor, but it still talks to the local
  // backend - make sure the local account exists there as well.
  React.useEffect(() => {
    if (native) return;
    const ensure = () => {
      if (getSessionMode() === "local") void ensureLocalAccount();
    };
    ensure();
    const timer = window.setInterval(ensure, POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [native]);

  const start = React.useCallback(
    async (port?: number) => {
      setLoading(true);
      try {
        const next = await startBackend(port ?? 0);
        setStatus(next);
        setError(null);
        if (next.localToken) {
          useLocalSession(next.localToken);
          if (getSessionMode() === "local") setApiBaseUrl(next.baseUrl);
        }
      } catch (err) {
        setError(
          err && typeof err === "object" && "message" in err
            ? String((err as { message: unknown }).message)
            : "Cannot start the backend",
        );
      } finally {
        setLoading(false);
      }
    },
    [useLocalSession],
  );

  const stop = React.useCallback(async () => {
    setLoading(true);
    try {
      setStatus(await stopBackend());
      setError(null);
    } catch (err) {
      setError(
        err && typeof err === "object" && "message" in err
          ? String((err as { message: unknown }).message)
          : "Cannot stop the backend",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  const restart = React.useCallback(async () => {
    setLoading(true);
    try {
      const next = await restartBackend();
      setStatus(next);
      setError(null);
      if (next.localToken) {
        useLocalSession(next.localToken);
        if (getSessionMode() === "local") setApiBaseUrl(next.baseUrl);
      }
    } catch (err) {
      setError(
        err && typeof err === "object" && "message" in err
          ? String((err as { message: unknown }).message)
          : "Cannot restart the backend",
      );
    } finally {
      setLoading(false);
    }
  }, [useLocalSession]);

  const value = React.useMemo<BackendContextValue>(
    () => ({
      status,
      error,
      loading,
      native,
      logs,
      agent,
      refresh,
      refreshLogs,
      refreshAgent,
      start,
      stop,
      restart,
    }),
    [
      status,
      error,
      loading,
      native,
      logs,
      agent,
      refresh,
      refreshLogs,
      refreshAgent,
      start,
      stop,
      restart,
    ],
  );

  return (
    <BackendContext.Provider value={value}>{children}</BackendContext.Provider>
  );
}

export function useBackend(): BackendContextValue {
  return React.useContext(BackendContext);
}
