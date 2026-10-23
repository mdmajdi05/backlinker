import * as React from "react";
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
  MetricTile,
  ProgressBar,
  Table,
  Td,
  Textarea,
  Th,
  useToast,
  type BadgeTone,
} from "@autobacklinker/ui";
import type {
  CampaignAddResult,
  CampaignRow,
  CampaignRowStatus,
  CampaignStartResult,
} from "@autobacklinker/shared-types";
import { api, apiClient } from "../lib/api";
import { useAsync } from "../lib/useAsync";
import { ErrorBlock } from "../components/common";
import { SubmissionDetailsPanel } from "../components/SubmissionDetailsPanel";
import { formatDate } from "../lib/format";

/** The status of a row as the operator reads it - not the internal code. */
const STATUS_LABELS: Record<CampaignRowStatus, string> = {
  NOT_STARTED: "Not started",
  NEEDS_DETAILS: "Details needed",
  READY: "Ready to start",
  QUEUED: "Queued",
  SUBMITTING: "Submitting…",
  WAITING_MANUAL: "Submit by hand",
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
  WAITING_MANUAL: "warning",
  SUBMITTED: "accent",
  VERIFIED: "success",
  FAILED: "danger",
  VERIFICATION_FAILED: "danger",
  EXCLUDED: "neutral",
};

const LIVE_STATUSES: CampaignRowStatus[] = ["QUEUED", "SUBMITTING"];

function errorText(error: unknown, fallback: string): string {
  if (error && typeof error === "object" && "message" in error) {
    return String((error as { message: unknown }).message);
  }
  return fallback;
}

