"use client";

import * as React from "react";
import { api } from "@autobacklinker/api-client";
import type { WorkerStatus } from "@autobacklinker/shared-types";
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
import { apiClient, errorMessage } from "@/lib/api";
import { useResource } from "@/lib/hooks";

/**
 * Controls of the background automation.
 *
 * The browser that the platform uses is always an isolated browser of this
 * application - the personal browser of the operator is never opened or
 * controlled.  This panel shows that guarantee, the resource usage of the
 * machine and the switches that decide how much of the machine the jobs may
 * use.
 */
export function AutomationPanel() {
  const toast = useToast();
  const [busy, setBusy] = React.useState<string | null>(null);
  const [installLog, setInstallLog] = React.useState<string | null>(null);

  const status = useResource(() => api.automation.workerStatus(apiClient), []);

  const reload = () => status.reload();

  const run = async (key: string, action: () => Promise<unknown>, message: string) => {
    setBusy(key);
    try {
      await action();
      toast.push(message, "success");
      reload();
    } catch (err) {
      toast.push(errorMessage(err), "error");
    } finally {
      setBusy(null);
    }
  };

  const save = async (changes: Record<string, unknown>) => {
    setBusy("settings");
    try {
      await api.automation.updateSettings(apiClient, changes as never);
      toast.push("Automation settings saved", "success");
      reload();
    } catch (err) {
      toast.push(errorMessage(err), "error");
    } finally {
      setBusy(null);
    }
  };

  const installBrowser = async () => {
    setBusy("browser");
    setInstallLog(null);
    try {
      const result = await api.automation.installBrowser(apiClient);
      setInstallLog(result.message ?? "The browser runtime was installed.");
      toast.push("The browser runtime was installed", "success");
      reload();
    } catch (err) {
      setInstallLog(errorMessage(err));
      toast.push("The browser runtime could not be installed", "error");
    } finally {
      setBusy(null);
    }
  };

  const data: WorkerStatus | null = status.data ?? null;
  const execution = data?.execution;
  const resources = data?.resources;
  const browser = data?.browser;

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader
          title="Background execution"
          description="Pause, resume or stop every automation job - locally and in the cloud."
          action={
            <div className="flex items-center gap-2">
              <Button
                size="sm"
                variant="outline"
                disabled={busy !== null || execution?.state === "PAUSED"}
                loading={busy === "pause"}
                onClick={() => run("pause", () => api.automation.pause(apiClient), "Automation paused")}
              >
                Pause all
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={busy !== null || execution?.state === "RUNNING"}
                loading={busy === "resume"}
                onClick={() => run("resume", () => api.automation.resume(apiClient), "Automation resumed")}
              >
                Resume
              </Button>
              <Button
                size="sm"
                variant="danger"
                disabled={busy !== null || execution?.state === "STOPPED"}
                loading={busy === "stop"}
                onClick={() => run("stop", () => api.automation.stop(apiClient), "Automation stopped")}
              >
                Stop
              </Button>
            </div>
          }
        />
        <CardBody>
          {status.error ? (
            <Alert tone="danger" title="The execution state could not be read">
              {errorMessage(status.error)}
            </Alert>
          ) : null}

          <div className="flex flex-wrap items-center gap-3">
            <Badge tone={execution?.state === "RUNNING" ? "success" : "warning"}>
              {execution?.state ?? "…"}
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
                ["Running browser jobs", String(data?.running_browser_jobs ?? 0)],
                ["Parallel browser jobs", String(resources?.effective_limit ?? 0)],
                ["Configured limit", String(resources?.configured_limit ?? 0)],
              ]}
            />
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title="Browser isolation"
          description="The automation runs in a browser that belongs to this application."
        />
        <CardBody className="space-y-3">
          <Alert tone="info" title="Your personal browser is never touched">
            {browser?.isolation?.note ??
              "The automation uses its own browser with a throw away profile."}
          </Alert>
          <div className="grid gap-3 sm:grid-cols-2">
            <KeyValue
              items={[
                ["Runtime", browser?.available ? "installed" : "not installed"],
                ["Mode", browser?.headless ? "headless (default)" : "headed (isolated profile)"],
                ["Own profile directory", browser?.profile_dir ?? "-"],
                ["Browser build directory", browser?.browsers_dir ?? "-"],
              ]}
            />
            <div className="space-y-2">
              <p className="text-xs text-content-muted">
                The browser build is downloaded once into the directory of this
                installation. It is not shared with the browser of the operating
                system.
              </p>
              <Button
                size="sm"
                disabled={busy !== null}
                loading={busy === "browser"}
                onClick={() => void installBrowser()}
              >
                {browser?.available ? "Reinstall browser runtime" : "Install browser runtime"}
              </Button>
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
        <CardBody className="space-y-3">
          {resources ? (
            <>
              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <div className="mb-1 flex items-center justify-between text-xs">
                    <span className="text-content-muted">CPU</span>
                    <span className="text-content">{resources.resources.cpu_percent}%</span>
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
                  <ProgressBar value={resources.resources.memory_used_percent / 100} />
                </div>
              </div>
              <p className="text-xs text-content-muted">{resources.reason}</p>
              <p className="text-[11px] text-content-subtle">
                The limit is enforced by the worker before a job is claimed. It
                cannot stop a single browser process from using CPU, so it is a
                target and not a guarantee.
              </p>
            </>
          ) : (
            <p className="text-xs text-content-muted">The machine load is measured on demand.</p>
          )}
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Limits" description="How much of the machine the jobs may use." />
        <CardBody className="space-y-3">
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
            <Field label="Resource preference" hint="Lower values keep the machine responsive.">
              <Select
                defaultValue={execution?.resource_preference ?? "balanced"}
                onChange={(event) => void save({ resource_preference: event.target.value })}
              >
                <option value="max_speed">Maximum speed</option>
                <option value="balanced">Balanced</option>
                <option value="save_resources">Save resources</option>
              </Select>
            </Field>
            <Field label="Jobs per domain" hint="Parallel jobs that may touch the same website.">
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
            <Field label="Requests per domain / minute" hint="Throttle for one website.">
              <Input
                type="number"
                min={1}
                max={120}
                defaultValue={execution?.per_domain_requests_per_minute ?? 10}
                onBlur={(event) => {
                  const value = Number(event.target.value);
                  if (value >= 1 && value !== execution?.per_domain_requests_per_minute) {
                    void save({ per_domain_requests_per_minute: value });
                  }
                }}
              />
            </Field>
            <Field label="Job timeout (seconds)" hint="A longer job is cancelled.">
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
                onChange={(event) => void save({ headless: event.target.value === "headless" })}
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
