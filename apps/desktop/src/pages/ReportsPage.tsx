import * as React from "react";
import {
  Alert,
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  Field,
  Pagination,
  Select,
  StatusBadge,
  Table,
  Td,
  Th,
  useToast,
} from "@autobacklinker/ui";
import { api, apiClient, isMissingEndpoint } from "../lib/api";
import { useAsync } from "../lib/useAsync";
import { ErrorBlock, LoadingBlock, NothingYet, PageHeader } from "../components/common";
import { formatDate, formatNumber, truncate } from "../lib/format";
import { saveBytes, sendNativeNotification } from "../lib/backend";
import { fetchWebsiteStats, retryFailedSubmissions } from "../lib/websites";
import type { ExportJob, Project } from "@autobacklinker/shared-types";

const PAGE_SIZE = 20;

export function ReportsPage() {
  const toast = useToast();
  const [page, setPage] = React.useState(1);
  const [projectId, setProjectId] = React.useState("");
  const [format, setFormat] = React.useState<"xlsx" | "csv">("xlsx");
  const [generating, setGenerating] = React.useState(false);
  const [downloadingId, setDownloadingId] = React.useState<string | null>(null);

  // The retry of the failed submissions works on a report - the operator
  // picks the report the retry should use.
  const [retryScope, setRetryScope] = React.useState("");
  const [retrying, setRetrying] = React.useState<string | null>(null);
  const [retrySupported, setRetrySupported] = React.useState<boolean | null>(null);

  const projects = useAsync(
    () => api.projects.list(apiClient, { page: 1, page_size: 100 }),
    [],
  );
  const reports = useAsync(
    () => api.reports.list(apiClient, { page, page_size: PAGE_SIZE }),
    [page],
  );
  const scopeReports = useAsync(
    () => api.reports.list(apiClient, { page: 1, page_size: 50 }),
    [],
  );
  const websiteStats = useAsync(
    () => fetchWebsiteStats(projectId || undefined),
    [projectId],
  );

  const items = reports.data?.items ?? [];

  // The newest report that is finished is the default scope of the retry.
  React.useEffect(() => {
    if (retryScope) return;
    const candidates = scopeReports.data?.items ?? [];
    const first =
      candidates.find((job) => job.status === "COMPLETED") ?? candidates[0];
    if (first) setRetryScope(first.id);
  }, [scopeReports.data, retryScope]);

  async function generate() {
    setGenerating(true);
    try {
      await api.reports.generate(apiClient, {
        project_id: projectId || undefined,
        format,
      });
      toast.push("Report generation started", "success");
      reports.reload();
      scopeReports.reload();
    } catch (err) {
      toast.push(
        err && typeof err === "object" && "message" in err
          ? String((err as { message: unknown }).message)
          : "Could not generate the report",
        "error",
      );
    } finally {
      setGenerating(false);
    }
  }

  async function download(job: ExportJob) {
    setDownloadingId(job.id);
    try {
      const response = await fetch(
        `${apiClient.baseUrl}/api/v1/reports/${job.id}/download`,
        {
          headers: apiClient.token
            ? { Authorization: `Bearer ${apiClient.token}` }
            : undefined,
        },
      );
      if (!response.ok) {
        throw new Error(`Download failed with status ${response.status}`);
      }
      const blob = await response.blob();
      const bytes = new Uint8Array(await blob.arrayBuffer());
      const fileName = job.file_name ?? `report-${job.id}.${format}`;

      let saved = false;
      try {
        const path = await saveBytes(
          fileName,
          bytes,
          format === "csv"
            ? [{ name: "CSV", extensions: ["csv"] }]
            : [{ name: "Excel", extensions: ["xlsx"] }],
        );
        if (path) {
          saved = true;
          toast.push(`Saved to ${path}`, "success");
        }
      } catch {
        saved = false;
      }

      if (!saved) {
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement("a");
        anchor.href = url;
        anchor.download = fileName;
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
        URL.revokeObjectURL(url);
        toast.push("Download started", "info");
      }
    } catch (err) {
      toast.push(
        err && typeof err === "object" && "message" in err
          ? String((err as { message: unknown }).message)
          : "Could not download the report",
        "error",
      );
    } finally {
      setDownloadingId(null);
    }
  }

  async function retryFailed(domain?: string) {
    if (!retryScope) return;
    setRetrying(domain ?? "");
    try {
      const outcome = await retryFailedSubmissions(retryScope, {
        domain,
        project_id: projectId || undefined,
      });
      setRetrySupported(true);
      const message =
        outcome.retried !== null
          ? `${outcome.retried} failed submission${
              outcome.retried === 1 ? "" : "s"
            } queued again`
          : "The failed submissions were queued again";
      toast.push(message, "success");
      void sendNativeNotification("Auto Backlinker", `${message}.`);
      websiteStats.reload();
    } catch (err) {
      if (isMissingEndpoint(err)) {
        // The endpoint does not exist in this backend - the control stays
        // disabled and says why.
        setRetrySupported(false);
        toast.push(
          "This backend does not support the retry of failed submissions",
          "error",
        );
      } else {
        toast.push(
          err && typeof err === "object" && "message" in err
            ? String((err as { message: unknown }).message)
            : "Could not retry the failed submissions",
          "error",
        );
      }
    } finally {
      setRetrying(null);
    }
  }

  const statsRows = websiteStats.data ?? [];
  const statsMissing =
    Boolean(websiteStats.error) && isMissingEndpoint(websiteStats.error);
  const scopeOptions = scopeReports.data?.items ?? [];

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Reports"
        description="Generated exports. Downloads are saved with the native dialog."
      />

      <Card>
        <CardHeader title="Generate a report" />
        <CardBody>
          <div className="flex flex-wrap items-end gap-3">
            <div className="w-72">
              <Field label="Project">
                <Select
                  value={projectId}
                  onChange={(event) => setProjectId(event.target.value)}
                >
                  <option value="">All projects</option>
                  {(projects.data?.items ?? []).map((project: Project) => (
                    <option key={project.id} value={project.id}>
                      {project.name}
                    </option>
                  ))}
                </Select>
              </Field>
            </div>
            <div className="w-40">
              <Field label="Format">
                <Select
                  value={format}
                  onChange={(event) => setFormat(event.target.value as "xlsx" | "csv")}
                >
                  <option value="xlsx">Excel (.xlsx)</option>
                  <option value="csv">CSV</option>
                </Select>
              </Field>
            </div>
            <Button loading={generating} onClick={generate}>
              Generate
            </Button>
          </div>
        </CardBody>
      </Card>

      {reports.loading && !reports.data ? <LoadingBlock /> : null}
      {reports.error ? (
        <ErrorBlock message={reports.error} onRetry={reports.reload} />
      ) : null}

      {!reports.loading && items.length === 0 && !reports.error ? (
        <NothingYet
          title="No reports yet"
          description="Generate a report to export opportunities, tasks and verification results."
        />
      ) : null}

      {items.length > 0 ? (
        <Card>
          <CardBody className="p-0">
            <Table>
              <thead>
                <tr>
                  <Th>File</Th>
                  <Th>Scope</Th>
                  <Th>Format</Th>
                  <Th>Status</Th>
                  <Th className="text-right">Rows</Th>
                  <Th>Created</Th>
                  <Th>Completed</Th>
                  <Th />
                </tr>
              </thead>
              <tbody>
                {items.map((job: ExportJob) => (
                  <tr key={job.id}>
                    <Td className="max-w-[260px] truncate text-xs">
                      {job.file_name ?? "-"}
                    </Td>
                    <Td className="text-xs">{job.scope}</Td>
                    <Td>
                      <Badge tone="neutral">{job.format}</Badge>
                    </Td>
                    <Td>
                      <StatusBadge status={job.status} />
                    </Td>
                    <Td className="text-right text-xs">
                      {formatNumber(job.row_count)}
                    </Td>
                    <Td className="whitespace-nowrap text-xs text-content-muted">
                      {formatDate(job.created_at)}
                    </Td>
                    <Td className="whitespace-nowrap text-xs text-content-muted">
                      {formatDate(job.completed_at)}
                    </Td>
                    <Td className="text-right">
                      <Button
                        size="sm"
                        variant="outline"
                        loading={downloadingId === job.id}
                        disabled={job.status !== "COMPLETED"}
                        onClick={() => download(job)}
                      >
                        Save as…
                      </Button>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
            <Pagination
              page={page}
              pages={reports.data?.pages ?? 1}
              total={reports.data?.total ?? 0}
              onPageChange={setPage}
            />
          </CardBody>
        </Card>
      ) : null}

      <Card>
        <CardHeader
          title="Per website"
          description="How many submissions succeeded on every website - and how many failed. The project filter above applies here as well."
          action={
            <div className="flex flex-wrap items-center gap-2">
              <Select
                aria-label="The report the retry works on"
                value={retryScope}
                disabled={scopeOptions.length === 0}
                onChange={(event) => setRetryScope(event.target.value)}
                className="h-8 w-56 text-xs"
              >
                {scopeOptions.length === 0 ? (
                  <option value="">No report yet</option>
                ) : null}
                {scopeOptions.map((job) => (
                  <option key={job.id} value={job.id}>
                    {job.file_name ?? job.id} · {formatDate(job.created_at)}
                  </option>
                ))}
              </Select>
              <Button
                size="sm"
                variant="outline"
                loading={retrying === ""}
                disabled={
                  !retryScope ||
                  retrySupported === false ||
                  retrying !== null
                }
                onClick={() => void retryFailed()}
              >
                Retry all failed
              </Button>
            </div>
          }
        />
        <CardBody className="p-0">
          {retrySupported === false ? (
            <div className="border-b border-line p-4">
              <Alert
                tone="warning"
                title="This backend can not retry the failed submissions"
              >
                The endpoint <code>/api/v1/reports/{"{id}"}/retry-failed</code>{" "}
                answers with 404. The button stays disabled until the backend
                knows it - nothing was retried.
              </Alert>
            </div>
          ) : null}

          {!retryScope && scopeOptions.length === 0 ? (
            <div className="border-b border-line p-4">
              <Alert
                tone="neutral"
                title="The retry needs a report"
              >
                Generate a report first - the retry of the failed submissions
                works on the rows of a report.
              </Alert>
            </div>
          ) : null}

          {websiteStats.loading && !websiteStats.data ? (
            <div className="p-4">
              <LoadingBlock rows={4} />
            </div>
          ) : null}

          {websiteStats.error && !statsMissing ? (
            <div className="p-4">
              <ErrorBlock
                message={websiteStats.error}
                onRetry={websiteStats.reload}
              />
            </div>
          ) : null}

          {statsMissing ? (
            <div className="p-4">
              <Alert
                tone="warning"
                title="The backend does not report the per website statistics yet"
              >
                The endpoint <code>/api/v1/websites/stats</code> answers with
                404. The counters of every website need a newer backend.
              </Alert>
            </div>
          ) : null}

          {!websiteStats.loading &&
          !websiteStats.error &&
          statsRows.length === 0 ? (
            <div className="p-4">
              <NothingYet
                title="No website in the statistics"
                description="As soon as a website is used, the counters of its submissions show up here."
              />
            </div>
          ) : null}

          {statsRows.length > 0 ? (
            <Table>
              <thead>
                <tr>
                  <Th>Website</Th>
                  <Th>Category</Th>
                  <Th>State</Th>
                  <Th className="text-right">Opportunities</Th>
                  <Th className="text-right">Submitted</Th>
                  <Th className="text-right">Verified</Th>
                  <Th className="text-right">Failed</Th>
                  <Th className="text-right">Pending</Th>
                  <Th className="text-right">Waiting</Th>
                  <Th>Last attempt</Th>
                  <Th />
                </tr>
              </thead>
              <tbody>
                {statsRows.map((row) => (
                  <tr key={`${row.domain}-${row.name}`}>
                    <Td>
                      <div className="min-w-0">
                        <p className="truncate text-sm text-content">
                          {row.name || row.domain}
                        </p>
                        <p className="truncate text-xs text-content-subtle">
                          {row.domain || "-"}
                        </p>
                      </div>
                    </Td>
                    <Td className="whitespace-nowrap text-xs">
                      {truncate(row.category.replace(/_/g, " "), 22)}
                    </Td>
                    <Td>
                      <StatusBadge status={row.status} />
                    </Td>
                    <Td className="text-right text-xs tabular-nums">
                      {formatNumber(row.opportunities)}
                    </Td>
                    <Td className="text-right text-xs tabular-nums text-accent">
                      {formatNumber(row.submitted)}
                    </Td>
                    <Td className="text-right text-xs tabular-nums text-success">
                      {formatNumber(row.verified)}
                    </Td>
                    <Td className="text-right text-xs tabular-nums text-danger">
                      {formatNumber(row.failed)}
                    </Td>
                    <Td className="text-right text-xs tabular-nums text-content-muted">
                      {formatNumber(row.pending)}
                    </Td>
                    <Td className="text-right text-xs tabular-nums text-content-muted">
                      {formatNumber(row.waiting_for_details)}
                    </Td>
                    <Td className="whitespace-nowrap text-xs text-content-muted">
                      {formatDate(row.last_attempt_at)}
                    </Td>
                    <Td className="whitespace-nowrap text-right">
                      <Button
                        size="sm"
                        variant="outline"
                        loading={retrying === row.domain}
                        disabled={
                          row.failed === 0 ||
                          !retryScope ||
                          retrySupported === false ||
                          retrying !== null
                        }
                        onClick={() => void retryFailed(row.domain)}
                      >
                        Retry failed
                      </Button>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          ) : null}
        </CardBody>
      </Card>
    </div>
  );
}
