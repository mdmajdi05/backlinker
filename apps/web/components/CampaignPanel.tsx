"use client";

import * as React from "react";
import { api } from "@autobacklinker/api-client";
import type {
  CampaignAddResult,
  CampaignRow,
  CampaignRowStatus,
  CampaignStartResult,
} from "@autobacklinker/shared-types";
import {
  Alert,
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  Dialog,
  Field,
  Input,
  LoginViewer,
  MetricTile,
  ProgressBar,
  Select,
  Skeleton,
  Table,
  Td,
  Textarea,
  Th,
  useToast,
  type BadgeTone,
} from "@autobacklinker/ui";
import { apiClient, errorMessage } from "@/lib/api";
import { useAction, useResource } from "@/lib/hooks";
import { formatDateTime, humanize } from "@/lib/format";
import { ErrorPanel } from "@/components/States";
import { SubmissionDetailsPanel } from "@/components/SubmissionDetailsPanel";
import { AutomationSetupDialog } from "@/components/AutomationSetupDialog";

/** The status of a row as the operator reads it - not the internal code. */
const STATUS_LABELS: Record<CampaignRowStatus, string> = {
  NOT_STARTED: "Not started",
  NEEDS_DETAILS: "Details needed",
  READY: "Ready to start",
  QUEUED: "Queued",
  SUBMITTING: "Submitting…",
  PAUSED: "Stopped",
  WAITING_MANUAL: "Submit by hand",
  LOGIN_NEEDED: "Login needed",
  SUBMITTED: "Submitted",
  VERIFIED: "Verified",
  FAILED: "Failed",
  VERIFICATION_FAILED: "Verification failed",
  EXCLUDED: "Excluded",
};

const STATUS_TONES: Record<CampaignRowStatus, BadgeTone> = {
  NOT_STARTED: "neutral",
  NEEDS_DETAILS: "warning",
  READY: "accent",
  QUEUED: "info",
  SUBMITTING: "info",
  PAUSED: "neutral",
  WAITING_MANUAL: "warning",
  LOGIN_NEEDED: "warning",
  SUBMITTED: "accent",
  VERIFIED: "success",
  FAILED: "danger",
  VERIFICATION_FAILED: "danger",
  EXCLUDED: "neutral",
};

/** Rows whose task is on its way - the table refreshes fast while any exists. */
const LIVE_STATUSES: CampaignRowStatus[] = ["QUEUED", "SUBMITTING"];

