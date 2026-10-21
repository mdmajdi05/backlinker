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
  ProgressBar,
  Select,
  useToast,
} from "@autobacklinker/ui";
import { api, apiClient } from "../lib/api";
import { useAsync } from "../lib/useAsync";
import { ErrorBlock, LoadingBlock } from "../components/common";
import {
  NativeUnavailableError,
  installBrowserRuntime,
  sendNativeNotification,
} from "../lib/backend";
import type { ExecutionSettings, WorkerStatus } from "@autobacklinker/shared-types";

function errorText(error: unknown, fallback: string): string {
  if (error && typeof error === "object" && "message" in error) {
    return String((error as { message: unknown }).message);
  }
  return fallback;
}

/**
 * Controls of the background automation.
 *
 * The browser that the platform uses is always an isolated browser of this
 * application - the personal browser of the operator is never opened or
 * controlled. This panel shows that guarantee, the resource usage of the
 * machine and the switches that decide how much of the machine the jobs may
 * use.
 */
export function AutomationPanel() {
  const toast = useToast();
  const [busy, setBusy] = React.useState<string | null>(null);
  const [installLog, setInstallLog] = React.useState<string | null>(null);

  const status = useAsync(() => api.automation.workerStatus(apiClient), []);

  const data: WorkerStatus | null = status.data;
  const execution = data?.execution;
  const resources = data?.resources;
  const browser = data?.browser;

  const reload = () => status.reload();

  const run = async (
    key: string,
    action: () => Promise<unknown>,
    message: string,
  ) => {
    setBusy(key);
    try {
      await action();
      toast.push(message, "success");
      void sendNativeNotification("Auto Backlinker", message);
      reload();
    } catch (err) {
      const text = errorText(err, "The action could not be executed");
      toast.push(text, "error");
      void sendNativeNotification("Auto Backlinker", text);
    } finally {
      setBusy(null);
    }
  };

  const save = async (changes: Partial<ExecutionSettings>) => {
    setBusy("settings");
    try {
      await api.automation.updateSettings(apiClient, changes);
      toast.push("Automation settings saved", "success");
      reload();
    } catch (err) {
      toast.push(errorText(err, "Could not save the settings"), "error");
    } finally {
      setBusy(null);
    }
  };

  const installBrowser = async () => {
    setBusy("browser");
    setInstallLog(null);
    try {
      let message: string;
      try {
        // The desktop build ships its own installer - it puts the runtime
        // into the directory of the application.
        message = await installBrowserRuntime();
      } catch (error) {
        if (!(error instanceof NativeUnavailableError)) throw error;
        const result = await api.automation.installBrowser(apiClient);
        message = result.message ?? "The browser runtime was installed.";
      }
      setInstallLog(message);
      toast.push("The browser runtime was installed", "success");
      void sendNativeNotification(
        "Auto Backlinker",
        "The browser runtime was installed.",
      );
      reload();
    } catch (err) {
      const text = errorText(err, "The browser runtime could not be installed");
      setInstallLog(text);
      toast.push(text, "error");
      void sendNativeNotification("Auto Backlinker", text);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader
          title="Background execution"
          description="Pause, resume or stop every automation job on this machine."
          action={
            <div className="flex items-center gap-2">
              <Button
                size="sm"
                variant="outline"
                disabled={busy !== null || execution?.state === "PAUSED"}
                loading={busy === "pause"}
                onClick={() =>
                  run(
                    "pause",
                    () => api.automation.pause(apiClient),
                    "Automation paused",
                  )
                }
              >
                Pause all
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={busy !== null || execution?.state === "RUNNING"}
                loading={busy === "resume"}
                onClick={() =>
                  run(
                    "resume",
                    () => api.automation.resume(apiClient),
                    "Automation resumed",
                  )
                }
              >
                Resume
              </Button>
              <Button
                size="sm"
                variant="danger"
                disabled={busy !== null || execution?.state === "STOPPED"}
                loading={busy === "stop"}
                onClick={() =>
                  run(
                    "stop",
                    () => api.automation.stop(apiClient),
                    "Automation stopped",
                  )
                }
              >
                Stop
              </Button>
            </div>
          }
        />
        <CardBody>
          {status.error ? (
            <div className="mb-3">
              <ErrorBlock
                message={status.error}
                onRetry={status.reload}
              />
            </div>
          ) : null}

          {status.loading && !data ? (
            <LoadingBlock rows={2} />
          ) : (
            <>
              <div className="flex flex-wrap items-center gap-3">
                <Badge
                  tone={
                    execution?.state === "RUNNING"
                      ? "success"
                      : execution?.state === "PAUSED"
                        ? "warning"
                        : "danger"
                  }
                >
                  {execution?.state ?? "UNKNOWN"}
                </Badge>
                <span className="text-xs text-content-muted">
                  {execution?.states?.[execution?.state ?? "RUNNING"] ??
                    "Jobs are claimed and executed."}
                </span>
              </div>

              <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <KeyValue
                  items={[
                    ["Running jobs", String(data?.running_jobs ?? 0)],
                    [
                      "Running browser jobs",
                      String(data?.running_browser_jobs ?? 0),
                    ],
                    [
                      "Parallel browser jobs",
                      String(resources?.effective_limit ?? 0),
                    ],
                    [
                      "Configured limit",
                      String(resources?.configured_limit ?? 0),
                    ],
                  ]}
                />
              </div>
            </>
          )}
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title="Browser isolation"
          description="The automation runs in a browser that belongs to this application."
        />
        <CardBody className="flex flex-col gap-3">
          <Alert tone="info" title="Your personal browser is never touched">
            {browser?.isolation?.note ??
              "The automation uses its own browser with a throw away profile."}
          </Alert>
          <div className="grid gap-3 sm:grid-cols-2">
            <KeyValue
              items={[
                [
                  "Runtime",
                  browser?.available ? "installed" : "not installed",
                ],
                [
                  "Mode",
                  browser?.headless
                    ? "headless (default)"
                    : "headed (isolated profile)",
                ],
                ["Own profile directory", browser?.profile_dir ?? "-"],
                ["Browser build directory", browser?.browsers_dir ?? "-"],
                ["Personal profile used", browser?.isolation?.personal_profile_used ? "yes" : "no"],
                ["Extensions disabled", browser?.isolation?.extensions_disabled ? "yes" : "no"],
              ]}
            />
            <div className="flex flex-col gap-2">
              <p className="text-xs text-content-muted">
                The browser build is downloaded once into the directory of this
                installation. It is not shared with the browser of the operating
                system.
              </p>
              <div>
                <Button
                  size="sm"
                  disabled={busy !== null}
                  loading={busy === "browser"}
                  onClick={() => void installBrowser()}
                >
                  {browser?.available
                    ? "Reinstall browser runtime"
                    : "Install browser runtime"}
                </Button>
              </div>
              {installLog ? (
                <pre className="max-h-40 overflow-auto rounded-md bg-surface-sunken p-2 text-[11px] text-content-muted">
                  {installLog}
                </pre>
              ) : null}
            </div>
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title="Resource usage"
          description="The number of parallel jobs is lowered automatically when the machine is busy."
        />
        <CardBody className="flex flex-col gap-3">
          {resources ? (
            <>
              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <div className="mb-1 flex items-center justify-between text-xs">
                    <span className="text-content-muted">CPU</span>
                    <span className="text-content">
                      {resources.resources.cpu_percent}%
                    </span>
                  </div>
                  <ProgressBar value={resources.resources.cpu_percent / 100} />
                </div>
                <div>
                  <div className="mb-1 flex items-center justify-between text-xs">
                    <span className="text-content-muted">Memory in use</span>
                    <span className="text-content">
                      {resources.resources.memory_used_percent}%
                    </span>
                  </div>
                  <ProgressBar
                    value={resources.resources.memory_used_percent / 100}
                  />
                </div>
              </div>
              <KeyValue
                items={[
                  [
                    "Free memory",
                    `${Math.round(resources.resources.memory_available_mb)} MB of ${Math.round(
                      resources.resources.memory_total_mb,
                    )} MB`,
                  ],
                  [
                    "Effective parallel limit",
                    String(resources.effective_limit),
                  ],
                  ["Configured limit", String(resources.configured_limit)],
                  ["Preference", resources.preference],
                ]}
              />
              <p className="text-xs text-content-muted">{resources.reason}</p>
              <p className="text-[11px] text-content-subtle">
                The limit is enforced by the worker before a job is claimed. It
                cannot stop a single browser process from using CPU, so it is a
                target and not a guarantee.
              </p>
            </>
          ) : (
            <p className="text-xs text-content-muted">
              The machine load is measured on demand.
            </p>
          )}
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title="Limits"
          description="How much of the machine the jobs may use."
        />
        <CardBody>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <Field
              label="Maximum parallel browser jobs"
              hint="The worker never starts more than this many browser jobs at the same time."
            >
              <Input
                type="number"
                min={1}
                max={16}
                defaultValue={execution?.max_browser_jobs ?? 2}
                onBlur={(event) => {
                  const value = Number(event.target.value);
                  if (value >= 1 && value !== execution?.max_browser_jobs) {
                    void save({ max_browser_jobs: value });
                  }
                }}
              />
            </Field>
            <Field
              label="Resource preference"
              hint="Lower values keep the machine responsive."
            >
              <Select
                defaultValue={execution?.resource_preference ?? "balanced"}
                onChange={(event) =>
                  void save({
                    resource_preference: event.target
                      .value as ExecutionSettings["resource_preference"],
                  })
                }
              >
                <option value="max_speed">Maximum speed</option>
                <option value="balanced">Balanced</option>
                <option value="save_resources">Save resources</option>
              </Select>
            </Field>
            <Field
              label="Jobs per domain"
              hint="Parallel jobs that may touch the same website."
            >
              <Input
                type="number"
                min={1}
                max={10}
                defaultValue={execution?.per_domain_limit ?? 1}
                onBlur={(event) => {
                  const value = Number(event.target.value);
                  if (value >= 1 && value !== execution?.per_domain_limit) {
                    void save({ per_domain_limit: value });
                  }
                }}
              />
            </Field>
            <Field
              label="Requests per domain / minute"
              hint="Throttle for one website."
            >
              <Input
                type="number"
                min={1}
                max={120}
                defaultValue={execution?.per_domain_requests_per_minute ?? 10}
                onBlur={(event) => {
                  const value = Number(event.target.value);
                  if (
                    value >= 1 &&
                    value !== execution?.per_domain_requests_per_minute
                  ) {
                    void save({ per_domain_requests_per_minute: value });
                  }
                }}
              />
            </Field>
            <Field
              label="Job timeout (seconds)"
              hint="A longer job is cancelled."
            >
              <Input
                type="number"
                min={30}
                max={3600}
                defaultValue={execution?.task_timeout_seconds ?? 240}
                onBlur={(event) => {
                  const value = Number(event.target.value);
                  if (value >= 30 && value !== execution?.task_timeout_seconds) {
                    void save({ task_timeout_seconds: value });
                  }
                }}
              />
            </Field>
            <Field
              label="Browser mode"
              hint="The headed mode uses an isolated profile as well - never your personal browser."
            >
              <Select
                defaultValue={execution?.headless ? "headless" : "headed"}
                onChange={(event) =>
                  void save({ headless: event.target.value === "headless" })
                }
              >
                <option value="headless">Headless (default)</option>
                <option value="headed">Headed, isolated profile</option>
              </Select>
            </Field>
          </div>
        </CardBody>
      </Card>
    </div>
  );
}
