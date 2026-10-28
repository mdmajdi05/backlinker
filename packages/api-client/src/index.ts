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
  AdapterConfiguration,
  AdapterConfigurationUpdate,
  AiStatus,
  AuthTokens,
  AutoPilotState,
  BacklinkRecord,
  BrowserRuntimeStatus,
  BulkActionRequest,
  BulkActionResult,
  BusinessProfile,
  BusinessProfileUpsert,
  Campaign,
  CampaignAddResult,
  CampaignStartResult,
  CampaignStopResult,
  CampaignRestartResult,
  CampaignSubmitResult,
  CampaignView,
  GmailStatus,
  ProjectAccounts,
  SiteAccount,
  DashboardMetrics,
  Device,
  DeviceHeartbeatRequest,
  DeviceRegisterRequest,
  DeviceRegisterResponse,
  DeviceTaskReport,
  DiscoveryProvider,
  DiscoveryRequest,
  DiscoveryRun,
  DomainExclusionRequest,
  DomainExclusionResult,
  ExecutionSettings,
  ExportJob,
  GenerateDetailsResult,
  HealthStatus,
  ImportCommitRequest,
  ImportJob,
  ImportPreview,
  ImportRowDetail,
  IntegrationCredentialSummary,
  IntegrationProvider,
  LoginRequest,
  MergeDuplicatesRequest,
  MergeDuplicatesResult,
  Opportunity,
  OpportunityCreate,
  OpportunityUpdate,
  Paginated,
  PageParams,
  Project,
  ProjectCreate,
  ProjectLogin,
  ProjectLoginActionResult,
  ProjectLoginSite,
  ProjectLoginStreamConnection,
  ProjectLoginStreamTicket,
  ProjectLoginView,
  ProjectSettings,
  QueueCreateRequest,
  QueueCreateResponse,
  QueueStats,
  RegisterRequest,
  ReorderResult,
  ReportCreateRequest,
  ResourceStatus,
  Schedule,
  StorageBackup,
  StorageBackupEntry,
  StorageConnectionRequest,
  StorageMigrationPreview,
  StorageRestoreResult,
  StorageStatus,
  SubmissionDetails,
  SubmissionDetailsUpdate,
  WebsiteAutomationDetectResult,
  WebsiteAutomationFindResult,
  WebsiteAutomationSaveRequest,
  WebsiteChooseResult,
  WebsiteImportResult,
  BacklinkDetails,
  BacklinkDetailsUpdate,
  RecycleBinItem,
  RecycleBinPage,
  WebsiteListItem,
  WebsiteStats,
  StorageTestResult,
  SyncChangesResponse,
  SyncEntityPushRequest,
  SyncPullResult,
  SyncPushResult,
  SyncResolveResult,
  SyncStatus,
  SystemInfo,
  TargetWebsite,
  Task,
  TaskAttempt,
  TaskBulkControlRequest,
  TaskControlRequest,
  TaskEvent,
  User,
  VerificationRun,
  VerificationScheduleResult,
  WorkerStatus,
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

  /**
   * Build an absolute `ws://` / `wss://` URL for a backend route.
   *
   * A WebSocket cannot send an `Authorization` header, so the caller attaches
   * a short lived ticket via `query` instead of the session token.
   */
  websocketUrl(path: string, query?: Query): string {
    const origin =
      this.baseUrl ||
      (typeof window !== "undefined" ? window.location.origin : "http://127.0.0.1:8000");
    const url = new URL(`${origin.replace(/\/$/, "")}${path}${buildQuery(query)}`);
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    return url.toString();
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
   *
   * `EventSource` cannot send an `Authorization` header, therefore the token
   * is passed as the `access_token` query parameter.
   */
  subscribe(
    path: string,
    onMessage: (event: unknown, type: string) => void,
    onError?: (err: unknown) => void,
  ): () => void {
    if (typeof EventSource === "undefined") {
      return () => undefined;
    }
    const separator = path.includes("?") ? "&" : "?";
    const url = `${this.baseUrl}${path}${this.token ? `${separator}access_token=${encodeURIComponent(this.token)}` : ""}`;
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
    create: (c: ApiClient, body: Partial<BusinessProfile> | BusinessProfileUpsert) =>
      c.post<BusinessProfile>("/api/v1/profiles", body),
    update: (
      c: ApiClient,
      id: string,
      body: Partial<BusinessProfile> | BusinessProfileUpsert,
    ) => c.put<BusinessProfile>(`/api/v1/profiles/${id}`, body),
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
    /** The company facts and anchors a submission needs (stored in the profile). */
    details: (c: ApiClient, id: string) =>
      c.get<BacklinkDetails>(`/api/v1/projects/${id}/backlink-details`),
    saveDetails: (c: ApiClient, id: string, body: BacklinkDetailsUpdate) =>
      c.put<BacklinkDetails>(`/api/v1/projects/${id}/backlink-details`, body),
    /** The landing pages of the project (the targets a backlink may point to). */
    websites: (c: ApiClient, id: string, q?: PageParams) =>
      c.get<Paginated<TargetWebsite>>(`/api/v1/projects/${id}/websites`, { ...q }),
  },

  /**
   * The Google login of one project.  A project has its own isolated browser
   * profile; the visible login window opens on the machine that runs the
   * backend and is streamed when the client asks for `view="remote"`.
   */
  projectLogin: {
    get: (c: ApiClient, projectId: string) =>
      c.get<ProjectLogin>(`/api/v1/projects/${projectId}/login`),
    /** Open the Google window of the project (native or streamed). */
    connectGoogle: (
      c: ApiClient,
      projectId: string,
      email?: string,
      view?: ProjectLoginView,
    ) =>
      c.post<ProjectLoginActionResult>(`/api/v1/projects/${projectId}/login/google`, {
        email: email ?? null,
        view: view ?? null,
      }),
    /** Save the session of the open window and resume the paused websites. */
    finish: (c: ApiClient, projectId: string) =>
      c.post<ProjectLoginActionResult>(`/api/v1/projects/${projectId}/login/finish`),
    cancel: (c: ApiClient, projectId: string) =>
      c.post<ProjectLoginActionResult>(`/api/v1/projects/${projectId}/login/cancel`),
    /** Forget the session and delete the browser profile of the project. */
    forget: (c: ApiClient, projectId: string) =>
      c.delete<{ forgotten: boolean; login: ProjectLogin }>(
        `/api/v1/projects/${projectId}/login`,
      ),
    /** Open the login page of a single website in the project's profile. */
    openSite: (
      c: ApiClient,
      projectId: string,
      websiteId: string,
      view?: ProjectLoginView,
    ) =>
      c.post<ProjectLoginActionResult>(
        `/api/v1/projects/${projectId}/login/sites/${websiteId}`,
        { view: view ?? null },
      ),
    finishSite: (c: ApiClient, projectId: string, websiteId: string) =>
      c.post<ProjectLoginActionResult>(
        `/api/v1/projects/${projectId}/login/sites/${websiteId}/finish`,
      ),
    markSiteExpired: (c: ApiClient, projectId: string, websiteId: string) =>
      c.post<ProjectLoginSite>(
        `/api/v1/projects/${projectId}/login/sites/${websiteId}/expired`,
      ),
    /**
     * Ask for a one time ticket and return the ready-to-open WebSocket URL of
     * the live login view.  The ticket is consumed on connect; ask for a new
     * one for every (re)connect.
     */
    streamTicket: async (
      c: ApiClient,
      projectId: string,
    ): Promise<ProjectLoginStreamConnection> => {
      const ticket = await c.post<ProjectLoginStreamTicket>(
        `/api/v1/projects/${projectId}/login/stream-ticket`,
      );
      return {
        ...ticket,
        url: c.websocketUrl(ticket.ws_path, { ticket: ticket.ticket }),
      };
    },
  },

  opportunities: {
    list: (c: ApiClient, q?: Query) =>
      c.get<Paginated<Opportunity>>("/api/v1/opportunities", { ...q }),
    get: (c: ApiClient, id: string) =>
      c.get<Opportunity>(`/api/v1/opportunities/${id}`),
    create: (c: ApiClient, body: OpportunityCreate) =>
      c.post<Opportunity>("/api/v1/opportunities", body),
    update: (c: ApiClient, id: string, body: OpportunityUpdate) =>
      c.patch<Opportunity>(`/api/v1/opportunities/${id}`, body),
    bulk: (c: ApiClient, body: BulkActionRequest) =>
      c.post<BulkActionResult>("/api/v1/opportunities/bulk", body),
    excludeDomain: (c: ApiClient, domain: string, body: Omit<DomainExclusionRequest, "domain">) =>
      c.post<DomainExclusionResult>("/api/v1/registry/exclusions", { domain, ...body }),
    /** Merge duplicate registry entries into one primary record. */
    mergeDuplicates: (c: ApiClient, body: MergeDuplicatesRequest) =>
      c.post<MergeDuplicatesResult>("/api/v1/registry/merge", body),
  },

  discovery: {
    run: (c: ApiClient, body: DiscoveryRequest) =>
      c.post<DiscoveryRun>("/api/v1/discovery/runs", body),
    list: (c: ApiClient, q?: Query) =>
      c.get<Paginated<DiscoveryRun>>("/api/v1/discovery/runs", { ...q }),
    get: (c: ApiClient, id: string) => c.get<DiscoveryRun>(`/api/v1/discovery/runs/${id}`),
    providers: (c: ApiClient) => c.get<DiscoveryProvider[]>("/api/v1/discovery/providers"),
  },

  queue: {
    list: (c: ApiClient, q?: Query) => c.get<Paginated<Task>>("/api/v1/queue", { ...q }),
    create: (c: ApiClient, body: QueueCreateRequest) =>
      c.post<QueueCreateResponse>("/api/v1/queue", body),
    reorder: (c: ApiClient, body: { task_ids: string[] }) =>
      c.post<ReorderResult>("/api/v1/queue/reorder", body),
    control: (c: ApiClient, id: string, body: TaskControlRequest) =>
      c.post<Task>(`/api/v1/queue/${id}/control`, body),
    bulkControl: (c: ApiClient, body: TaskBulkControlRequest) =>
      c.post<BulkActionResult>("/api/v1/queue/bulk-control", body),
    stats: (c: ApiClient) => c.get<QueueStats>("/api/v1/queue/stats"),
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
    get: (c: ApiClient, id: string) =>
      c.get<BacklinkRecord>(`/api/v1/verification/records/${id}`),
    run: (c: ApiClient, body: { backlink_ids?: string[]; project_id?: string; force?: boolean }) =>
      c.post<VerificationScheduleResult>("/api/v1/verification/run", body),
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
    /** Every row of the import together with the planned action. */
    rowPlans: (c: ApiClient, id: string) => c.get<ImportRowDetail[]>(`/api/v1/imports/${id}/rows`),
    errorReport: (c: ApiClient, id: string) =>
      c.download(`/api/v1/imports/${id}/error-report`, `import-errors-${id}.csv`),
  },

  reports: {
    list: (c: ApiClient, q?: Query) => c.get<Paginated<ExportJob>>("/api/v1/reports", { ...q }),
    generate: (c: ApiClient, body: ReportCreateRequest) =>
      c.post<ExportJob>("/api/v1/reports", body),
    download: (c: ApiClient, id: string) =>
      c.download(`/api/v1/reports/${id}/download`, `report-${id}.xlsx`),
    remove: (c: ApiClient, id: string) => c.delete<void>(`/api/v1/reports/${id}`),
    retryFailed: (c: ApiClient, id: string, body: { domain?: string; project_id?: string }) =>
      c.post<{ retried: number; skipped: number; task_ids: string[] }>(
        `/api/v1/reports/${id}/retry-failed`,
        body,
      ),
  },

  activity: {
    list: (c: ApiClient, q?: Query) => c.get<Paginated<ActivityEvent>>("/api/v1/activity", { ...q }),
  },

  adapters: {
    list: (c: ApiClient) => c.get<Adapter[]>("/api/v1/adapters"),
    get: (c: ApiClient, id: string) => c.get<Adapter>(`/api/v1/adapters/${id}`),
    update: (c: ApiClient, id: string, body: Partial<Adapter>) =>
      c.patch<Adapter>(`/api/v1/adapters/${id}`, body),
    configuration: (c: ApiClient, id: string) =>
      c.get<AdapterConfiguration[]>(`/api/v1/adapters/${id}/configuration`),
    updateConfiguration: (
      c: ApiClient,
      id: string,
      body: AdapterConfigurationUpdate,
    ) => c.put<AdapterConfiguration>(`/api/v1/adapters/${id}/configuration`, body),
  },

  devices: {
    list: (c: ApiClient) => c.get<Device[]>("/api/v1/devices"),
    revoke: (c: ApiClient, id: string) => c.delete<void>(`/api/v1/devices/${id}`),
    /** Register a local agent (device) - the agent authenticates with the key. */
    register: (c: ApiClient, body: DeviceRegisterRequest) =>
      c.post<DeviceRegisterResponse>("/api/v1/devices/register", body),
    heartbeat: (c: ApiClient, id: string, body: DeviceHeartbeatRequest) =>
      c.post<{ ok: boolean; device_id: string }>(`/api/v1/devices/${id}/heartbeat`, body),
    /** Claim the next task of the local environment (204 when there is none). */
    claimTask: (c: ApiClient) => c.get<Task | null>("/api/v1/devices/tasks/claim"),
    reportTask: (c: ApiClient, id: string, body: DeviceTaskReport) =>
      c.post<{ ok: boolean; attempt: number; status: string }>(
        `/api/v1/devices/tasks/${id}/report`,
        body,
      ),
  },

  integrations: {
    providers: (c: ApiClient) => c.get<IntegrationProvider[]>("/api/v1/integrations/providers"),
    credentials: (c: ApiClient) =>
      c.get<IntegrationCredentialSummary[]>("/api/v1/integrations/credentials"),
    saveCredential: (c: ApiClient, body: { provider: string; label?: string; secret?: string }) =>
      c.post<{ id: string; provider: string; masked_hint: string }>(
        "/api/v1/integrations/credentials",
        body,
      ),
    deleteCredential: (c: ApiClient, id: string) =>
      c.delete<void>(`/api/v1/integrations/credentials/${id}`),
    /** Reveal a secret - administrators only. */
    revealCredential: (c: ApiClient, id: string) =>
      c.get<{ provider: string; secret: string }>(
        `/api/v1/integrations/credentials/${id}/reveal`,
      ),
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

  /** The live event stream and the recent events of the activity log. */
  events: {
    stream: (c: ApiClient, projectId?: string, onMessage?: (e: unknown, t: string) => void) =>
      c.subscribe(
        `/api/v1/events/stream${projectId ? `?project_id=${projectId}` : ""}`,
        onMessage ?? (() => undefined),
      ),
    recent: (c: ApiClient, limit?: number) =>
      c.get<ActivityEvent[]>("/api/v1/events/recent", { limit }),
  },

  storage: {
    status: (c: ApiClient) => c.get<StorageStatus>("/api/v1/storage/status"),
    test: (c: ApiClient, body: StorageConnectionRequest) =>
      c.post<StorageTestResult>("/api/v1/storage/test", body),
    connect: (c: ApiClient, body: StorageConnectionRequest) =>
      c.post<StorageStatus>("/api/v1/storage/connect", body),
    disconnect: (c: ApiClient) => c.post<StorageStatus>("/api/v1/storage/disconnect"),
    previewMigration: (c: ApiClient) =>
      c.get<StorageMigrationPreview>("/api/v1/storage/migration/preview"),
    migrate: (c: ApiClient) => c.post<StorageMigrationPreview>("/api/v1/storage/migration/run"),
    backup: (c: ApiClient) => c.post<StorageBackup>("/api/v1/storage/backup"),
    restore: (c: ApiClient, body: { path?: string }) =>
      c.post<StorageRestoreResult>("/api/v1/storage/restore", body),
    history: (c: ApiClient) => c.get<StorageBackupEntry[]>("/api/v1/storage/history"),
  },

  sync: {
    status: (c: ApiClient) => c.get<SyncStatus>("/api/v1/sync/status"),
    push: (c: ApiClient) => c.post<SyncPushResult>("/api/v1/sync/push"),
    pull: (c: ApiClient) => c.post<SyncPullResult>("/api/v1/sync/pull"),
    resolve: (c: ApiClient, changeId: string, strategy: "local" | "remote") =>
      c.post<SyncResolveResult>(`/api/v1/sync/conflicts/${changeId}/resolve`, { strategy }),
    /** The changes a local workspace has to pull. */
    changes: (c: ApiClient, q?: { since?: string; limit?: number }) =>
      c.get<SyncChangesResponse>("/api/v1/sync/changes", { ...q }),
    /** Push a single entity to the cloud workspace. */
    pushEntity: (c: ApiClient, entityType: string, body: SyncEntityPushRequest) =>
      c.post<{ ok: boolean; entity_type: string; entity_id: string; version: number }>(
        `/api/v1/sync/${entityType}`,
        body,
      ),
  },

  campaigns: {
    list: (c: ApiClient, projectId: string) =>
      c.get<Campaign[]>(`/api/v1/projects/${projectId}/campaigns`),
    create: (c: ApiClient, projectId: string, body: Partial<Campaign>) =>
      c.post<Campaign>(`/api/v1/projects/${projectId}/campaigns`, body),
    remove: (c: ApiClient, campaignId: string) =>
      c.delete<void>(`/api/v1/campaigns/${campaignId}`),
  },

  /**
   * The campaign cockpit of a project: add websites, start the work and read
   * the live state of every row.
   */
  campaign: {
    get: (c: ApiClient, projectId: string) =>
      c.get<CampaignView>(`/api/v1/projects/${projectId}/campaign`),
    /** Add one URL or a comma / new line separated list. */
    add: (c: ApiClient, projectId: string, text: string) =>
      c.post<CampaignAddResult>(`/api/v1/projects/${projectId}/campaign/websites`, {
        text,
      }),
    /** Import a spreadsheet and link the imported rows to the project. */
    import: (c: ApiClient, projectId: string, file: File) =>
      c.upload<
        CampaignAddResult & { created: number; updated: number; skipped: number; linked: number }
      >(`/api/v1/projects/${projectId}/campaign/import`, file),
    start: (c: ApiClient, projectId: string) =>
      c.post<CampaignStartResult>(`/api/v1/projects/${projectId}/campaign/start`),
    /** Pause the whole project; Start resumes the same work. */
    stop: (c: ApiClient, projectId: string) =>
      c.post<CampaignStopResult>(`/api/v1/projects/${projectId}/campaign/stop`),
    /** Remove one website from the project - the website stays in the list. */
    remove: (c: ApiClient, projectId: string, opportunityId: string) =>
      c.delete<void>(
        `/api/v1/projects/${projectId}/campaign/${opportunityId}`,
      ),
    /** Queue failed submissions and verifications again. */
    restartFailed: (c: ApiClient, projectId: string) =>
      c.post<CampaignRestartResult>(
        `/api/v1/projects/${projectId}/campaign/restart-failed`,
      ),
    /** Download the live table as a CSV report. */
    downloadReport: (c: ApiClient, projectId: string) =>
      c.download(
        `/api/v1/projects/${projectId}/campaign/report.csv`,
        `backlinks-${projectId}.csv`,
      ),
    /** Record a submission the operator made by hand. */
    markSubmitted: (
      c: ApiClient,
      projectId: string,
      opportunityId: string,
      body: { published_url?: string; anchor_text?: string; verify?: boolean } = {},
    ) =>
      c.post<CampaignSubmitResult>(
        `/api/v1/projects/${projectId}/campaign/${opportunityId}/submit`,
        body,
      ),
    verify: (c: ApiClient, projectId: string, opportunityId: string) =>
      c.post<{ task_id: string; backlink_id: string; created: boolean }>(
        `/api/v1/projects/${projectId}/campaign/${opportunityId}/verify`,
      ),
  },

  /**
   * The accounts of a project on its backlink websites: one background batch
   * creates every missing account with one browser and one Gmail session.
   */
  accounts: {
    get: (c: ApiClient, projectId: string) =>
      c.get<ProjectAccounts>(`/api/v1/projects/${projectId}/accounts`),
    /** Create every missing account in one batch (or the given websites). */
    provision: (
      c: ApiClient,
      projectId: string,
      body: { website_ids?: string[]; retry?: boolean } = {},
    ) =>
      c.post<{ batch: ProjectAccounts["batch"]; accounts: Record<string, SiteAccount> }>(
        `/api/v1/projects/${projectId}/accounts/provision`,
        body,
      ),
    /** Retry one website (after a CAPTCHA was solved by hand, for example). */
    provisionOne: (c: ApiClient, projectId: string, websiteId: string) =>
      c.post<{ batch: ProjectAccounts["batch"]; account: SiteAccount | null }>(
        `/api/v1/projects/${projectId}/accounts/${websiteId}/provision`,
        { retry: true },
      ),
    stop: (c: ApiClient, projectId: string) =>
      c.post<{
        stopped: boolean;
        batch: ProjectAccounts["batch"];
        accounts: Record<string, SiteAccount>;
      }>(`/api/v1/projects/${projectId}/accounts/stop`),
    /** Search the backlink page again with the authenticated session. */
    discover: (c: ApiClient, projectId: string, websiteId: string) =>
      c.post<{ result: Record<string, unknown>; account: SiteAccount | null }>(
        `/api/v1/projects/${projectId}/accounts/${websiteId}/discover`,
      ),
    gmail: (c: ApiClient) => c.get<GmailStatus>("/api/v1/accounts/gmail"),
    saveGmail: (
      c: ApiClient,
      body: { address: string; app_password: string; save?: boolean },
    ) =>
      c.put<GmailStatus & { ok: boolean; message: string }>(
        "/api/v1/accounts/gmail",
        body,
      ),
    testGmail: (
      c: ApiClient,
      body: { address?: string; app_password?: string } = {},
    ) =>
      c.post<{ ok: boolean; message: string }>("/api/v1/accounts/gmail/test", body),
    forgetGmail: (c: ApiClient) => c.delete<GmailStatus>("/api/v1/accounts/gmail"),
  },

  schedules: {
    list: (c: ApiClient) => c.get<Schedule[]>("/api/v1/schedules"),
    create: (c: ApiClient, body: Partial<Schedule>) =>
      c.post<Schedule>("/api/v1/schedules", body),
    update: (c: ApiClient, id: string, body: Partial<Schedule>) =>
      c.patch<Schedule>(`/api/v1/schedules/${id}`, body),
    remove: (c: ApiClient, id: string) => c.delete<void>(`/api/v1/schedules/${id}`),
  },

  ai: {
    status: (c: ApiClient) => c.get<AiStatus>("/api/v1/ai/status"),
    run: (c: ApiClient, action: string, payload: Record<string, unknown>) =>
      c.post<Record<string, unknown>>(`/api/v1/ai/${action}`, payload),
  },

  automation: {
    browserStatus: (c: ApiClient) => c.get<BrowserRuntimeStatus>("/api/v1/browser/status"),
    installBrowser: (c: ApiClient) =>
      c.post<{ ok: boolean; message: string; status: BrowserRuntimeStatus }>(
        "/api/v1/browser/install",
      ),
    workerStatus: (c: ApiClient) => c.get<WorkerStatus>("/api/v1/worker/status"),
    updateSettings: (c: ApiClient, body: Partial<ExecutionSettings>) =>
      c.put<{ execution: ExecutionSettings }>("/api/v1/worker/settings", body),
    pause: (c: ApiClient) => c.post<{ execution: ExecutionSettings }>("/api/v1/worker/pause"),
    resume: (c: ApiClient) => c.post<{ execution: ExecutionSettings }>("/api/v1/worker/resume"),
    stop: (c: ApiClient) =>
      c.post<{ execution: ExecutionSettings; cancelled: number }>("/api/v1/worker/stop"),
    resources: (c: ApiClient) => c.get<ResourceStatus>("/api/v1/resources"),
  },

  /**
   * The submission details of one opportunity - the values a directory asks
   * for.  They are stored per opportunity so the same site can be filled
   * differently in two projects.
   */
  submissionDetails: {
    get: (c: ApiClient, opportunityId: string) => c.get<SubmissionDetails>(`/api/v1/opportunities/${opportunityId}/details`).then((value) => normalizeSubmissionDetails(value)),
    update: (c: ApiClient, opportunityId: string, body: SubmissionDetailsUpdate) => c.put<SubmissionDetails>(`/api/v1/opportunities/${opportunityId}/details`, body).then((value) => normalizeSubmissionDetails(value)),
    remove: (c: ApiClient, opportunityId: string) => c.delete<void>(`/api/v1/opportunities/${opportunityId}/details`),
    required: (c: ApiClient, opportunityId: string) => c.get<{ required: string[]; missing: string[]; complete: boolean }>(`/api/v1/opportunities/${opportunityId}/details/required`),
    gaps: (c: ApiClient, opportunityId: string) => c.get<DetailsGapReport>(`/api/v1/opportunities/${opportunityId}/details/gaps`),
    generate: (c: ApiClient, opportunityId: string) => c.post<GenerateDetailsResult>(`/api/v1/opportunities/${opportunityId}/details/generate`).then(normalizeGenerateResult),
  },

  /**
   * The central list of websites where the backlinks are made.  It is
   * independent of the projects - a project picks the sites it wants from it.
   */
  /**
   * The recycle bin: everything that was deleted waits here until it is
   * restored or deleted forever.
   */
  recycleBin: {
    list: (c: ApiClient, query?: Query) => c.get<RecycleBinPage>("/api/v1/recycle-bin", { ...query }),
    counts: (c: ApiClient) => c.get<Record<string, number>>("/api/v1/recycle-bin/counts"),
    /** Bring a removed row back into the normal lists. */
    restore: (c: ApiClient, kind: string, id: string) =>
      c.post<RecycleBinItem>(`/api/v1/recycle-bin/${kind}/${id}/restore`),
    /** Delete a row from the recycle bin forever, with everything that depends on it. */
    purge: (c: ApiClient, kind: string, id: string) =>
      c.delete<void>(`/api/v1/recycle-bin/${kind}/${id}`),
  },

  websites: {
    list: (c: ApiClient, query?: Query) => c.get<Paginated<WebsiteListItem>>("/api/v1/websites", { ...query }),
    create: (c: ApiClient, body: Record<string, unknown>) => c.post<WebsiteListItem>("/api/v1/websites", body),
    update: (c: ApiClient, id: string, body: Record<string, unknown>) => c.patch<WebsiteListItem>(`/api/v1/websites/${id}`, body),
    remove: (c: ApiClient, id: string) => c.delete<void>(`/api/v1/websites/${id}`),
    /** Bring a removed website back into the list. */
    restore: (c: ApiClient, id: string) => c.post<WebsiteListItem>(`/api/v1/websites/${id}/restore`),
    /** Delete a website forever, including its opportunities and tasks. */
    purge: (c: ApiClient, id: string) => c.delete<void>(`/api/v1/websites/${id}/purge`),
    importFile: (c: ApiClient, file: File, fields: Record<string, string> = {}) => c.upload<WebsiteImportResult>("/api/v1/websites/import", file, fields),
    stats: (c: ApiClient, projectId?: string) => c.get<WebsiteStatsRow[]>("/api/v1/websites/stats", { project_id: projectId }),
    chooseForProject: (c: ApiClient, projectId: string, body: Record<string, unknown>) => c.post<WebsiteChooseResult>(`/api/v1/projects/${projectId}/websites/choose`, body),
    /** Store the per website automatic form configuration. */
    saveAutomation: (c: ApiClient, id: string, body: WebsiteAutomationSaveRequest) =>
      c.put<WebsiteListItem>(`/api/v1/websites/${id}/automation`, body),
    /** Remove the automatic form configuration (manual path). */
    clearAutomation: (c: ApiClient, id: string) =>
      c.delete<WebsiteListItem>(`/api/v1/websites/${id}/automation`),
    /** Inspect the static form HTML and propose CSS selectors. */
    detectAutomation: (c: ApiClient, id: string, body: { form_url?: string } = {}) =>
      c.post<WebsiteAutomationDetectResult>(`/api/v1/websites/${id}/automation/detect`, body),
    /** Follow the "add listing" links of the homepage to the real form. */
    findAutomationForm: (c: ApiClient, id: string, body: { form_url?: string } = {}) =>
      c.post<WebsiteAutomationFindResult>(`/api/v1/websites/${id}/automation/find-form`, body),
  },

  /** The automatic submission of a project. */
  autoPilot: {
    get: (c: ApiClient, projectId: string) => c.get<AutoPilotState>(`/api/v1/projects/${projectId}/autopilot`).then((value) => normalizeAutoPilot(value)),
    update: (c: ApiClient, projectId: string, body: { enabled: boolean; categories: string[] }) => c.post<AutoPilotState>(`/api/v1/projects/${projectId}/autopilot`, body).then((value) => normalizeAutoPilot(value)),
  },

  /** Information about the backend the client talks to. */
  system: {
    info: (c: ApiClient) => c.get<SystemInfo>("/api/v1/system/info"),
    health: (c: ApiClient) => c.get<HealthStatus>("/health"),
  },
};

export type Api = typeof api;
export type { Query };

/* ------------------------------------------------------------------ */
/* Normalisation - the interface must never crash on a partial answer   */
/* ------------------------------------------------------------------ */

function asString(value: unknown): string | null {
  if (typeof value === "string") return value;
  if (value === null || value === undefined) return null;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return null;
}

function asNumber(value: unknown): number | null {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function asStringList(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.map((item) => asString(item)).filter((item): item is string => item !== null);
  }
  if (typeof value === "string") {
    return value
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
  }
  return [];
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

export function normalizeSubmissionDetails(value: unknown): SubmissionDetails {
  const raw = asRecord(value);
  return {
    opportunity_id: asString(raw.opportunity_id) ?? "",
    company_name: asString(raw.company_name),
    description: asString(raw.description),
    email: asString(raw.email),
    phone: asString(raw.phone),
    website: asString(raw.website),
    address: asString(raw.address),
    city: asString(raw.city),
    state: asString(raw.state),
    country: asString(raw.country),
    postal_code: asString(raw.postal_code),
    logo_path: asString(raw.logo_path),
    categories: asStringList(raw.categories),
    founded_year: asNumber(raw.founded_year),
    employee_count: asNumber(raw.employee_count),
    extra: asRecord(raw.extra),
    generated: asRecord(raw.generated),
    updated_at: asString(raw.updated_at),
    required: asStringList(raw.required),
    missing: asStringList(raw.missing),
    complete: Boolean(raw.complete),
  };
}

export function normalizeAutoPilot(value: unknown): AutoPilotState {
  const raw = asRecord(value);
  return {
    enabled: Boolean(raw.enabled),
    categories: asStringList(raw.categories),
    waiting: asNumber(raw.waiting) ?? 0,
    submitted: asNumber(raw.submitted) ?? 0,
  };
}

export function normalizeGenerateResult(value: unknown): GenerateDetailsResult {
  const raw = asRecord(value);
  return {
    details: normalizeSubmissionDetails(raw.details),
    generated: asStringList(raw.generated),
    source: asString(raw.source) ?? "profile",
  };
}

/** One row of the per website statistics. */
export interface WebsiteStatsRow {
  domain: string;
  name: string;
  category: string;
  status: string;
  opportunities: number;
  submitted: number;
  verified: number;
  failed: number;
  pending: number;
  waiting_for_details: number;
  last_attempt_at: string | null;
  notes: string | null;
}

/** Which details of an opportunity could not be derived from the profile. */
export interface DetailsGapReport {
  required: string[];
  filled: string[];
  missing: string[];
  derivable: string[];
  not_derivable: Array<{ field: string; label: string; reason: string }>;
  source: string;
}