export function CampaignPanel({
  projectId,
  onChanged,
  onPickFromList,
  onOpenReport,
  reloadToken,
}: {
  projectId: string;
  onChanged?: () => void;
  /** Optional: open the picker of the central website list. */
  onPickFromList?: () => void;
  /** Optional: open the full report page. */
  onOpenReport?: () => void;
  /** Bumping this number reloads the table (the parent added rows). */
  reloadToken?: number;
}) {
  const toast = useToast();
  const campaign = useResource(
    () => api.campaign.get(apiClient, projectId),
    [projectId],
  );
  const settings = useResource(
    () => api.projects.settings(apiClient, projectId),
    [projectId],
  );

  const [text, setText] = React.useState("");
  const [addResult, setAddResult] = React.useState<CampaignAddResult | null>(null);
  const [startOpen, setStartOpen] = React.useState(false);
  const [startResult, setStartResult] = React.useState<CampaignStartResult | null>(null);
  const [detailsRow, setDetailsRow] = React.useState<CampaignRow | null>(null);
  const [automationRow, setAutomationRow] = React.useState<CampaignRow | null>(null);
  const [submitRow, setSubmitRow] = React.useState<CampaignRow | null>(null);
  const [submitMode, setSubmitMode] = React.useState<"mark" | "update">("mark");
  const [submitUrl, setSubmitUrl] = React.useState("");
  const [submitAnchor, setSubmitAnchor] = React.useState("");
  const [submitVerify, setSubmitVerify] = React.useState(true);
  const [stopOpen, setStopOpen] = React.useState(false);
  const [removeRow, setRemoveRow] = React.useState<CampaignRow | null>(null);
  /** The row whose login window is open and waits for "save". */
  const [loginRow, setLoginRow] = React.useState<CampaignRow | null>(null);
  const [loginStreaming, setLoginStreaming] = React.useState(false);
  const [loginViewOpen, setLoginViewOpen] = React.useState(false);
  const [loginWarning, setLoginWarning] = React.useState<string | null>(null);
  const [categoryFilter, setCategoryFilter] = React.useState("");
  const [statusFilter, setStatusFilter] = React.useState("");
  const fileRef = React.useRef<HTMLInputElement | null>(null);

  const addAction = useAction();
  const importAction = useAction();
  const startAction = useAction();
  const submitAction = useAction();
  const rowAction = useAction();
  const controlAction = useAction();
  const downloadAction = useAction();
  const settingsAction = useAction();

  const data = campaign.data;
  const rows = React.useMemo(() => data?.rows ?? [], [data]);
  const summary = data?.summary;
  const live = rows.some((row) => LIVE_STATUSES.includes(row.status));
  const paused = data?.project_status === "PAUSED";
  const pausedCount = summary?.paused ?? 0;
  const categories = React.useMemo(
    () => Array.from(new Set(rows.map((row) => row.category).filter(Boolean))).sort(),
    [rows],
  );
  const visibleRows = React.useMemo(
    () =>
      rows.filter(
        (row) =>
          (!categoryFilter || row.category === categoryFilter) &&
          (!statusFilter || row.status === statusFilter),
      ),
    [rows, categoryFilter, statusFilter],
  );

  /* The table is alive while a task is on its way; when nothing runs a slow
     refresh is enough to notice a change made in another tab. */
  React.useEffect(() => {
    const interval = window.setInterval(
      () => campaign.reload(),
      live ? 3000 : 20000,
    );
    return () => window.clearInterval(interval);
  }, [live, campaign.reload]);

  /* The parent added rows (from the website list) - show them right away. */
  React.useEffect(() => {
    if (reloadToken) campaign.reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reloadToken]);

  const refresh = React.useCallback(() => {
    campaign.reload();
    onChanged?.();
  }, [campaign, onChanged]);

  const addWebsites = async () => {
    const value = text.trim();
    if (!value) return;
    const outcome = await addAction.run(() =>
      api.campaign.add(apiClient, projectId, value),
    );
    if (!outcome.ok || !outcome.data) {
      toast.push(errorMessage(outcome.error), "error");
      return;
    }
    setAddResult(outcome.data);
    setText("");
    const count = outcome.data.added + outcome.data.linked;
    toast.push(`${count} website(s) added to this project`, "success");
    refresh();
  };

  const importFile = async (file: File | undefined) => {
    if (!file) return;
    const outcome = await importAction.run(() =>
      api.campaign.import(apiClient, projectId, file),
    );
    if (outcome.ok && outcome.data) {
      toast.push(
        `${outcome.data.created + outcome.data.updated} row(s) imported, ${outcome.data.linked} linked here`,
        "success",
      );
      refresh();
    } else {
      toast.push(errorMessage(outcome.error), "error");
    }
    if (fileRef.current) fileRef.current.value = "";
  };

  const start = async () => {
    const outcome = await startAction.run(() =>
      api.campaign.start(apiClient, projectId),
    );
    if (!outcome.ok || !outcome.data) {
      toast.push(errorMessage(outcome.error), "error");
      return;
    }
    setStartOpen(false);
    setStartResult(outcome.data);
    toast.push(
      outcome.data.queued > 0
        ? `${outcome.data.queued} website(s) queued`
        : "Nothing new to queue",
      outcome.data.queued > 0 ? "success" : "info",
    );
    refresh();
  };

  const stop = async () => {
    const outcome = await controlAction.run(() =>
      api.campaign.stop(apiClient, projectId),
    );
    if (!outcome.ok || !outcome.data) {
      toast.push(errorMessage(outcome.error), "error");
      return;
    }
    setStopOpen(false);
    toast.push(outcome.data.message || "Work stopped", "success");
    refresh();
  };

  const removeFromProject = async () => {
    if (!removeRow) return;
    const outcome = await controlAction.run(() =>
      api.campaign.remove(apiClient, projectId, removeRow.opportunity_id),
    );
    if (!outcome.ok) {
      toast.push(errorMessage(outcome.error), "error");
      return;
    }
    toast.push(
      `${removeRow.name} removed from this project - it stays in Backlink websites`,
      "success",
    );
    setRemoveRow(null);
    refresh();
  };

  const restartFailed = async () => {
    const outcome = await controlAction.run(() =>
      api.campaign.restartFailed(apiClient, projectId),
    );
    if (!outcome.ok || !outcome.data) {
      toast.push(errorMessage(outcome.error), "error");
      return;
    }
    const count = outcome.data.retried + outcome.data.verifications;
    toast.push(
      count > 0
        ? `${count} failed row(s) queued again`
        : "There is no failed row to restart",
      count > 0 ? "success" : "info",
    );
    refresh();
  };

  const downloadReport = async () => {
    const outcome = await downloadAction.run(() =>
      api.campaign.downloadReport(apiClient, projectId),
    );
    if (outcome.ok) {
      toast.push("Report downloaded", "success");
    } else {
      toast.push(errorMessage(outcome.error), "error");
    }
  };

  /** Three simple speed presets instead of a wall of execution numbers. */
  const changeSpeed = async (value: string) => {
    const current = settings.data;
    if (!current) {
      toast.push("The project settings could not be loaded", "error");
      return;
    }
    const preset =
      value === "slow"
        ? { max_concurrency: 1, request_rate_per_minute: 20 }
        : value === "fast"
          ? { max_concurrency: 6, request_rate_per_minute: 120 }
          : { max_concurrency: 3, request_rate_per_minute: 60 };
    const outcome = await settingsAction.run(() =>
      api.projects.updateSettings(apiClient, projectId, { ...current, ...preset }),
    );
    if (outcome.ok) {
      toast.push(`Speed set to ${value}`, "success");
      settings.reload();
    } else {
      toast.push(errorMessage(outcome.error), "error");
    }
  };

  const speedValue = settings.data
    ? settings.data.max_concurrency >= 6
      ? "fast"
      : settings.data.max_concurrency <= 1
        ? "slow"
        : "normal"
    : "normal";

  const retryRow = async (row: CampaignRow) => {
    if (!row.task_id) return;
    const outcome = await rowAction.run(() =>
      api.tasks.retry(apiClient, row.task_id as string),
    );
    if (outcome.ok) {
      toast.push("Task queued for retry", "success");
      refresh();
    } else {
      toast.push(errorMessage(outcome.error), "error");
    }
  };

  /** Reopen the login browser of the project for this row. */
  const relogin = async (row: CampaignRow) => {
    const outcome = await rowAction.run(() =>
      api.projectLogin.openSite(apiClient, projectId, row.website_id, "remote"),
    );
    if (outcome.ok && outcome.data?.running) {
      const streamed = outcome.data.view === "remote";
      setLoginRow(row);
      setLoginStreaming(streamed);
      setLoginViewOpen(streamed);
      setLoginWarning(outcome.data.warning ?? null);
      toast.push(
        streamed
          ? "Login browser opened. Sign in in the live view."
          : "Login window opened for this website. Sign in, then press Save login.",
        "success",
      );
      refresh();
    } else if (outcome.ok) {
      toast.push(outcome.data?.message ?? "The login window could not be opened.", "info");
    } else {
      toast.push(errorMessage(outcome.error), "error");
    }
  };

  /** Save the session of the open window and resume the paused tasks. */
  const saveLogin = async () => {
    if (!loginRow) return;
    const outcome = await rowAction.run(() =>
      api.projectLogin.finishSite(apiClient, projectId, loginRow.website_id),
    );
    if (outcome.ok) {
      const result = outcome.data;
      const saved = Boolean(result?.saved) && result?.site?.status === "CONNECTED";
      toast.push(
        saved
          ? result?.resumed
            ? `Login saved. ${result.resumed} paused task(s) queued again.`
            : "Login saved."
          : result?.message ?? "No new session was saved.",
        saved ? "success" : "info",
      );
      setLoginRow(null);
      setLoginStreaming(false);
      setLoginViewOpen(false);
      refresh();
    } else {
      toast.push(errorMessage(outcome.error), "error");
    }
  };

  const verifyRow = async (row: CampaignRow) => {
    const outcome = await rowAction.run(() =>
      api.campaign.verify(apiClient, projectId, row.opportunity_id),
    );
    if (outcome.ok) {
      toast.push("Verification queued", "success");
      refresh();
      /* The verification runs in the background - one more look keeps the
         row honest without polling the backend forever. */
      window.setTimeout(() => campaign.reload(), 5000);
    } else {
      toast.push(errorMessage(outcome.error), "error");
    }
  };

  const openSubmit = (row: CampaignRow, mode: "mark" | "update" = "mark") => {
    setSubmitRow(row);
    setSubmitMode(mode);
    setSubmitUrl(row.published_page_url ?? row.url);
    setSubmitAnchor(row.observed_anchor_text ?? "");
    setSubmitVerify(true);
  };

  const markSubmitted = async () => {
    if (!submitRow) return;
    const outcome = await submitAction.run(() =>
      api.campaign.markSubmitted(apiClient, projectId, submitRow.opportunity_id, {
        published_url: submitUrl.trim() || undefined,
        anchor_text: submitAnchor.trim() || undefined,
        verify: submitVerify,
      }),
    );
    if (!outcome.ok) {
      toast.push(errorMessage(outcome.error), "error");
      return;
    }
    toast.push(
      submitMode === "update"
        ? submitVerify
          ? "Published link updated - verification is queued"
          : "Published link updated"
        : submitVerify
          ? "Marked as submitted - verification is queued"
          : "Marked as submitted",
      "success",
    );
    setSubmitRow(null);
    refresh();
    /* The verification runs in the background - one more look keeps the row
       honest without polling the backend forever. */
    if (submitVerify) window.setTimeout(() => campaign.reload(), 5000);
  };

  return (
    <Card>
      <CardHeader
        title="Backlink work"
        description="Step 1: add websites. Step 2: press Start. Step 3: follow every result in the table."
        action={
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => void downloadReport()}
              loading={downloadAction.pending}
              disabled={rows.length === 0}
            >
              Download report
            </Button>
            {onOpenReport ? (
              <Button variant="outline" size="sm" onClick={onOpenReport}>
                Report page
              </Button>
            ) : null}
          </div>
        }
      />
      <CardBody className="space-y-4">
        {campaign.loading && !data ? (
          <div className="space-y-2" aria-busy="true" aria-live="polite">
            <span className="sr-only">Loading the campaign…</span>
            <Skeleton className="h-2 w-full" />
            <Skeleton className="h-16 w-full" />
            <Skeleton className="h-32 w-full" />
          </div>
        ) : campaign.error ? (
          <ErrorPanel
            error={campaign.error}
            onRetry={campaign.reload}
            title="The campaign could not be loaded"
          />
        ) : data && summary ? (
          <>
            {/* ------------------------------------------------ progress */}
            <div className="space-y-2">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <p className="text-sm font-semibold text-content">
                  {summary.done} of {summary.total} website(s) done
                  <span className="ml-2 font-normal text-content-muted">
                    ({summary.percent}%)
                  </span>
                </p>
                <span className="flex items-center gap-1.5 text-[11px] text-content-subtle">
                  <span
                    className={
                      live
                        ? "h-1.5 w-1.5 animate-pulse rounded-full bg-success"
                        : "h-1.5 w-1.5 rounded-full bg-line-strong"
                    }
                    aria-hidden
                  />
                  {live ? "Live - updates every 3s" : "Idle - updates every 20s"}
                  {data.generated_at ? ` · ${formatDateTime(data.generated_at)}` : ""}
                </span>
              </div>
              <ProgressBar value={summary.percent / 100} className="h-2" />
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <MetricTile label="Websites" value={summary.total} />
                <MetricTile
                  label="Done"
                  value={`${summary.done} (${summary.percent}%)`}
                  hint={`${summary.verified} verified · ${summary.submitted} submitted`}
                  tone="success"
                />
                <MetricTile
                  label="In progress"
                  value={
                    summary.in_progress +
                    summary.waiting_manual +
                    summary.login_needed +
                    pausedCount
                  }
                  hint={`${summary.in_progress} running · ${summary.waiting_manual} manual · ${summary.login_needed} login · ${pausedCount} stopped`}
                  tone="info"
                />
                <MetricTile
                  label="Remaining"
                  value={summary.remaining}
                  hint={
                    summary.failed > 0
                      ? `${summary.failed} failed - see the table`
                      : `${summary.needs_details} need details`
                  }
                  tone={summary.failed > 0 ? "danger" : "neutral"}
                />
              </div>
            </div>

            {/* ------------------------------------------------- run bar */}
            <div className="rounded-lg border border-accent/35 bg-accent-soft/30 p-3">
              <p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-accent">
                Step 2 - Start and stop the work
              </p>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                  <span
                    className={
                      live
                        ? "h-2 w-2 animate-pulse rounded-full bg-success"
                        : paused
                          ? "h-2 w-2 rounded-full bg-warning"
                          : "h-2 w-2 rounded-full bg-line-strong"
                    }
                    aria-hidden
                  />
                  <div>
                    <p className="text-sm font-semibold text-content">
                      {live
                        ? "Working now"
                        : paused
                          ? "Stopped"
                          : summary.in_progress > 0
                            ? "Queued"
                            : "Ready when you are"}
                    </p>
                    <p className="text-[11px] text-content-muted">
                      {live
                        ? `${summary.in_progress} website(s) in progress`
                        : paused
                          ? `${pausedCount} website(s) paused - Start resumes them`
                          : `${summary.not_started} ready · ${summary.needs_details} need details`}
                    </p>
                  </div>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <label className="flex items-center gap-1.5 text-[11px] text-content-muted">
                    Speed
                    <Select
                      aria-label="Run speed"
                      className="h-8 w-28 text-xs"
                      value={speedValue}
                      disabled={settingsAction.pending || !settings.data}
                      onChange={(event) => void changeSpeed(event.target.value)}
                    >
                      <option value="slow">Slow</option>
                      <option value="normal">Normal</option>
                      <option value="fast">Fast</option>
                    </Select>
                  </label>
                  <Button
                    onClick={() => setStartOpen(true)}
                    loading={startAction.pending}
                    disabled={!summary || summary.total === 0}
                  >
                    {paused ? "Resume backlinks" : "Start backlinks"}
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() => setStopOpen(true)}
                    loading={controlAction.pending}
                    disabled={paused || !summary || summary.total === 0}
                  >
                    Stop
                  </Button>
                </div>
              </div>
              {summary.failed > 0 ? (
                <div className="mt-2 flex flex-wrap items-center justify-between gap-2 border-t border-accent/20 pt-2">
                  <p className="text-[11px] text-danger">
                    {summary.failed} row(s) failed. Restart them without touching the rest.
                  </p>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => void restartFailed()}
                    loading={controlAction.pending}
                  >
                    Restart failed
                  </Button>
                </div>
              ) : null}
            </div>

            {/* ------------------------------------------------- add box */}
            <div className="space-y-2 rounded-lg border border-line bg-surface-raised/40 p-3">
              <Field
                label="Step 1 - Add websites"
                hint="Paste one or many URLs - separated by a comma, a space or a new line. Each site is added to the central list once and linked to this project."
              >
                <Textarea
                  rows={2}
                  value={text}
                  onChange={(event) => setText(event.target.value)}
                  placeholder="example.com/add-listing, another-directory.com/submit"
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
                      event.preventDefault();
                      void addWebsites();
                    }
                  }}
                />
              </Field>
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  size="sm"
                  onClick={() => void addWebsites()}
                  loading={addAction.pending}
                  disabled={!text.trim()}
                >
                  Add websites
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => fileRef.current?.click()}
                  loading={importAction.pending}
                >
                  Import Excel / CSV
                </Button>
                {onPickFromList ? (
                  <Button size="sm" variant="outline" onClick={onPickFromList}>
                    Choose websites
                  </Button>
                ) : null}
                <span className="text-[11px] text-content-subtle">
                  Columns: Website or Opportunity URL, Category, Anchor Text, Description
                </span>
                <input
                  ref={fileRef}
                  type="file"
                  accept=".xlsx,.xlsm,.csv"
                  className="hidden"
                  aria-label="Import a spreadsheet"
                  onChange={(event) => void importFile(event.target.files?.[0])}
                />
              </div>

              {addResult ? (
                <Alert
                  tone={
                    addResult.invalid + addResult.deleted > 0 ? "warning" : "success"
                  }
                  title={[
                    `${addResult.added} added`,
                    `${addResult.linked} linked`,
                    addResult.existing ? `${addResult.existing} already here` : "",
                    addResult.invalid ? `${addResult.invalid} invalid` : "",
                    addResult.deleted ? `${addResult.deleted} in the recycle bin` : "",
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                  action={
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => setAddResult(null)}
                    >
                      Dismiss
                    </Button>
                  }
                >
                  {addResult.results.filter(
                    (row) => row.status === "invalid" || row.status === "deleted",
                  ).length > 0 ? (
                    <ul className="list-disc space-y-1 pl-4">
                      {addResult.results
                        .filter(
                          (row) => row.status === "invalid" || row.status === "deleted",
                        )
                        .map((row) => (
                          <li key={`${row.status}-${row.input}`}>
                            <span className="font-mono text-[11px]">{row.input}</span> -{" "}
                            {row.message}
                          </li>
                        ))}
                    </ul>
                  ) : (
                    "The rows were added to the central list and linked to this project."
                  )}
                </Alert>
              ) : null}
            </div>

            {/* ------------------------------------------------ filters */}
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-[11px] font-semibold uppercase tracking-wider text-content-subtle">
                  Step 3 - Assigned websites and report
                </span>
                <Select
                  aria-label="Filter by category"
                  className="h-8 w-44 text-xs"
                  value={categoryFilter}
                  onChange={(event) => setCategoryFilter(event.target.value)}
                >
                  <option value="">All categories</option>
                  {categories.map((category) => (
                    <option key={category} value={category}>
                      {humanize(category)}
                    </option>
                  ))}
                </Select>
                <Select
                  aria-label="Filter by status"
                  className="h-8 w-40 text-xs"
                  value={statusFilter}
                  onChange={(event) => setStatusFilter(event.target.value)}
                >
                  <option value="">All statuses</option>
                  {(Object.keys(STATUS_LABELS) as CampaignRowStatus[]).map((status) => (
                    <option key={status} value={status}>
                      {STATUS_LABELS[status]}
                    </option>
                  ))}
                </Select>
              </div>
              <span className="text-[11px] text-content-muted">
                {visibleRows.length} of {rows.length} website(s)
              </span>
            </div>

            {/* --------------------------------------------------- table */}
            {visibleRows.length === 0 ? (
              <Alert
                tone="neutral"
                title={
                  rows.length === 0
                    ? "No websites in this project yet"
                    : "No website matches these filters"
                }
              >
                {rows.length === 0
                  ? "Paste the URLs above, import a spreadsheet or pick from Backlink websites. A website can be used by many projects - removing it here never deletes it from the list."
                  : "Choose another category or status to see the other websites."}
              </Alert>
            ) : (
              <Table>
                <thead>
                  <tr>
                    <Th>Website</Th>
                    <Th>Data ready</Th>
                    <Th>Status</Th>
                    <Th>Last update</Th>
                    <Th className="text-right">Actions</Th>
                  </tr>
                </thead>
                <tbody>
                  {visibleRows.map((row) => (
                    <tr key={row.opportunity_id}>
                      <Td>
                        <div className="min-w-0">
                          <p className="truncate font-medium text-content" title={row.name}>
                            {row.name}
                          </p>
                          <a
                            href={row.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="truncate text-[11px] text-accent hover:underline"
                          >
                            {row.domain}
                          </a>
                          <p className="flex flex-wrap items-center gap-1 text-[11px] text-content-subtle">
                            {humanize(row.category)}
                            {row.adapter_key ? (
                              <Badge tone="info" className="px-1 py-0 text-[9px]">
                                Auto setup
                              </Badge>
                            ) : null}
                          </p>
                        </div>
                      </Td>
                      <Td>
                        <div className="w-36 space-y-1">
                          <div className="flex items-center justify-between text-[11px]">
                            <span className="text-content-muted">
                              {row.details_percent}%
                            </span>
                            {row.missing.length > 0 ? (
                              <span
                                className="text-warning"
                                title={`Missing: ${row.missing.join(", ")}`}
                              >
                                {row.missing.length} missing
                              </span>
                            ) : (
                              <span className="text-success">ready</span>
                            )}
                          </div>
                          <ProgressBar value={row.details_percent / 100} />
                          {row.missing.length > 0 ? (
                            <p
                              className="truncate text-[10px] text-warning"
                              title={`Missing: ${row.missing.join(", ")}`}
                            >
                              Missing: {row.missing.join(", ")}
                            </p>
                          ) : null}
                        </div>
                      </Td>
                      <Td>
                        <Badge tone={STATUS_TONES[row.status]}>
                          {STATUS_LABELS[row.status]}
                        </Badge>
                      </Td>
                      <Td>
                        <span className="whitespace-nowrap text-[11px] text-content-muted">
                          {formatDateTime(row.last_update)}
                        </span>
                      </Td>
                      <Td>
                        <div className="flex flex-wrap items-center justify-end gap-1">
                          {row.status === "NEEDS_DETAILS" ? (
                            <Button size="sm" onClick={() => setDetailsRow(row)}>
                              Fill details
                            </Button>
                          ) : null}
                          {row.status === "LOGIN_NEEDED" ? (
                            <div className="flex flex-wrap items-center justify-end gap-1">
                              {loginRow?.opportunity_id === row.opportunity_id ? (
                                <>
                                  {loginStreaming ? (
                                    <Button
                                      size="sm"
                                      variant="outline"
                                      onClick={() => setLoginViewOpen(true)}
                                    >
                                      Open login view
                                    </Button>
                                  ) : null}
                                  <Button
                                    size="sm"
                                    loading={rowAction.pending}
                                    onClick={() => void saveLogin()}
                                  >
                                    Save login
                                  </Button>
                                </>
                              ) : (
                                <Button
                                  size="sm"
                                  loading={rowAction.pending}
                                  onClick={() => void relogin(row)}
                                >
                                  Re-login
                                </Button>
                              )}
                              <Button
                                size="sm"
                                variant="ghost"
                                onClick={() => openSubmit(row)}
                              >
                                Mark submitted
                              </Button>
                            </div>
                          ) : null}
                          {row.status === "WAITING_MANUAL" ? (
                            <>
                              <Button size="sm" onClick={() => openSubmit(row)}>
                                Mark submitted
                              </Button>
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={() => setAutomationRow(row)}
                              >
                                Automate
                              </Button>
                            </>
                          ) : null}
                          {["READY", "FAILED", "PAUSED"].includes(row.status) ? (
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => setAutomationRow(row)}
                            >
                              Automate
                            </Button>
                          ) : null}
                          {row.status === "SUBMITTED" ? (
                            <>
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={() => void verifyRow(row)}
                                loading={rowAction.pending}
                              >
                                Verify
                              </Button>
                              <Button
                                size="sm"
                                variant="ghost"
                                onClick={() => openSubmit(row, "update")}
                              >
                                Update link
                              </Button>
                            </>
                          ) : null}
                          {row.status === "FAILED" && row.task_id ? (
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => void retryRow(row)}
                              loading={rowAction.pending}
                            >
                              Retry
                            </Button>
                          ) : null}
                          {row.status === "VERIFICATION_FAILED" ? (
                            <>
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={() => void verifyRow(row)}
                                loading={rowAction.pending}
                              >
                                Verify again
                              </Button>
                              <Button size="sm" onClick={() => openSubmit(row)}>
                                Mark submitted
                              </Button>
                            </>
                          ) : null}
                          {row.status === "VERIFIED" && row.published_page_url ? (
                            <>
                              <a
                                href={row.published_page_url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="text-[11px] text-accent hover:underline"
                              >
                                View link
                              </a>
                              <Button
                                size="sm"
                                variant="ghost"
                                onClick={() => openSubmit(row, "update")}
                              >
                                Update link
                              </Button>
                            </>
                          ) : null}
                          {row.status !== "NEEDS_DETAILS" ? (
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => setDetailsRow(row)}
                            >
                              Details
                            </Button>
                          ) : null}
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => setRemoveRow(row)}
                            title="Remove this website from the project (it stays in Backlink websites)"
                          >
                            Remove
                          </Button>
                        </div>
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}

            <p className="text-[11px] text-content-muted">
              <strong className="font-semibold text-content">Data ready</strong> counts the
              values the website asks for that are already filled or that the project
              details supply. <strong className="font-semibold text-content">Start backlinks</strong>{" "}
              fills them; a site is never sent half filled. Manually edited values are
              never overwritten. Sites without an automation stay at{" "}
              <span className="font-medium text-content">&quot;Submit by hand&quot;</span>:
              open <span className="font-medium text-content">Details</span> for the values,
              submit them on the website, then press{" "}
              <span className="font-medium text-content">Mark submitted</span>.{" "}
              <strong className="font-semibold text-content">Stop</strong> pauses the
              queued work and Start resumes it.
            </p>
          </>
        ) : null}
      </CardBody>

      {/* ------------------------------------------------- stop dialog */}
      <Dialog
        open={stopOpen}
        onClose={() => setStopOpen(false)}
        title="Stop the backlink work?"
        footer={
          <>
            <Button variant="outline" onClick={() => setStopOpen(false)}>
              Keep running
            </Button>
            <Button variant="danger" onClick={() => void stop()} loading={controlAction.pending}>
              Stop
            </Button>
          </>
        }
      >
        <p className="text-xs text-content-muted">
          Queued websites are paused and nothing is deleted. A task that is already
          running stops at the next safe step. Press <strong className="text-content">Resume
          backlinks</strong> to continue exactly where it stopped.
        </p>
      </Dialog>

      {/* ----------------------------------------------- remove dialog */}
      <Dialog
        open={removeRow !== null}
        onClose={() => setRemoveRow(null)}
        title={removeRow ? `Remove ${removeRow.name}?` : "Remove website"}
        footer={
          <>
            <Button variant="outline" onClick={() => setRemoveRow(null)}>
              Cancel
            </Button>
            <Button
              variant="danger"
              onClick={() => void removeFromProject()}
              loading={controlAction.pending}
            >
              Remove from project
            </Button>
          </>
        }
      >
        <p className="text-xs text-content-muted">
          The website leaves this project and its open work is cancelled. It stays in{" "}
          <strong className="text-content">Backlink websites</strong>, so other projects
          keep it and you can add it back at any time.
        </p>
      </Dialog>

      {/* ------------------------------------------------ start dialog */}
      <Dialog
        open={startOpen}
        onClose={() => setStartOpen(false)}
        title="Start the backlink work?"
        description="One click does three things - nothing is sent half filled."
        footer={
          <>
            <Button variant="outline" onClick={() => setStartOpen(false)}>
              Cancel
            </Button>
            <Button onClick={() => void start()} loading={startAction.pending}>
              Start backlinks
            </Button>
          </>
        }
      >
        <ol className="list-decimal space-y-2 pl-4 text-xs text-content-muted">
          <li>
            The details of every website are filled from the project details. Manually
            edited values stay untouched.
          </li>
          <li>
            Every website with complete details is queued. The project is set to{" "}
            <strong className="text-content">Active</strong>.
          </li>
          <li>
            A site that still misses details is not queued - it appears in the table with
            the missing values.
          </li>
        </ol>
        <p className="mt-3 text-xs text-content-muted">
          {summary?.total ?? 0} website(s) in this project ·{" "}
          {summary?.needs_details ?? 0} currently need details ·{" "}
          {summary?.in_progress ?? 0} already queued.
        </p>
      </Dialog>

      {/* --------------------------------------------- start result */}
      <Dialog
        open={startResult !== null}
        onClose={() => setStartResult(null)}
        title="Backlink work started"
        footer={
          <Button onClick={() => setStartResult(null)}>Close</Button>
        }
      >
        {startResult ? (
          <div className="space-y-3 text-xs text-content-muted">
            <p>
              <strong className="text-content">{startResult.queued}</strong> website(s)
              queued · {startResult.already_queued} already queued ·{" "}
              {startResult.done} already done · {startResult.excluded} excluded.
            </p>
            {startResult.needs_details.length > 0 ? (
              <Alert
                tone="warning"
                title={`${startResult.needs_details.length} website(s) need details`}
              >
                <ul className="list-disc space-y-1 pl-4">
                  {startResult.needs_details.map((row) => (
                    <li key={row.opportunity_id}>
                      <span className="font-medium text-content">{row.website}</span>:{" "}
                      {row.missing.join(", ")}
                    </li>
                  ))}
                </ul>
                <p className="mt-2">
                  Edit the project details above or use &quot;Fill details&quot; on the row,
                  then press Start again.
                </p>
              </Alert>
            ) : (
              <p>Every website of this project has complete details.</p>
            )}
          </div>
        ) : null}
      </Dialog>

      {/* --------------------------------------------- automation dialog */}
      <AutomationSetupDialog
        open={automationRow !== null}
        onClose={() => setAutomationRow(null)}
        websiteId={automationRow?.website_id ?? ""}
        domain={automationRow?.domain ?? ""}
        formUrl={automationRow?.url ?? ""}
        taskId={automationRow?.task_id ?? null}
        config={automationRow?.adapter_config ?? null}
        onSaved={refresh}
      />

      {/* ------------------------------------------------ details dialog */}
      <Dialog
        open={detailsRow !== null}
        onClose={() => setDetailsRow(null)}
        title={detailsRow ? `Details - ${detailsRow.name}` : "Details"}
        description="The values this website asks for. They are stored for this project only."
        width="xl"
      >
        {detailsRow ? (
          <SubmissionDetailsPanel
            opportunityId={detailsRow.opportunity_id}
            onChanged={() => {
              campaign.reload();
              onChanged?.();
            }}
          />
        ) : null}
      </Dialog>

      {/* ------------------------------------------- mark submitted dialog */}
      <Dialog
        open={submitRow !== null}
        onClose={() => setSubmitRow(null)}
        title={
          submitRow
            ? `${submitMode === "update" ? "Update published link" : "Mark submitted"} - ${submitRow.name}`
            : submitMode === "update"
              ? "Update published link"
              : "Mark submitted"
        }
        description={
          submitMode === "update"
            ? "Correct the page where your link lives. Saving it queues a fresh verification."
            : "Use this after you filled the form of the website by hand."
        }
        footer={
          <>
            <Button variant="outline" onClick={() => setSubmitRow(null)}>
              Cancel
            </Button>
            <Button onClick={() => void markSubmitted()} loading={submitAction.pending}>
              {submitMode === "update" ? "Save link" : "Mark submitted"}
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <Field
            label="Published page URL"
            hint="The page where your link now lives. Leave it as it is when the submission URL is the published page."
          >
            <Input
              value={submitUrl}
              onChange={(event) => setSubmitUrl(event.target.value)}
              placeholder="https://example.com/my-listing"
            />
          </Field>
          <Field label="Anchor text (optional)" hint="Defaults to the anchor text of the website.">
            <Input
              value={submitAnchor}
              onChange={(event) => setSubmitAnchor(event.target.value)}
              placeholder="Acme Analytics"
            />
          </Field>
          <label className="flex items-center gap-2 text-xs text-content">
            <input
              type="checkbox"
              checked={submitVerify}
              onChange={(event) => setSubmitVerify(event.target.checked)}
            />
            Verify the link right after saving
          </label>
        </div>
      </Dialog>

      <LoginViewer
        open={loginViewOpen && loginStreaming && loginRow !== null}
        title={`Sign in to ${loginRow?.domain ?? "the website"}`}
        description="The browser runs on the backend machine. Type and click directly in the live view, then save the login."
        warning={loginWarning}
        issueTicket={() => api.projectLogin.streamTicket(apiClient, projectId)}
        onClose={() => setLoginViewOpen(false)}
        onClosed={() => {
          setLoginViewOpen(false);
          refresh();
        }}
        onSave={saveLogin}
        saveLabel="I'm done - save login"
        saving={rowAction.pending}
      />
    </Card>
  );
}