/**
 * The campaign cockpit of a project.
 *
 * Add websites by URL (one or many), start the work with one click and watch
 * every row here.  The table refreshes itself while a task is on its way.
 */
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
  /** Optional: open the report of the project. */
  onOpenReport?: () => void;
  /** Bumping this number reloads the table (the parent added rows). */
  reloadToken?: number;
}) {
  const toast = useToast();
  const campaign = useAsync(
    () => api.campaign.get(apiClient, projectId),
    [projectId],
  );

  const [text, setText] = React.useState("");
  const [addResult, setAddResult] = React.useState<CampaignAddResult | null>(null);
  const [startOpen, setStartOpen] = React.useState(false);
  const [startResult, setStartResult] = React.useState<CampaignStartResult | null>(
    null,
  );
  const [detailsRow, setDetailsRow] = React.useState<CampaignRow | null>(null);
  const [submitRow, setSubmitRow] = React.useState<CampaignRow | null>(null);
  const [submitUrl, setSubmitUrl] = React.useState("");
  const [submitAnchor, setSubmitAnchor] = React.useState("");
  const [submitVerify, setSubmitVerify] = React.useState(true);
  const [adding, setAdding] = React.useState(false);
  const [importing, setImporting] = React.useState(false);
  const [starting, setStarting] = React.useState(false);
  const [submitting, setSubmitting] = React.useState(false);
  const [busyRow, setBusyRow] = React.useState<string | null>(null);
  const fileRef = React.useRef<HTMLInputElement | null>(null);

  const data = campaign.data;
  const rows = React.useMemo(() => data?.rows ?? [], [data]);
  const summary = data?.summary;
  const live = rows.some((row) => LIVE_STATUSES.includes(row.status));

  React.useEffect(() => {
    const interval = window.setInterval(
      () => campaign.reload(),
      live ? 3000 : 20000,
    );
    return () => window.clearInterval(interval);
  }, [live, campaign.reload]);

  React.useEffect(() => {
    if (reloadToken) campaign.reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reloadToken]);

  function refresh() {
    campaign.reload();
    onChanged?.();
  }

  async function addWebsites() {
    const value = text.trim();
    if (!value) return;
    setAdding(true);
    try {
      const result = await api.campaign.add(apiClient, projectId, value);
      setAddResult(result);
      setText("");
      toast.push(
        `${result.added + result.linked} website(s) added to this project`,
        "success",
      );
      refresh();
    } catch (error) {
      toast.push(errorText(error, "Could not add the websites"), "error");
    } finally {
      setAdding(false);
    }
  }

  async function importFile(file: File | undefined) {
    if (!file) return;
    setImporting(true);
    try {
      const result = await api.campaign.import(apiClient, projectId, file);
      toast.push(
        `${result.created + result.updated} row(s) imported, ${result.linked} linked here`,
        "success",
      );
      refresh();
    } catch (error) {
      toast.push(errorText(error, "Could not import the file"), "error");
    } finally {
      setImporting(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function start() {
    setStarting(true);
    try {
      const result = await api.campaign.start(apiClient, projectId);
      setStartOpen(false);
      setStartResult(result);
      toast.push(
        result.queued > 0
          ? `${result.queued} website(s) queued`
          : "Nothing new to queue",
        result.queued > 0 ? "success" : "info",
      );
      refresh();
    } catch (error) {
      toast.push(errorText(error, "Could not start the work"), "error");
    } finally {
      setStarting(false);
    }
  }

  async function retryRow(row: CampaignRow) {
    if (!row.task_id) return;
    setBusyRow(row.opportunity_id);
    try {
      await api.tasks.retry(apiClient, row.task_id);
      toast.push("Task queued for retry", "success");
      refresh();
    } catch (error) {
      toast.push(errorText(error, "Could not retry the task"), "error");
    } finally {
      setBusyRow(null);
    }
  }

  async function verifyRow(row: CampaignRow) {
    setBusyRow(row.opportunity_id);
    try {
      await api.campaign.verify(apiClient, projectId, row.opportunity_id);
      toast.push("Verification queued", "success");
      refresh();
      window.setTimeout(() => campaign.reload(), 5000);
    } catch (error) {
      toast.push(errorText(error, "Could not queue the verification"), "error");
    } finally {
      setBusyRow(null);
    }
  }

  function openSubmit(row: CampaignRow) {
    setSubmitRow(row);
    setSubmitUrl(row.published_page_url ?? row.url);
    setSubmitAnchor("");
    setSubmitVerify(true);
  }

  async function markSubmitted() {
    if (!submitRow) return;
    setSubmitting(true);
    try {
      await api.campaign.markSubmitted(
        apiClient,
        projectId,
        submitRow.opportunity_id,
        {
          published_url: submitUrl.trim() || undefined,
          anchor_text: submitAnchor.trim() || undefined,
          verify: submitVerify,
        },
      );
      toast.push(
        submitVerify
          ? "Marked as submitted - verification is queued"
          : "Marked as submitted",
        "success",
      );
      setSubmitRow(null);
      refresh();
    } catch (error) {
      toast.push(errorText(error, "Could not mark the row as submitted"), "error");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <>
      <Card>
        <CardHeader
          title="Backlink campaign"
          description="Everything for this project on one screen: add websites, press Start and watch every row."
          action={
            <div className="flex flex-wrap items-center gap-2">
              {onOpenReport ? (
                <Button size="sm" variant="outline" onClick={onOpenReport}>
                  Full report
                </Button>
              ) : null}
              <Button
                onClick={() => setStartOpen(true)}
                disabled={!summary || summary.total === 0}
              >
                Start backlinks
              </Button>
            </div>
          }
        />
        <CardBody className="flex flex-col gap-4">
          {campaign.loading && !data ? (
            <div className="flex flex-col gap-2" aria-busy="true">
              <div className="h-2 w-full animate-pulse rounded bg-line" />
              <div className="h-16 w-full animate-pulse rounded bg-line" />
              <div className="h-32 w-full animate-pulse rounded bg-line" />
            </div>
          ) : campaign.error ? (
            <ErrorBlock message={campaign.error} onRetry={campaign.reload} />
          ) : data && summary ? (
            <>
              <div className="flex flex-col gap-2">
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
                    {data.generated_at ? ` · ${formatDate(data.generated_at)}` : ""}
                  </span>
                </div>
                <ProgressBar value={summary.percent / 100} className="h-2" />
                <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                  <MetricTile label="Websites" value={summary.total} />
                  <MetricTile
                    label="Done"
                    value={`${summary.done} (${summary.percent}%)`}
                    hint={`${summary.verified} verified · ${summary.submitted} submitted`}
                    tone="success"
                  />
                  <MetricTile
                    label="In progress"
                    value={summary.in_progress + summary.waiting_manual}
                    hint={`${summary.in_progress} running · ${summary.waiting_manual} manual`}
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

              <div className="flex flex-col gap-2 rounded-lg border border-line bg-surface-raised/40 p-3">
                <Field
                  label="Add websites"
                  hint="Paste one or many URLs - separated by a comma, a space or a new line. Each site is added to the central list once and linked to this project."
                >
                  <Textarea
                    rows={2}
                    value={text}
                    onChange={(event) => setText(event.target.value)}
                    placeholder="example.com/add-listing, another-directory.com/submit"
                  />
                </Field>
                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    size="sm"
                    onClick={() => void addWebsites()}
                    loading={adding}
                    disabled={!text.trim()}
                  >
                    Add websites
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => fileRef.current?.click()}
                    loading={importing}
                  >
                    Import Excel / CSV
                  </Button>
                  {onPickFromList ? (
                    <Button size="sm" variant="outline" onClick={onPickFromList}>
                      Pick from list
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
                      addResult.invalid + addResult.deleted > 0
                        ? "warning"
                        : "success"
                    }
                    title={[
                      `${addResult.added} added`,
                      `${addResult.linked} linked`,
                      addResult.existing ? `${addResult.existing} already here` : "",
                      addResult.invalid ? `${addResult.invalid} invalid` : "",
                      addResult.deleted
                        ? `${addResult.deleted} in the recycle bin`
                        : "",
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
                            (row) =>
                              row.status === "invalid" || row.status === "deleted",
                          )
                          .map((row) => (
                            <li key={`${row.status}-${row.input}`}>
                              <span className="font-mono text-[11px]">{row.input}</span>{" "}
                              - {row.message}
                            </li>
                          ))}
                      </ul>
                    ) : (
                      "The rows were added to the central list and linked to this project."
                    )}
                  </Alert>
                ) : null}
              </div>

              {rows.length === 0 ? (
                <Alert tone="neutral" title="No websites in this project yet">
                  Paste the URLs above or import a spreadsheet. The central list is
                  not touched by other projects - every project picks its own
                  websites.
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
                    {rows.map((row) => (
                      <tr key={row.opportunity_id}>
                        <Td>
                          <div className="min-w-0">
                            <p
                              className="truncate text-sm font-medium text-content"
                              title={row.name}
                            >
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
                            <p className="text-[11px] text-content-subtle">
                              {row.category.replace(/_/g, " ")}
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
                          </div>
                        </Td>
                        <Td>
                          <Badge tone={STATUS_TONES[row.status]}>
                            {STATUS_LABELS[row.status]}
                          </Badge>
                        </Td>
                        <Td>
                          <span className="whitespace-nowrap text-[11px] text-content-muted">
                            {formatDate(row.last_update)}
                          </span>
                        </Td>
                        <Td>
                          <div className="flex flex-wrap items-center justify-end gap-1">
                            {row.status === "NEEDS_DETAILS" ? (
                              <Button size="sm" onClick={() => setDetailsRow(row)}>
                                Fill details
                              </Button>
                            ) : null}
                            {row.status === "WAITING_MANUAL" ? (
                              <Button size="sm" onClick={() => openSubmit(row)}>
                                Mark submitted
                              </Button>
                            ) : null}
                            {row.status === "SUBMITTED" ? (
                              <Button
                                size="sm"
                                variant="outline"
                                loading={busyRow === row.opportunity_id}
                                onClick={() => void verifyRow(row)}
                              >
                                Verify
                              </Button>
                            ) : null}
                            {row.status === "FAILED" && row.task_id ? (
                              <Button
                                size="sm"
                                variant="outline"
                                loading={busyRow === row.opportunity_id}
                                onClick={() => void retryRow(row)}
                              >
                                Retry
                              </Button>
                            ) : null}
                            {row.status === "VERIFICATION_FAILED" ? (
                              <>
                                <Button
                                  size="sm"
                                  variant="outline"
                                  loading={busyRow === row.opportunity_id}
                                  onClick={() => void verifyRow(row)}
                                >
                                  Verify again
                                </Button>
                                <Button size="sm" onClick={() => openSubmit(row)}>
                                  Mark submitted
                                </Button>
                              </>
                            ) : null}
                            {row.status === "VERIFIED" && row.published_page_url ? (
                              <a
                                href={row.published_page_url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="text-[11px] text-accent hover:underline"
                              >
                                View link
                              </a>
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
                          </div>
                        </Td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              )}

              <p className="text-[11px] text-content-muted">
                <strong className="font-semibold text-content">Data ready</strong> counts
                the values the website asks for (name, website, description, …) that are
                already filled or that the business profile supplies.{" "}
                <strong className="font-semibold text-content">Start backlinks</strong>{" "}
                writes the profile values; a site is never sent half filled. Sites without
                an automation stay at{" "}
                <span className="font-medium text-content">&quot;Submit by hand&quot;</span>
                : the details are ready, you submit them and press{" "}
                <span className="font-medium text-content">Mark submitted</span>.
              </p>
            </>
          ) : null}
        </CardBody>
      </Card>

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
            <Button onClick={() => void start()} loading={starting}>
              Start backlinks
            </Button>
          </>
        }
      >
        <ol className="list-decimal space-y-2 pl-4 text-xs text-content-muted">
          <li>
            The details of every website are filled from the business profile of the
            project. Manually edited values stay untouched.
          </li>
          <li>
            Every website with complete details is queued. The project is set to{" "}
            <strong className="text-content">Active</strong>.
          </li>
          <li>
            A site that still misses details is not queued - it appears in the table
            with the missing values.
          </li>
        </ol>
        <p className="mt-3 text-xs text-content-muted">
          {summary?.total ?? 0} website(s) in this project ·{" "}
          {summary?.needs_details ?? 0} currently need details ·{" "}
          {summary?.in_progress ?? 0} already queued.
        </p>
      </Dialog>

      <Dialog
        open={startResult !== null}
        onClose={() => setStartResult(null)}
        title="Backlink work started"
        footer={<Button onClick={() => setStartResult(null)}>Close</Button>}
      >
        {startResult ? (
          <div className="flex flex-col gap-3 text-xs text-content-muted">
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
                  Fill the missing values in the business profile (Settings) or per row
                  via &quot;Fill details&quot;, then press Start again.
                </p>
              </Alert>
            ) : (
              <p>Every website of this project has complete details.</p>
            )}
          </div>
        ) : null}
      </Dialog>

      <Dialog
        open={submitRow !== null}
        onClose={() => setSubmitRow(null)}
        title={
          submitRow ? `Mark submitted - ${submitRow.name}` : "Mark submitted"
        }
        description="Use this after you filled the form of the website by hand."
        footer={
          <>
            <Button variant="outline" onClick={() => setSubmitRow(null)}>
              Cancel
            </Button>
            <Button onClick={() => void markSubmitted()} loading={submitting}>
              Mark submitted
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-3">
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
          <Field
            label="Anchor text (optional)"
            hint="Defaults to the anchor text of the website."
          >
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

      {detailsRow ? (
        <SubmissionDetailsPanel
          opportunityId={detailsRow.opportunity_id}
          opportunityName={detailsRow.name}
          onClose={() => setDetailsRow(null)}
          onChanged={() => {
            campaign.reload();
            onChanged?.();
          }}
        />
      ) : null}
    </>
  );
}
