import { api } from "./api";
import { apiClient } from "./api";

export interface LiveEvent {
  id?: string;
  event_type?: string;
  message?: string;
  level?: string;
  task_id?: string | null;
  project_id?: string | null;
  opportunity_id?: string | null;
  execution_environment?: string | null;
  metadata?: Record<string, unknown> | null;
  created_at?: string;
}

export type LiveEventListener = (event: LiveEvent) => void;

/**
 * A single shared Server-Sent Events subscription. The desktop app shows the
 * live feed on the overview page and reuses the same stream for native
 * notifications.
 */
class ActivityStream {
  private listeners = new Set<LiveEventListener>();
  private stop: (() => void) | null = null;
  private retryTimer: number | null = null;

  subscribe(listener: LiveEventListener): () => void {
    this.listeners.add(listener);
    this.ensureStarted();
    return () => {
      this.listeners.delete(listener);
      if (this.listeners.size === 0) this.stopStream();
    };
  }

  private ensureStarted(): void {
    if (this.stop) return;
    this.stop = api.dashboard.stream(apiClient, undefined, (payload) => {
      if (payload && typeof payload === "object") {
        this.emit(payload as LiveEvent);
      }
    });
  }

  private stopStream(): void {
    if (this.stop) {
      this.stop();
      this.stop = null;
    }
    if (this.retryTimer !== null) {
      window.clearTimeout(this.retryTimer);
      this.retryTimer = null;
    }
  }

  private emit(event: LiveEvent): void {
    this.listeners.forEach((listener) => {
      try {
        listener(event);
      } catch {
        /* a broken listener must not kill the stream */
      }
    });
  }
}

export const activityStream = new ActivityStream();
