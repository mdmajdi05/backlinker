/**
 * Typed API client shared by the web app and the Tauri desktop app.
 *
 * Both clients talk to the exact same FastAPI backend, therefore all data
 * lives on the server and the clients are thin, stateless views. The desktop
 * app additionally spawns a local backend sidecar, but still speaks the same
 * protocol (baseUrl differs).
 */

import type {
  ActivityEvent,
  Adapter,
  AuthTokens,
  BacklinkRecord,
  BusinessProfile,
  BulkActionRequest,
  DashboardMetrics,
  Device,
  DiscoveryRequest,
  DiscoveryRun,
  ExportJob,
  ImportCommitRequest,
  ImportJob,
  ImportPreview,
  LoginRequest,
  Opportunity,
  OpportunityUpdate,
  Paginated,
  PageParams,
  Project,
  ProjectCreate,
  ProjectSettings,
  QueueCreateRequest,
  RegisterRequest,
  StorageConnectionRequest,
  StorageMigrationPreview,
  StorageStatus,
  Task,
  TaskAttempt,
  TaskControlRequest,
  TaskEvent,
  User,
  VerificationRun,
} from "@autobacklinker/shared-types";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details?: unknown;
  readonly requestId?: string;

  constructor(
    status: number,
    code: string,
    message: string,
    details?: unknown,
    requestId?: string,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
    this.requestId = requestId;
  }
}

export interface ClientOptions {
  baseUrl?: string;
  token?: string | null;
  onUnauthorized?: () => void;
  fetchImpl?: typeof fetch;
}

type Query = Record<string, string | number | boolean | undefined | null>;

function buildQuery(params?: Query): string {
  if (!params) return "";
  const usp = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v === undefined || v === null || v === "") return;
    usp.append(k, String(v));
  });
  const s = usp.toString();
  return s ? `?${s}` : "";
}

export class ApiClient {
  baseUrl: string;
  token: string | null;
  onUnauthorized?: () => void;
  private fetchImpl: typeof fetch;

