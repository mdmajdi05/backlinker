import * as React from "react";
import {
  Alert,
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  Checkbox,
  Field,
  Input,
  KeyValue,
  Label,
  MetricTile,
  Select,
  StatusBadge,
  Table,
  Td,
  Th,
  useToast,
} from "@autobacklinker/ui";
import { api, apiClient } from "../lib/api";
import { useAsync } from "../lib/useAsync";
import { ErrorBlock, LoadingBlock, NothingYet, PageHeader } from "../components/common";
import { AutoPilotPanel } from "../components/AutoPilotPanel";
import { CampaignPanel } from "../components/CampaignPanel";
import { AddToProjectDialog } from "../components/AddToProjectDialog";
import {
  ProjectDeleteDialog,
  ProjectEditDialog,
} from "../components/ProjectEditDialog";
import { formatDate, formatNumber, titleCase } from "../lib/format";
import { navigate } from "../lib/router";
import { openPath, sendNativeNotification } from "../lib/backend";
import { fetchWebsites, fetchWebsiteStats, websiteStatusLabel } from "../lib/websites";
import { isMissingEndpoint } from "../lib/api";
import { openReportForProject } from "./ReportsPage";
import type {
  BusinessProfile,
  ExecutionEnvironment,
  Opportunity,
  Project,
  ProjectSettings,
  TargetWebsite,
} from "@autobacklinker/shared-types";

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

function errorText(error: unknown, fallback: string): string {
  if (error && typeof error === "object" && "message" in error) {
    return String((error as { message: unknown }).message);
  }
  return fallback;
}

async function openExternal(url: string): Promise<void> {
  try {
    await openPath(url);
  } catch {
    window.open(url, "_blank", "noopener,noreferrer");
  }
}

