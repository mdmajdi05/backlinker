"use client";

import * as React from "react";
import { api } from "@autobacklinker/api-client";
import type { StorageStatus } from "@autobacklinker/shared-types";
import { apiClient } from "./api";

interface StorageContextValue {
  status: StorageStatus | null;
  error: unknown;
  loading: boolean;
  /** True when the backend answered and reports a healthy connection. */
  connected: boolean;
  refresh: () => void;
}

const StorageContext = React.createContext<StorageContextValue>({
  status: null,
  error: null,
  loading: true,
  connected: false,
  refresh: () => undefined,
});

const POLL_INTERVAL_MS = 30_000;

export function StorageProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = React.useState<StorageStatus | null>(null);
  const [error, setError] = React.useState<unknown>(null);
  const [loading, setLoading] = React.useState(true);

  const load = React.useCallback(async () => {
    setLoading(true);
    try {
      const next = await api.storage.status(apiClient);
      setStatus(next);
      setError(null);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    void load();
    const timer = window.setInterval(() => {
      void load();
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [load]);

  const value = React.useMemo<StorageContextValue>(
    () => ({
      status,
      error,
      loading,
      connected: Boolean(status?.connected) && !error,
      refresh: () => {
        void load();
      },
    }),
    [status, error, loading, load],
  );

  return <StorageContext.Provider value={value}>{children}</StorageContext.Provider>;
}

export function useStorage(): StorageContextValue {
  return React.useContext(StorageContext);
}
