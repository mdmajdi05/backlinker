"use client";

import * as React from "react";
import { api } from "@autobacklinker/api-client";
import type { ExecutionEnvironment, ProjectSettings } from "@autobacklinker/shared-types";
import {
  Button,
  Checkbox,
  Field,
  Input,
  Label,
  Select,
} from "@autobacklinker/ui";
import { apiClient, errorMessage } from "@/lib/api";
import { useAction } from "@/lib/hooks";
import { useToast } from "@autobacklinker/ui";

const WEEKDAYS = [
  { value: 1, label: "Mon" },
  { value: 2, label: "Tue" },
  { value: 3, label: "Wed" },
  { value: 4, label: "Thu" },
  { value: 5, label: "Fri" },
  { value: 6, label: "Sat" },
  { value: 7, label: "Sun" },
];

const DEFAULTS: ProjectSettings = {
  id: "",
  project_id: "",
  max_concurrency: 3,
  global_concurrency: 5,
  per_domain_concurrency: 1,
  per_provider_concurrency: 2,
  request_rate_per_minute: 60,
  max_retries: 3,
  backoff_base_seconds: 30,
  jitter_seconds: 5,
  operating_schedule: { days: [1, 2, 3, 4, 5], start_hour: 9, end_hour: 18 },
  verify_interval_hours: 24,
  verify_backoff_hours: 6,
  daily_discovery_limit: 200,
  allow_browser_automation: false,
  require_approval: true,
  execution_environment: "CLOUD",
  auto_queue_approved: false,
  timezone: "UTC",
};

export function ProjectSettingsForm({
  projectId,
  settings,
}: {
  projectId: string;
  settings: ProjectSettings | null;
}) {
  const toast = useToast();
  const action = useAction();
  const [form, setForm] = React.useState<ProjectSettings>(() => ({
    ...DEFAULTS,
    ...(settings ?? {}),
    operating_schedule: {
      ...DEFAULTS.operating_schedule,
      ...(settings?.operating_schedule ?? {}),
    },
  }));

  React.useEffect(() => {
    setForm({
      ...DEFAULTS,
      ...(settings ?? {}),
      operating_schedule: {
        ...DEFAULTS.operating_schedule,
        ...(settings?.operating_schedule ?? {}),
      },
    });
  }, [settings]);

  const update = <K extends keyof ProjectSettings>(key: K, value: ProjectSettings[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  const numberField = (
    key: keyof ProjectSettings,
    label: string,
    hint?: string,
  ): React.ReactElement => (
    <Field label={label} hint={hint}>
      <Input
        type="number"
        min={0}
        value={String(form[key] ?? "")}
        onChange={(event) => {
          const parsed = Number.parseInt(event.target.value, 10);
          update(key, (Number.isFinite(parsed) ? parsed : 0) as ProjectSettings[typeof key]);
        }}
      />
    </Field>
  );

  const save = async () => {
    const outcome = await action.run(() => api.projects.updateSettings(apiClient, projectId, form));
    if (outcome.ok) {
      toast.push("Project settings saved", "success");
    }
  };

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {numberField("max_concurrency", "Max concurrency")}
        {numberField("global_concurrency", "Global concurrency")}
        {numberField("per_domain_concurrency", "Per-domain concurrency")}
        {numberField("per_provider_concurrency", "Per-provider concurrency")}
        {numberField("request_rate_per_minute", "Requests / minute")}
        {numberField("max_retries", "Max retries")}
        {numberField("backoff_base_seconds", "Backoff base (s)")}
        {numberField("jitter_seconds", "Jitter (s)")}
        {numberField("verify_interval_hours", "Verification interval (h)")}
        {numberField("verify_backoff_hours", "Verification backoff (h)")}
        {numberField("daily_discovery_limit", "Daily discovery limit")}
        <Field label="Timezone">
          <Input
            value={form.timezone}
            onChange={(event) => update("timezone", event.target.value)}
            placeholder="UTC"
          />
        </Field>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Execution environment">
          <Select
            value={form.execution_environment}
            onChange={(event) =>
              update("execution_environment", event.target.value as ExecutionEnvironment)
            }
          >
            <option value="CLOUD">Cloud worker</option>
            <option value="LOCAL">Local agent</option>
          </Select>
        </Field>

        <div className="space-y-2 pt-5">
          <Label className="flex items-center gap-2 text-content">
            <Checkbox
              checked={form.require_approval}
              onChange={(event) => update("require_approval", event.target.checked)}
            />
            Require approval
          </Label>
          <Label className="flex items-center gap-2 text-content">
            <Checkbox
              checked={form.auto_queue_approved}
              onChange={(event) => update("auto_queue_approved", event.target.checked)}
            />
            Auto-queue approved
          </Label>
          <p className="text-xs text-content-subtle">
            Puts every approved opportunity into the queue. The automatic submission - queueing
            and submitting in the background - is configured in the Auto pilot card above.
          </p>
          <Label className="flex items-center gap-2 text-content">
            <Checkbox
              checked={form.allow_browser_automation}
              onChange={(event) => update("allow_browser_automation", event.target.checked)}
            />
            Allow browser automation
          </Label>
        </div>
      </div>

      <div className="rounded-md border border-line p-3">
        <p className="mb-2 text-xs font-semibold text-content">Operating schedule</p>
        <div className="flex flex-wrap gap-2">
          {WEEKDAYS.map((day) => {
            const active = form.operating_schedule.days.includes(day.value);
            return (
              <button
                key={day.value}
                type="button"
                aria-pressed={active}
                onClick={() => {
                  const days = active
                    ? form.operating_schedule.days.filter((d) => d !== day.value)
                    : [...form.operating_schedule.days, day.value].sort((a, b) => a - b);
                  update("operating_schedule", { ...form.operating_schedule, days });
                }}
                className={`h-8 w-11 rounded-md border text-xs font-medium transition-colors ${
                  active
                    ? "border-accent bg-accent-soft text-accent"
                    : "border-line text-content-muted hover:bg-surface-sunken"
                }`}
              >
                {day.label}
              </button>
            );
          })}
        </div>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <Field label="Start hour (0-23)">
            <Input
              type="number"
              min={0}
              max={23}
              value={form.operating_schedule.start_hour}
              onChange={(event) =>
                update("operating_schedule", {
                  ...form.operating_schedule,
                  start_hour: Number.parseInt(event.target.value, 10) || 0,
                })
              }
            />
          </Field>
          <Field label="End hour (0-23)">
            <Input
              type="number"
              min={0}
              max={23}
              value={form.operating_schedule.end_hour}
              onChange={(event) =>
                update("operating_schedule", {
                  ...form.operating_schedule,
                  end_hour: Number.parseInt(event.target.value, 10) || 0,
                })
              }
            />
          </Field>
        </div>
      </div>

      {action.error ? (
        <p role="alert" className="rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-xs text-danger">
          {errorMessage(action.error)}
        </p>
      ) : null}

      <div className="flex justify-end gap-2 border-t border-line pt-3">
        <Button variant="outline" onClick={() => setForm({
          ...DEFAULTS,
          ...(settings ?? {}),
          operating_schedule: {
            ...DEFAULTS.operating_schedule,
            ...(settings?.operating_schedule ?? {}),
          },
        })}>
          Reset
        </Button>
        <Button onClick={save} loading={action.pending}>
          Save settings
        </Button>
      </div>
    </div>
  );
}