function SettingsForm({
  projectId,
  settings,
}: {
  projectId: string;
  settings: ProjectSettings | null;
}) {
  const toast = useToast();
  const [form, setForm] = React.useState<ProjectSettings>(() => ({
    ...DEFAULTS,
    ...(settings ?? {}),
    operating_schedule: {
      ...DEFAULTS.operating_schedule,
      ...(settings?.operating_schedule ?? {}),
    },
  }));
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

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

  const update = <K extends keyof ProjectSettings>(
    key: K,
    value: ProjectSettings[K],
  ) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  const numberField = (
    key: keyof ProjectSettings,
    label: string,
    hint?: string,
  ) => (
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

  async function save() {
    setError(null);
    setSaving(true);
    try {
      await api.projects.updateSettings(apiClient, projectId, {
        max_concurrency: form.max_concurrency,
        global_concurrency: form.global_concurrency,
        per_domain_concurrency: form.per_domain_concurrency,
        per_provider_concurrency: form.per_provider_concurrency,
        request_rate_per_minute: form.request_rate_per_minute,
        max_retries: form.max_retries,
        backoff_base_seconds: form.backoff_base_seconds,
        jitter_seconds: form.jitter_seconds,
        operating_schedule: form.operating_schedule,
        verify_interval_hours: form.verify_interval_hours,
        verify_backoff_hours: form.verify_backoff_hours,
        daily_discovery_limit: form.daily_discovery_limit,
        allow_browser_automation: form.allow_browser_automation,
        require_approval: form.require_approval,
        execution_environment: form.execution_environment,
        auto_queue_approved: form.auto_queue_approved,
        timezone: form.timezone,
      });
      toast.push("Project settings saved", "success");
      void sendNativeNotification(
        "Auto Backlinker",
        `The settings of ${projectId} were saved.`,
      );
    } catch (err) {
      setError(errorText(err, "Could not save the project settings"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {numberField("max_concurrency", "Max concurrency", "Parallel tasks of this project")}
        {numberField("global_concurrency", "Global concurrency")}
        {numberField("per_domain_concurrency", "Per-domain concurrency")}
        {numberField("per_provider_concurrency", "Per-provider concurrency")}
        {numberField("request_rate_per_minute", "Requests / minute", "Rate limit")}
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
        <Field
          label="Execution environment"
          hint="LOCAL runs the work on this machine, CLOUD needs a hosted worker."
        >
          <Select
            value={form.execution_environment}
            onChange={(event) =>
              update(
                "execution_environment",
                event.target.value as ExecutionEnvironment,
              )
            }
          >
            <option value="LOCAL">Local agent (this device)</option>
            <option value="CLOUD">Cloud worker</option>
          </Select>
        </Field>

        <div className="flex flex-col gap-2 pt-5">
          <Label className="flex items-center gap-2 text-content">
            <Checkbox
              checked={form.require_approval}
              onChange={(event) =>
                update("require_approval", event.target.checked)
              }
            />
            Require approval
          </Label>
          <Label className="flex items-center gap-2 text-content">
            <Checkbox
              checked={form.auto_queue_approved}
              onChange={(event) =>
                update("auto_queue_approved", event.target.checked)
              }
            />
            Auto-queue approved
          </Label>
          <Label className="flex items-center gap-2 text-content">
            <Checkbox
              checked={form.allow_browser_automation}
              onChange={(event) =>
                update("allow_browser_automation", event.target.checked)
              }
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
                    : [...form.operating_schedule.days, day.value].sort(
                        (a, b) => a - b,
                      );
                  update("operating_schedule", {
                    ...form.operating_schedule,
                    days,
                  });
                }}
                className={
                  active
                    ? "h-8 w-11 rounded-md border border-accent bg-accent-soft text-xs font-medium text-accent"
                    : "h-8 w-11 rounded-md border border-line text-xs font-medium text-content-muted transition-colors hover:bg-surface-sunken"
                }
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

      {error ? (
        <p className="rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-xs text-danger">
          {error}
        </p>
      ) : null}

      <div className="flex justify-end gap-2 border-t border-line pt-3">
        <Button
          variant="outline"
          onClick={() =>
            setForm({
              ...DEFAULTS,
              ...(settings ?? {}),
              operating_schedule: {
                ...DEFAULTS.operating_schedule,
                ...(settings?.operating_schedule ?? {}),
              },
            })
          }
        >
          Reset
        </Button>
        <Button loading={saving} onClick={save}>
          Save settings
        </Button>
      </div>
    </div>
  );
}

export function ProjectDetailPage({ projectId }: { projectId: string }) {
  const toast = useToast();
  const [choosingWebsites, setChoosingWebsites] = React.useState(false);
  const [editing, setEditing] = React.useState(false);
  const [deleting, setDeleting] = React.useState(false);
  const [deletingBusy, setDeletingBusy] = React.useState(false);
  const [deleteError, setDeleteError] = React.useState<string | null>(null);
  /* Bumped after the website picker added rows, so the campaign shows them
     immediately instead of waiting for its next refresh. */
  const [campaignReload, setCampaignReload] = React.useState(0);

  const project = useAsync(
    () => api.projects.get(apiClient, projectId),
    [projectId],
  );
  const settings = useAsync(
    () => api.projects.settings(apiClient, projectId),
    [projectId],
  );
  const projectDetails = useAsync(
    () => api.projects.details(apiClient, projectId),
    [projectId],
  );
  const metrics = useAsync(
    () => api.dashboard.metrics(apiClient, projectId),
    [projectId],
  );
  const opportunities = useAsync(
    () =>
      api.opportunities.list(apiClient, {
        page: 1,
        page_size: 200,
        project_id: projectId,
      }),
    [projectId],
  );
  const websites = useAsync(
    () =>
      api.projects.websites(apiClient, projectId, {
        page: 1,
        page_size: 100,
      }),
    [projectId],
  );
  const allProjects = useAsync(
    () => api.projects.list(apiClient, { page: 1, page_size: 100 }),
    [],
  );
  const linkedWebsites = useAsync(
    () => fetchWebsites({ page: 1, page_size: 100, project_id: projectId }),
    [projectId],
  );
  // The report of the project: the counters of every website it works on.
  const reportStats = useAsync(
    () => fetchWebsiteStats(projectId),
    [projectId],
  );
  const profile = useAsync(
    () => {
      const id = project.data?.business_profile_id;
      return id
        ? api.profiles.get(apiClient, id)
        : Promise.resolve(null as BusinessProfile | null);
    },
    [project.data?.business_profile_id],
  );

  const data: Project | null = project.data;
  const counts = data?.counts;

  // The landing pages of the project come from the backend. The business
  // profile and the opportunities may mention additional pages - they are
  // shown as a hint, never as a registered landing page.
  const landingPages: TargetWebsite[] = websites.data?.items ?? [];

  const suggestedPages = React.useMemo<string[]>(() => {
    const pages = new Set<string>();
    (profile.data?.primary_landing_pages ?? []).forEach((url) =>
      pages.add(url.trim()),
    );
    (profile.data?.secondary_landing_pages ?? []).forEach((url) =>
      pages.add(url.trim()),
    );
    (opportunities.data?.items ?? []).forEach((item: Opportunity) => {
      if (item.target_landing_page) pages.add(item.target_landing_page.trim());
    });
    landingPages.forEach((site) => pages.delete(site.url.trim()));
    return Array.from(pages).filter(Boolean);
  }, [profile.data, opportunities.data, landingPages]);

  // The websites of the report - the failing ones come first.
  const reportRows = React.useMemo(() => {
    return [...(reportStats.data ?? [])].sort((a, b) => {
      if (b.failed !== a.failed) return b.failed - a.failed;
      if (b.pending !== a.pending) return b.pending - a.pending;
      return (a.domain || a.name || "").localeCompare(b.domain || b.name || "");
    });
  }, [reportStats.data]);

  // The counters of the project - the sum of the rows above.
  const reportTotals = React.useMemo(() => {
    return (reportStats.data ?? []).reduce(
      (acc, row) => ({
        opportunities: acc.opportunities + row.opportunities,
        submitted: acc.submitted + row.submitted,
        verified: acc.verified + row.verified,
        failed: acc.failed + row.failed,
        pending: acc.pending + row.pending,
      }),
      { opportunities: 0, submitted: 0, verified: 0, failed: 0, pending: 0 },
    );
  }, [reportStats.data]);

  async function deleteProject() {
    if (!data) return;
    setDeletingBusy(true);
    setDeleteError(null);
    try {
      await api.projects.remove(apiClient, data.id);
      toast.push(`Project "${data.name}" deleted`, "success");
      void sendNativeNotification(
        "Auto Backlinker",
        `The project ${data.name} was deleted. The websites stay in the website list.`,
      );
      setDeleting(false);
      navigate("projects");
    } catch (err) {
      setDeleteError(errorText(err, "Could not delete the project"));
    } finally {
      setDeletingBusy(false);
    }
  }

  if (project.loading && !data) {
    return (
      <div className="flex flex-col gap-4">
        <PageHeader title="Project" description="Loading the project…" />
        <LoadingBlock rows={6} />
      </div>
    );
  }

  if (project.error && !data) {
    return (
      <div className="flex flex-col gap-4">
        <PageHeader title="Project" description="The project could not be loaded." />
        <ErrorBlock message={project.error} onRetry={project.reload} />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title={data?.name ?? "Project"}
        description={data?.target_website ?? "Project details"}
        actions={
          <>
            <Button
              size="sm"
              variant="outline"
              onClick={() => navigate("projects")}
            >
              Back to projects
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={!data}
              onClick={() => setEditing(true)}
            >
              Edit details
            </Button>
            <Button
              size="sm"
              variant="outline"
              className="text-danger"
              disabled={!data}
              onClick={() => {
                setDeleteError(null);
                setDeleting(true);
              }}
            >
              Delete project
            </Button>
            <Button size="sm" variant="outline" onClick={project.reload}>
              Refresh
            </Button>
          </>
        }
      />

      {project.error ? (
        <ErrorBlock message={project.error} onRetry={project.reload} />
      ) : null}

      {data ? (
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge status={data.status} />
          <button
            type="button"
            onClick={() => void openExternal(data.target_website)}
            className="max-w-[420px] truncate text-xs text-accent underline-offset-2 hover:underline"
            title={data.target_website}
          >
            {data.target_website}
          </button>
          <Badge tone="neutral">v{data.version}</Badge>
          <Badge tone="neutral">
            {data.settings?.execution_environment ?? "CLOUD"}
          </Badge>
          {data.description ? (
            <span className="text-xs text-content-muted">{data.description}</span>
          ) : null}
        </div>
      ) : null}

      <Card>
        <CardHeader
          title="1. Project details"
          description="This project keeps its own company details. Every website below reuses them."
          action={
            <Button size="sm" variant="outline" onClick={() => setEditing(true)} disabled={!data}>
              Edit details
            </Button>
          }
        />
        <CardBody>
          {projectDetails.error ? (
            <Alert tone="warning" title="The project details could not be loaded">
              {projectDetails.error}
            </Alert>
          ) : null}
          {projectDetails.data ? (
            <div className="flex flex-col gap-3">
              <div className="grid grid-cols-2 gap-3 text-xs md:grid-cols-4">
                {[
                  ["Company", projectDetails.data.company_name],
                  ["Website", projectDetails.data.website || data?.target_website || ""],
                  ["E-mail", projectDetails.data.email],
                  ["Phone", projectDetails.data.phone],
                  ["City", projectDetails.data.city],
                  ["State / region", projectDetails.data.state],
                  ["Country", projectDetails.data.country],
                  ["Anchors", projectDetails.data.anchors.join(", ")],
                ].map(([label, value]) => (
                  <div key={label} className="rounded-md border border-line px-3 py-2">
                    <p className="text-[10px] uppercase tracking-wider text-content-subtle">
                      {label}
                    </p>
                    <p className="truncate text-content" title={value || "Not filled"}>
                      {value || <span className="text-warning">Not filled</span>}
                    </p>
                  </div>
                ))}
              </div>
              {projectDetails.data.required.length > 0 ? (
                <div className="flex flex-wrap items-center justify-between gap-2 text-[11px]">
                  <span className="text-content-muted">
                    {projectDetails.data.filled.length} of{" "}
                    {projectDetails.data.required.length} required values are ready.
                  </span>
                  {projectDetails.data.missing.length > 0 ? (
                    <span className="text-warning">
                      Missing: {projectDetails.data.missing.map(titleCase).join(", ")}
                    </span>
                  ) : (
                    <span className="text-success">Every required value is ready.</span>
                  )}
                </div>
              ) : (
                <p className="text-[11px] text-content-muted">
                  Assign websites below and this card shows which details they ask for.
                </p>
              )}
            </div>
          ) : (
            <p className="text-xs text-content-subtle">Loading project details…</p>
          )}
        </CardBody>
      </Card>

      <CampaignPanel
        projectId={projectId}
        onChanged={() => {
          project.reload();
          linkedWebsites.reload();
          reportStats.reload();
          opportunities.reload();
        }}
        onPickFromList={() => setChoosingWebsites(true)}
        onOpenReport={() => openReportForProject(projectId)}
        reloadToken={campaignReload}
      />

      <details className="rounded-lg border border-line bg-surface">
        <summary className="cursor-pointer list-none px-4 py-3">
          <span className="text-sm font-semibold text-content">
            More tools (optional): counts, report, auto pilot and settings
          </span>
          <span className="ml-2 text-xs font-normal text-content-muted">
            Optional - the campaign above works without it.
          </span>
        </summary>
        <div className="flex flex-col gap-4 border-t border-line p-4">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-8">
        <MetricTile
          label="Websites"
          value={formatNumber(counts?.opportunities)}
        />
        <MetricTile label="Approved" value={formatNumber(counts?.approved)} />
        <MetricTile label="Queued" value={formatNumber(counts?.queued)} />
        <MetricTile
          label="Running"
          value={formatNumber(counts?.running)}
          tone="info"
        />
        <MetricTile
          label="Completed"
          value={formatNumber(counts?.completed)}
          tone="success"
        />
        <MetricTile
          label="Failed"
          value={formatNumber(counts?.failed)}
          tone="danger"
        />
        <MetricTile
          label="Verified live"
          value={formatNumber(counts?.verified_live)}
          tone="success"
        />
        <MetricTile
          label="Pending manual"
          value={formatNumber(counts?.pending_manual)}
          tone="warning"
        />
      </div>

      <Card>
        <CardHeader
          title="Project statistics"
          description="Live counters for this project"
        />
        <CardBody>
          {metrics.loading && !metrics.data ? (
            <p className="text-xs text-content-subtle">Loading metrics…</p>
          ) : metrics.error ? (
            <ErrorBlock message={metrics.error} onRetry={metrics.reload} />
          ) : metrics.data ? (
            <KeyValue
              items={[
                ["Generated at", formatDate(metrics.data.generated_at)],
                ["Awaiting retry", formatNumber(metrics.data.awaiting_retry)],
                [
                  "Requiring verification",
                  formatNumber(metrics.data.requiring_verification),
                ],
                ["Published", formatNumber(metrics.data.published)],
                ["Pending manual", formatNumber(metrics.data.pending_manual)],
                ["Connected devices", formatNumber(metrics.data.connected_devices)],
                ["Cloud workers", formatNumber(metrics.data.cloud_workers)],
                ["Running local jobs", formatNumber(metrics.data.running_local_jobs)],
              ]}
            />
          ) : (
            <p className="text-xs text-content-subtle">No statistics available.</p>
          )}
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title="Report & results"
          description="What happened in this project - the totals of every website"
          action={
            <Button
              size="sm"
              variant="outline"
              onClick={() => openReportForProject(projectId)}
            >
              Open the full report
            </Button>
          }
        />
        <CardBody className="p-0">
          {reportStats.loading && !reportStats.data ? (
            <div className="p-4">
              <LoadingBlock rows={3} />
            </div>
          ) : null}

          {reportStats.error ? (
            <div className="p-4">
              <ErrorBlock
                message={reportStats.error}
                onRetry={reportStats.reload}
              />
            </div>
          ) : null}

          {reportStats.data ? (
            <>
              <div className="grid grid-cols-2 gap-3 border-b border-line p-4 md:grid-cols-5">
                <MetricTile
                  label="Websites"
                  value={formatNumber(reportTotals.opportunities)}
                />
                <MetricTile
                  label="Submitted"
                  value={formatNumber(reportTotals.submitted)}
                  tone="accent"
                />
                <MetricTile
                  label="Verified"
                  value={formatNumber(reportTotals.verified)}
                  tone="success"
                />
                <MetricTile
                  label="Failed"
                  value={formatNumber(reportTotals.failed)}
                  tone="danger"
                />
                <MetricTile
                  label="Pending"
                  value={formatNumber(reportTotals.pending)}
                  tone="warning"
                />
              </div>

              {reportRows.length === 0 ? (
                <div className="p-4">
                  <NothingYet
                    title="Nothing happened yet"
                    description="The report fills as soon as a website of this project is worked on. Every website is listed below with its own counters."
                    action={
                      <Button
                        size="sm"
                        onClick={() => setChoosingWebsites(true)}
                      >
                        Add from the website list
                      </Button>
                    }
                  />
                </div>
              ) : null}
            </>
          ) : null}

          <p className="border-t border-line px-4 py-3 text-xs text-content-muted">
            Verified links are never submitted again. Use Opportunity import to
            bring a report back in - verified rows are skipped, failed rows are
            retried.
          </p>
        </CardBody>
      </Card>

      <AutoPilotPanel projectId={projectId} />

      <Card>
        <CardHeader
          title="Execution settings"
          description="Concurrency, rate limit, retries, backoff and verification cadence"
        />
        <CardBody>
          {settings.loading && !settings.data ? (
            <p className="text-xs text-content-subtle">Loading settings…</p>
          ) : settings.error ? (
            <ErrorBlock message={settings.error} onRetry={settings.reload} />
          ) : (
            <SettingsForm
              projectId={projectId}
              settings={settings.data ?? data?.settings ?? null}
            />
          )}
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title="Landing pages"
          description="The pages of this project the backlinks may point to"
        />
        <CardBody className="p-0">
          {websites.loading && !websites.data ? (
            <div className="p-4">
              <LoadingBlock rows={2} />
            </div>
          ) : null}

          {landingPages.length > 0 ? (
            <Table>
              <thead>
                <tr>
                  <Th>Name</Th>
                  <Th>URL</Th>
                  <Th>Kind</Th>
                  <Th>State</Th>
                </tr>
              </thead>
              <tbody>
                {landingPages.map((site) => (
                  <tr key={site.id}>
                    <Td className="max-w-[200px] truncate text-xs">
                      {site.name}
                    </Td>
                    <Td className="max-w-[320px]">
                      <button
                        type="button"
                        onClick={() => void openExternal(site.url)}
                        className="block max-w-full truncate text-xs text-accent underline-offset-2 hover:underline"
                        title={site.url}
                      >
                        {site.url}
                      </button>
                    </Td>
                    <Td>
                      <Badge tone="neutral">{titleCase(site.kind)}</Badge>
                    </Td>
                    <Td>
                      <Badge tone={site.is_active ? "success" : "neutral"}>
                        {site.is_active ? "Active" : "Inactive"}
                      </Badge>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          ) : null}

          {!websites.loading && landingPages.length === 0 ? (
            websites.error ? (
              <div className="p-4">
                <Alert
                  tone="warning"
                  title="The backend does not report the landing pages of a project"
                >
                  {websites.error} The pages below are derived from the
                  business profile and from the opportunities of this project.
                </Alert>
              </div>
            ) : (
              <NothingYet
                title="No landing pages"
                description="This project has no target page yet. The setup wizard registers the primary landing pages of the business profile."
                action={
                  <Button size="sm" onClick={() => navigate("onboarding")}>
                    Open the setup wizard
                  </Button>
                }
              />
            )
          ) : null}

          {suggestedPages.length > 0 ? (
            <div className="border-t border-line px-4 py-3">
              <p className="mb-2 text-xs font-semibold text-content">
                Mentioned by the profile and the opportunities
              </p>
              <ul className="flex flex-col gap-1">
                {suggestedPages.map((url) => (
                  <li key={url}>
                    <button
                      type="button"
                      onClick={() => void openExternal(url)}
                      className="block max-w-full truncate text-xs text-content-muted underline-offset-2 hover:text-accent hover:underline"
                      title={url}
                    >
                      {url}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title="Websites of this project"
          description="The sites this project works on - they are picked from the central website list."
          action={
            <Button
              size="sm"
              variant="outline"
              onClick={() => setChoosingWebsites(true)}
            >
              Add from the website list
            </Button>
          }
        />
        <CardBody className="p-0">
          {linkedWebsites.loading && !linkedWebsites.data ? (
            <div className="p-4">
              <LoadingBlock rows={2} />
            </div>
          ) : null}

          {linkedWebsites.error ? (
            <div className="p-4">
              {isMissingEndpoint(linkedWebsites.error) ? (
                <Alert
                  tone="warning"
                  title="The local backend does not know the website list yet"
                >
                  The endpoint <code>/api/v1/websites</code> answers with 404.
                  The central list of the websites - and with it the button that
                  adds them to a project - needs a newer backend.
                </Alert>
              ) : (
                <ErrorBlock
                  message={linkedWebsites.error}
                  onRetry={linkedWebsites.reload}
                />
              )}
            </div>
          ) : null}

          {linkedWebsites.data && linkedWebsites.data.items.length > 0 ? (
            <Table>
              <thead>
                <tr>
                  <Th>Website</Th>
                  <Th>Category</Th>
                  <Th>Niche</Th>
                  <Th>State</Th>
                  <Th className="text-right">Submitted</Th>
                  <Th className="text-right">Failed</Th>
                </tr>
              </thead>
              <tbody>
                {linkedWebsites.data.items.map((item) => (
                  <tr key={item.id}>
                    <Td>
                      <div className="min-w-0">
                        <p className="truncate text-sm text-content">
                          {item.name || item.domain}
                        </p>
                        <p className="truncate text-xs text-content-subtle">
                          {item.domain}
                        </p>
                      </div>
                    </Td>
                    <Td className="whitespace-nowrap text-xs">
                      {item.category.replace(/_/g, " ")}
                    </Td>
                    <Td className="whitespace-nowrap text-xs">
                      {item.niche || "-"}
                    </Td>
                    <Td>
                      <Badge tone="neutral">
                        {websiteStatusLabel(item.status)}
                      </Badge>
                    </Td>
                    <Td className="text-right text-xs tabular-nums">
                      {formatNumber(item.stats.submitted)}
                    </Td>
                    <Td className="text-right text-xs tabular-nums text-danger">
                      {formatNumber(item.stats.failed)}
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          ) : null}

          {!linkedWebsites.loading &&
          !linkedWebsites.error &&
          linkedWebsites.data &&
          linkedWebsites.data.items.length === 0 ? (
            <div className="p-4">
              <NothingYet
                title="No website in this project yet"
                description="Pick the sites this project should work on from the central website list."
                action={
                  <Button
                    size="sm"
                    onClick={() => setChoosingWebsites(true)}
                  >
                    Add from the website list
                  </Button>
                }
              />
            </div>
          ) : null}
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title="Switch project"
          description="Every project of this installation"
        />
        <CardBody>
          <div className="w-96">
            <Field label="Project">
              <Select
                value={projectId}
                onChange={(event) => {
                  const next = event.target.value;
                  if (next) navigate(`projects/${next}`);
                }}
              >
                {(allProjects.data?.items ?? []).map((item: Project) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </Select>
            </Field>
          </div>
          {allProjects.loading ? (
            <p className="mt-2 text-xs text-content-subtle">Loading projects…</p>
          ) : null}
          {allProjects.error ? (
            <p className="mt-2 text-xs text-danger">
              {errorText(allProjects.error, "Could not load the projects")}
            </p>
          ) : null}
        </CardBody>
      </Card>
        </div>
      </details>

      <AddToProjectDialog
        projectId={projectId}
        projectName={data?.name}
        open={choosingWebsites}
        onClose={() => setChoosingWebsites(false)}
        onAdded={() => {
          linkedWebsites.reload();
          setCampaignReload((value) => value + 1);
        }}
        defaultAnchorText={
          profile.data?.preferred_anchors?.[0] || profile.data?.name || ""
        }
        defaultTargetLandingPage={
          data?.target_website || landingPages[0]?.url || ""
        }
      />

      <ProjectEditDialog
        open={editing}
        project={data}
        onClose={() => setEditing(false)}
        onSaved={() => {
          project.reload();
          projectDetails.reload();
          websites.reload();
          reportStats.reload();
        }}
      />

      <ProjectDeleteDialog
        open={deleting}
        project={data}
        counts={counts ?? null}
        busy={deletingBusy}
        error={deleteError}
        onCancel={() => {
          if (deletingBusy) return;
          setDeleting(false);
          setDeleteError(null);
        }}
        onConfirm={() => void deleteProject()}
      />
    </div>
  );
}