  constructor(options: ClientOptions = {}) {
    this.baseUrl = (options.baseUrl ?? "").replace(/\/$/, "");
    this.token = options.token ?? null;
    this.onUnauthorized = options.onUnauthorized;
    this.fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis);
  }

  setToken(token: string | null) {
    this.token = token;
  }

  setBaseUrl(url: string) {
    this.baseUrl = url.replace(/\/$/, "");
  }

  private headers(extra?: HeadersInit): HeadersInit {
    const h: Record<string, string> = { "Content-Type": "application/json" };
    if (this.token) h.Authorization = `Bearer ${this.token}`;
    return { ...h, ...(extra as Record<string, string>) };
  }

  async request<T>(
    path: string,
    init: RequestInit & { query?: Query } = {},
  ): Promise<T> {
    const { query, ...rest } = init;
    const url = `${this.baseUrl}${path}${buildQuery(query)}`;
    let response: Response;
    try {
      response = await this.fetchImpl(url, {
        ...rest,
        headers: this.headers(rest.headers),
      });
    } catch (err) {
      throw new ApiError(
        0,
        "network_error",
        `Cannot reach the backend at ${this.baseUrl}. Is it running?`,
        err,
      );
    }

    if (response.status === 204) return undefined as T;

    const contentType = response.headers.get("content-type") ?? "";
    const payload = contentType.includes("application/json")
      ? await response.json()
      : await response.text();

    if (!response.ok) {
      const body = payload as { error?: { code: string; message: string; details?: unknown; request_id?: string } };
      if (response.status === 401) this.onUnauthorized?.();
      throw new ApiError(
        response.status,
        body?.error?.code ?? "http_error",
        body?.error?.message ?? `Request failed with status ${response.status}`,
        body?.error?.details,
        body?.error?.request_id,
      );
    }
    return payload as T;
  }

  get<T>(path: string, query?: Query) {
    return this.request<T>(path, { method: "GET", query });
  }

  post<T>(path: string, body?: unknown) {
    return this.request<T>(path, {
      method: "POST",
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  }

  put<T>(path: string, body?: unknown) {
    return this.request<T>(path, {
      method: "PUT",
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  }

  patch<T>(path: string, body?: unknown) {
    return this.request<T>(path, {
      method: "PATCH",
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  }

  delete<T>(path: string) {
    return this.request<T>(path, { method: "DELETE" });
  }

  async upload<T>(path: string, file: File, fields: Record<string, string> = {}) {
    const form = new FormData();
    Object.entries(fields).forEach(([k, v]) => form.append(k, v));
    form.append("file", file);
    const response = await this.fetchImpl(`${this.baseUrl}${path}`, {
      method: "POST",
      headers: this.token ? { Authorization: `Bearer ${this.token}` } : undefined,
      body: form,
    });
    if (!response.ok) {
      const body = await response.text();
      throw new ApiError(response.status, "upload_failed", body || "Upload failed");
    }
    const contentType = response.headers.get("content-type") ?? "";
    return (contentType.includes("application/json")
      ? await response.json()
      : await response.text()) as T;
  }

  /** Downloads a binary artifact (xlsx/csv) and triggers a browser save. */
  async download(path: string, filename: string, query?: Query) {
    const response = await this.fetchImpl(`${this.baseUrl}${path}${buildQuery(query)}`, {
      headers: this.token ? { Authorization: `Bearer ${this.token}` } : undefined,
    });
    if (!response.ok) {
      throw new ApiError(response.status, "download_failed", "Download failed");
    }
    const blob = await response.blob();
    if (typeof document !== "undefined") {
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    }
    return blob;
  }

  /**
   * Server-Sent Events subscription. Falls back to polling when the browser
   * does not support EventSource (not the case in modern browsers, but the
   * Tauri webview on some platforms has quirks).
   */
  subscribe(
    path: string,
    onMessage: (event: unknown, type: string) => void,
    onError?: (err: unknown) => void,
  ): () => void {
    if (typeof EventSource === "undefined") {
      return () => undefined;
    }
    const url = `${this.baseUrl}${path}`;
    const es = new EventSource(url, {
      withCredentials: false,
    } as EventSourceInit);
    es.onmessage = (e) => {
      try {
        onMessage(JSON.parse(e.data), e.type);
      } catch {
        onMessage(e.data, e.type);
      }
    };
    es.onerror = (e) => onError?.(e);
    return () => es.close();
  }
}

/* ------------------------------------------------------------------ */
/* Endpoint helpers (typed, shared by web + desktop)                    */
/* ------------------------------------------------------------------ */

export interface AuthApi {
  login: (payload: LoginRequest) => Promise<AuthTokens>;
  register: (payload: RegisterRequest) => Promise<AuthTokens>;
  me: () => Promise<User>;
}

export const createAuthApi = (client: ApiClient): AuthApi => ({
  login: (payload) => client.post<AuthTokens>("/api/v1/auth/login", payload),
  register: (payload) => client.post<AuthTokens>("/api/v1/auth/register", payload),
  me: () => client.get<User>("/api/v1/auth/me"),
});

export const api = {
  auth: createAuthApi,

  profiles: {
    list: (c: ApiClient) => c.get<BusinessProfile[]>("/api/v1/profiles"),
    get: (c: ApiClient, id: string) => c.get<BusinessProfile>(`/api/v1/profiles/${id}`),
    create: (c: ApiClient, body: Partial<BusinessProfile>) =>
      c.post<BusinessProfile>("/api/v1/profiles", body),
    update: (c: ApiClient, id: string, body: Partial<BusinessProfile>) =>
      c.put<BusinessProfile>(`/api/v1/profiles/${id}`, body),
    remove: (c: ApiClient, id: string) => c.delete<void>(`/api/v1/profiles/${id}`),
  },

  projects: {
    list: (c: ApiClient, q?: PageParams) =>
      c.get<Paginated<Project>>("/api/v1/projects", { ...q }),
    get: (c: ApiClient, id: string) => c.get<Project>(`/api/v1/projects/${id}`),
    create: (c: ApiClient, body: ProjectCreate) =>
      c.post<Project>("/api/v1/projects", body),
    update: (c: ApiClient, id: string, body: Partial<Project>) =>
      c.patch<Project>(`/api/v1/projects/${id}`, body),
    remove: (c: ApiClient, id: string) => c.delete<void>(`/api/v1/projects/${id}`),
    settings: (c: ApiClient, id: string) =>
      c.get<ProjectSettings>(`/api/v1/projects/${id}/settings`),
    updateSettings: (c: ApiClient, id: string, body: Partial<ProjectSettings>) =>
      c.put<ProjectSettings>(`/api/v1/projects/${id}/settings`, body),
  },

  opportunities: {
    list: (c: ApiClient, q?: Query) =>
      c.get<Paginated<Opportunity>>("/api/v1/opportunities", { ...q }),
    get: (c: ApiClient, id: string) =>
      c.get<Opportunity>(`/api/v1/opportunities/${id}`),
    update: (c: ApiClient, id: string, body: OpportunityUpdate) =>
      c.patch<Opportunity>(`/api/v1/opportunities/${id}`, body),
    bulk: (c: ApiClient, body: BulkActionRequest) =>
      c.post<{ affected: number }>("/api/v1/opportunities/bulk", body),
    excludeDomain: (c: ApiClient, domain: string, body: { until?: string; reason?: string }) =>
      c.post<void>("/api/v1/registry/exclusions", { domain, ...body }),
  },

  discovery: {
    run: (c: ApiClient, body: DiscoveryRequest) =>
      c.post<DiscoveryRun>("/api/v1/discovery/runs", body),
    list: (c: ApiClient, q?: Query) =>
      c.get<Paginated<DiscoveryRun>>("/api/v1/discovery/runs", { ...q }),
    providers: (c: ApiClient) =>
      c.get<Array<{ key: string; name: string; requires_credentials: boolean; categories: string[] }>>(
        "/api/v1/discovery/providers",
      ),
  },

  queue: {
    list: (c: ApiClient, q?: Query) => c.get<Paginated<Task>>("/api/v1/queue", { ...q }),
    create: (c: ApiClient, body: QueueCreateRequest) =>
      c.post<{ created: number; task_ids: string[] }>("/api/v1/queue", body),
    reorder: (c: ApiClient, body: { task_ids: string[] }) =>
      c.post<void>("/api/v1/queue/reorder", body),
    control: (c: ApiClient, id: string, body: TaskControlRequest) =>
      c.post<Task>(`/api/v1/queue/${id}/control`, body),
    bulkControl: (c: ApiClient, body: TaskControlRequest & { task_ids: string[] }) =>
      c.post<{ affected: number }>("/api/v1/queue/bulk-control", body),
    stats: (c: ApiClient) => c.get<Record<string, number>>("/api/v1/queue/stats"),
  },

  tasks: {
    get: (c: ApiClient, id: string) => c.get<Task>(`/api/v1/tasks/${id}`),
    attempts: (c: ApiClient, id: string) =>
      c.get<TaskAttempt[]>(`/api/v1/tasks/${id}/attempts`),
    events: (c: ApiClient, id: string) => c.get<TaskEvent[]>(`/api/v1/tasks/${id}/events`),
    cancel: (c: ApiClient, id: string) => c.post<Task>(`/api/v1/tasks/${id}/cancel`),
    retry: (c: ApiClient, id: string) => c.post<Task>(`/api/v1/tasks/${id}/retry`),
  },

  verification: {
    list: (c: ApiClient, q?: Query) =>
      c.get<Paginated<BacklinkRecord>>("/api/v1/verification/records", { ...q }),
    run: (c: ApiClient, body: { backlink_ids?: string[]; project_id?: string; force?: boolean }) =>
      c.post<{ scheduled: number }>("/api/v1/verification/run", body),
    history: (c: ApiClient, id: string) =>
      c.get<VerificationRun[]>(`/api/v1/verification/records/${id}/history`),
  },

  imports: {
    preview: (c: ApiClient, file: File, projectId?: string) =>
      c.upload<ImportPreview>("/api/v1/imports/preview", file, {
        project_id: projectId ?? "",
      }),
    commit: (c: ApiClient, id: string, body: ImportCommitRequest) =>
      c.post<ImportJob>(`/api/v1/imports/${id}/commit`, body),
    list: (c: ApiClient, q?: Query) => c.get<Paginated<ImportJob>>("/api/v1/imports", { ...q }),
    rows: (c: ApiClient, id: string) => c.get<ImportJob>(`/api/v1/imports/${id}`),
    errorReport: (c: ApiClient, id: string) =>
      c.download(`/api/v1/imports/${id}/error-report`, `import-errors-${id}.csv`),
  },

  reports: {
    list: (c: ApiClient, q?: Query) => c.get<Paginated<ExportJob>>("/api/v1/reports", { ...q }),
    generate: (c: ApiClient, body: { project_id?: string; format?: "xlsx" | "csv"; scope?: string }) =>
      c.post<ExportJob>("/api/v1/reports", body),
    download: (c: ApiClient, id: string) =>
      c.download(`/api/v1/reports/${id}/download`, `report-${id}.xlsx`),
  },

  activity: {
    list: (c: ApiClient, q?: Query) => c.get<Paginated<ActivityEvent>>("/api/v1/activity", { ...q }),
  },

  adapters: {
    list: (c: ApiClient) => c.get<Adapter[]>("/api/v1/adapters"),
    update: (c: ApiClient, id: string, body: Partial<Adapter>) =>
      c.patch<Adapter>(`/api/v1/adapters/${id}`, body),
  },

  devices: {
    list: (c: ApiClient) => c.get<Device[]>("/api/v1/devices"),
    revoke: (c: ApiClient, id: string) => c.delete<void>(`/api/v1/devices/${id}`),
  },

  dashboard: {
    metrics: (c: ApiClient, projectId?: string) =>
      c.get<DashboardMetrics>("/api/v1/dashboard/metrics", { project_id: projectId }),
    stream: (c: ApiClient, projectId?: string, onMessage?: (e: unknown, t: string) => void) =>
      c.subscribe(
        `/api/v1/events/stream${projectId ? `?project_id=${projectId}` : ""}`,
        onMessage ?? (() => undefined),
      ),
  },

  storage: {
    status: (c: ApiClient) => c.get<StorageStatus>("/api/v1/storage/status"),
    test: (c: ApiClient, body: StorageConnectionRequest) =>
      c.post<{ ok: boolean; message: string; dialect: string }>("/api/v1/storage/test", body),
    connect: (c: ApiClient, body: StorageConnectionRequest) =>
      c.post<StorageStatus>("/api/v1/storage/connect", body),
    disconnect: (c: ApiClient) => c.post<StorageStatus>("/api/v1/storage/disconnect"),
    previewMigration: (c: ApiClient) =>
      c.get<StorageMigrationPreview>("/api/v1/storage/migration/preview"),
    migrate: (c: ApiClient) => c.post<StorageMigrationPreview>("/api/v1/storage/migration/run"),
    backup: (c: ApiClient) => c.post<{ path: string; created_at: string }>("/api/v1/storage/backup"),
    restore: (c: ApiClient, body: { path?: string }) => c.post<{ restored: boolean }>("/api/v1/storage/restore", body),
    history: (c: ApiClient) => c.get<Array<Record<string, unknown>>>("/api/v1/storage/history"),
  },

  sync: {
    status: (c: ApiClient) =>
      c.get<{ pending: number; conflicts: number; last_sync_at: string | null; online: boolean }>(
        "/api/v1/sync/status",
      ),
    push: (c: ApiClient) =>
      c.post<{ ok: boolean; pushed: number; conflicts: number }>("/api/v1/sync/push"),
    pull: (c: ApiClient) =>
      c.post<{ ok: boolean; applied: number; skipped: number }>("/api/v1/sync/pull"),
    resolve: (c: ApiClient, changeId: string, strategy: "local" | "remote") =>
      c.post<{ ok: boolean }>(`/api/v1/sync/conflicts/${changeId}/resolve`, { strategy }),
  },

  campaigns: {
    list: (c: ApiClient, projectId: string) =>
      c.get<Array<Record<string, unknown>>>(`/api/v1/projects/${projectId}/campaigns`),
    create: (c: ApiClient, projectId: string, body: Record<string, unknown>) =>
      c.post<Record<string, unknown>>(`/api/v1/projects/${projectId}/campaigns`, body),
  },

  schedules: {
    list: (c: ApiClient) => c.get<Array<Record<string, unknown>>>("/api/v1/schedules"),
    create: (c: ApiClient, body: Record<string, unknown>) =>
      c.post<Record<string, unknown>>("/api/v1/schedules", body),
    update: (c: ApiClient, id: string, body: Record<string, unknown>) =>
      c.patch<Record<string, unknown>>(`/api/v1/schedules/${id}`, body),
    remove: (c: ApiClient, id: string) => c.delete<void>(`/api/v1/schedules/${id}`),
  },

  ai: {
    status: (c: ApiClient) =>
      c.get<{ configured: boolean; provider: string | null; model: string | null }>(
        "/api/v1/ai/status",
      ),
    run: (c: ApiClient, action: string, payload: Record<string, unknown>) =>
      c.post<Record<string, unknown>>(`/api/v1/ai/${action}`, payload),
  },
};

export type Api = typeof api;
export type { Query };
