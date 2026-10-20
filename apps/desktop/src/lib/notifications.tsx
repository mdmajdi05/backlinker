import * as React from "react";
import { sendNativeNotification } from "./backend";
import { activityStream, type LiveEvent } from "./activity";

const NOTIFICATIONS_KEY = "autobacklinker.desktop.notifications";

export interface NotificationsContextValue {
  enabled: boolean;
  supported: boolean;
  setEnabled: (enabled: boolean) => void;
}

const NotificationsContext = React.createContext<NotificationsContextValue>({
  enabled: false,
  supported: false,
  setEnabled: () => undefined,
});

function readStored(): boolean {
  try {
    return window.localStorage.getItem(NOTIFICATIONS_KEY) === "true";
  } catch {
    return false;
  }
}

const NOTIFY_LEVELS = new Set(["WARNING", "ERROR", "SUCCESS"]);

/**
 * Native desktop notifications for important backend events. The toggle is
 * honoured per installation and the permission is requested lazily.
 */
export function NotificationsProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const [enabled, setEnabledState] = React.useState<boolean>(readStored);
  const supported =
    typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

  const setEnabled = React.useCallback((next: boolean) => {
    setEnabledState(next);
    try {
      window.localStorage.setItem(NOTIFICATIONS_KEY, String(next));
    } catch {
      /* ignore */
    }
  }, []);

  React.useEffect(() => {
    if (!enabled || !supported) return;

    const handler = (event: LiveEvent) => {
      const level = (event.level ?? "INFO").toUpperCase();
      if (!NOTIFY_LEVELS.has(level)) return;
      void sendNativeNotification(
        `Auto Backlinker · ${level.toLowerCase()}`,
        event.message ?? "Backend event",
      );
    };

    return activityStream.subscribe(handler);
  }, [enabled, supported]);

  const value = React.useMemo<NotificationsContextValue>(
    () => ({ enabled, supported, setEnabled }),
    [enabled, supported, setEnabled],
  );

  return (
    <NotificationsContext.Provider value={value}>
      {children}
    </NotificationsContext.Provider>
  );
}

export function useNotifications(): NotificationsContextValue {
  return React.useContext(NotificationsContext);
}
