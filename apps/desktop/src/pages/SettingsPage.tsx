import * as React from "react";
import {
  Alert,
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  Field,
  Input,
  KeyValue,
  Select,
  useToast,
} from "@autobacklinker/ui";
import { useBackend } from "../lib/backendState";
import { useTheme, type ThemePreference } from "../lib/theme";
import { useNotifications } from "../lib/notifications";
import { useAuth } from "../lib/auth";
import { api, apiClient, setApiBaseUrl, setSessionMode } from "../lib/api";
import { openPath } from "../lib/backend";
import {
  getBrowserRuntimeStatus,
  installBrowserRuntime,
  type BrowserRuntimeStatus,
} from "../lib/backend";
import { ErrorBlock, LoadingBlock, PageHeader } from "../components/common";
import { useAsync } from "../lib/useAsync";
import { formatDate } from "../lib/format";

export function SettingsPage() {
  const toast = useToast();
  const backend = useBackend();
  const { preference, setPreference } = useTheme();
  const {
    enabled: notificationsEnabled,
    supported: notificationsSupported,
    setEnabled: setNotificationsEnabled,
  } = useNotifications();
  const { mode, user, logout } = useAuth();
  const [backendUrl, setBackendUrl] = React.useState(apiClient.baseUrl);
  const [port, setPort] = React.useState(
    String(backend.status?.port ?? 8765),
  );

  const storage = useAsync(() => api.storage.status(apiClient), []);

  // The browser runtime is only needed by the browser adapter.
  const [browserRuntime, setBrowserRuntime] = React.useState<BrowserRuntimeStatus | null>(null);
  const [installingBrowser, setInstallingBrowser] = React.useState(false);
  const [installBrowserMessage, setInstallBrowserMessage] = React.useState<string | null>(null);

  const refreshBrowserRuntime = React.useCallback(async () => {
    try {
      setBrowserRuntime(await getBrowserRuntimeStatus());
    } catch {
      setBrowserRuntime(null);
    }
  }, []);

  React.useEffect(() => {
    void refreshBrowserRuntime();
  }, [refreshBrowserRuntime]);

  const installBrowser = React.useCallback(async () => {
    setInstallingBrowser(true);
    setInstallBrowserMessage(null);
    try {
      const message = await installBrowserRuntime();
      setInstallBrowserMessage(message);
      toast.push("The browser runtime was installed", "success");
    } catch (error) {
      const text = error instanceof Error ? error.message : String(error);
      setInstallBrowserMessage(text);
      toast.push("The browser runtime could not be installed", "error");
    } finally {
      setInstallingBrowser(false);
      void refreshBrowserRuntime();
    }
  }, [refreshBrowserRuntime, toast]);

  const status = backend.status;
  const native = backend.native;
  const refreshLogs = backend.refreshLogs;

  React.useEffect(() => {
    if (status?.port) setPort(String(status.port));
  }, [status?.port]);

  React.useEffect(() => {
    if (!native) return;
    void refreshLogs();
    const timer = window.setInterval(() => {
      void refreshLogs();
    }, 5000);
    return () => window.clearInterval(timer);
  }, [native, refreshLogs]);

  function switchToHostedBackend() {
    const url = backendUrl.trim();
    if (!url) return;
    setApiBaseUrl(url);
    setSessionMode("cloud");
    logout();
    toast.push("Switched to the hosted backend - sign in to continue", "info");
  }

  function switchToLocal() {
    if (!status?.baseUrl) {
      toast.push("The local backend is not available", "error");
      return;
    }
    setApiBaseUrl(status.baseUrl);
    setSessionMode("local");
    toast.push("Switched back to the local backend", "success");
  }

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Settings"
        description="Local backend, optional hosted backend, notifications and appearance."
      />

      <Card>
        <CardHeader
          title="Local backend"
          description="The bundled FastAPI sidecar that runs on this machine."
          action={
            <div className="flex items-center gap-2">
              <Button
                size="sm"
                variant="outline"
                disabled={!backend.native || backend.loading}
                onClick={() => void backend.start(Number(port) || 0)}
              >
                Start
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={!backend.native || backend.loading}
                onClick={() => void backend.stop()}
              >
                Stop
              </Button>
              <Button
                size="sm"
                disabled={!backend.native || backend.loading}
                onClick={() => void backend.restart()}
              >
                Restart
              </Button>
            </div>
          }
        />
        <CardBody>
          {!backend.native ? (
            <Alert tone="info" title="Browser preview">
              The local backend is managed by the Tauri shell. Run the app with
              <code className="mx-1 rounded bg-surface-sunken px-1">npm run tauri:dev</code>
              to start and supervise it.
            </Alert>
          ) : null}

          {backend.error ? (
            <div className="mb-3">
              <ErrorBlock message={backend.error} onRetry={backend.refresh} />
            </div>
          ) : null}

          <KeyValue
            items={[
              [
                "State",
                status ? (
                  <span
                    className={
                      status.healthy
                        ? "text-success"
                        : status.running
                          ? "text-warning"
                          : "text-danger"
                    }
                  >
                    {status.healthy
                      ? "healthy"
                      : status.running
                        ? "starting"
                        : "stopped"}
                  </span>
                ) : (
                  "-"
                ),
              ],
              ["Base URL", status?.baseUrl ?? "-"],
              ["Process id", status?.pid ? String(status.pid) : "-"],
              ["Restarts", status?.restarts ? String(status.restarts) : "0"],
              ["Started", formatDate(status?.startedAt)],
              ["Data directory", status?.dataDir ?? "-"],
              ["Log file", status?.logPath ?? "-"],
              ["Sidecar binary", status?.sidecarPath ?? "-"],
              ["Last error", status?.lastError ?? "-"],
            ]}
          />

          <div className="mt-4 flex flex-wrap items-end gap-3">
            <div className="w-40">
              <Field label="Port" hint="127.0.0.1 only">
                <Input
                  type="number"
                  min={1024}
                  max={65535}
                  value={port}
                  onChange={(event) => setPort(event.target.value)}
                />
              </Field>
            </div>
            <Button
              variant="outline"
              disabled={!backend.native}
              onClick={() => {
                if (!status?.dataDir) return;
                void openPath(status.dataDir).catch(() =>
                  toast.push("Could not open the data directory", "error"),
                );
              }}
            >
              Open data directory
            </Button>
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title="Browser runtime"
          description="Needed by the browser adapter (Playwright + Chromium)."
          action={
            <div className="flex items-center gap-2">
              <Button
                size="sm"
                variant="outline"
                disabled={!backend.native}
                onClick={() => void refreshBrowserRuntime()}
              >
                Check
              </Button>
              <Button
                size="sm"
                disabled={!backend.native || installingBrowser || browserRuntime?.installed}
                loading={installingBrowser}
                onClick={() => void installBrowser()}
              >
                {browserRuntime?.installed ? "Installed" : "Install"}
              </Button>
            </div>
          }
        />
        <CardBody>
          <p className="text-xs text-content-muted">
            {browserRuntime?.installed
              ? `The browser runtime is available at ${browserRuntime.path}. The browser adapter can run form submissions.`
              : "The browser runtime is not installed yet. Without it the browser adapter pauses its tasks and asks for manual completion - everything else works. The download is about 150 MB and needs an internet connection once."}
          </p>
          {installBrowserMessage ? (
            <pre className="mt-3 max-h-40 overflow-auto rounded-md bg-surface-sunken p-2 text-[11px] text-content-muted">
              {installBrowserMessage}
            </pre>
          ) : null}
        </CardBody>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader title="Notifications" />
          <CardBody>
            <label className="flex items-start gap-2 text-sm text-content">
              <input
                type="checkbox"
                className="mt-0.5 h-4 w-4 rounded border-line-strong text-accent focus:ring-accent"
                checked={notificationsEnabled}
                disabled={!notificationsSupported}
                onChange={(event) => setNotificationsEnabled(event.target.checked)}
              />
              <span>
                Native desktop notifications
                <span className="mt-0.5 block text-xs text-content-muted">
                  {notificationsSupported
                    ? "Important backend events are shown as system notifications."
                    : "Only available in the desktop build."}
                </span>
              </span>
            </label>
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="Appearance" />
          <CardBody>
            <Field label="Theme" hint="Uses the shared design tokens.">
              <Select
                value={preference}
                onChange={(event) =>
                  setPreference(event.target.value as ThemePreference)
                }
              >
                <option value="system">Follow the system</option>
                <option value="light">Light</option>
                <option value="dark">Dark</option>
              </Select>
            </Field>
          </CardBody>
        </Card>
      </div>

      <Card>
        <CardHeader
          title="Optional hosted backend"
          description="Point this client at a different Auto Backlinker backend. This only changes where the client sends requests - it does not copy or synchronise local data. The bundled local backend stays the default."
          action={
            <Badge tone={mode === "cloud" ? "accent" : "neutral"}>
              {mode === "cloud" ? "Hosted" : "Local"}
            </Badge>
          }
        />
        <CardBody>
          <div className="flex flex-wrap items-end gap-3">
            <div className="w-96">
              <Field label="Backend URL" hint="Must expose the same API as the local backend.">
                <Input
                  value={backendUrl}
                  onChange={(event) => setBackendUrl(event.target.value)}
                  placeholder="https://backlinks.example.com"
                />
              </Field>
            </div>
            <Button onClick={switchToHostedBackend}>Use this backend</Button>
            <Button variant="outline" onClick={switchToLocal}>
              Back to local backend
            </Button>
          </div>
          <p className="mt-3 text-xs text-content-muted">
            {mode === "cloud"
              ? `Signed in as ${user?.email ?? "an unknown user"} on the hosted backend. Data already stored locally is not transferred.`
              : "The desktop app is currently connected to the local sidecar, which is the default."}
          </p>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Storage" />
        <CardBody>
          {storage.loading && !storage.data ? (
            <LoadingBlock rows={2} />
          ) : storage.error ? (
            <ErrorBlock message={storage.error} onRetry={storage.reload} />
          ) : (
            <KeyValue
              items={[
                ["Mode", storage.data?.mode ?? "-"],
                ["Database", storage.data?.database_type ?? "-"],
                ["Connection", storage.data?.database_url_masked ?? "-"],
                ["Last backup", formatDate(storage.data?.last_backup_at)],
                ["Schema", storage.data?.schema_version ?? "-"],
              ]}
            />
          )}
        </CardBody>
      </Card>
    </div>
  );
}
