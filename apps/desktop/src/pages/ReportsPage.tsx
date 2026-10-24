import * as React from "react";
import {
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
import { api, apiClient } from "../lib/api";
import { useAsync } from "../lib/useAsync";
import { ErrorBlock, LoadingBlock, NothingYet, PageHeader } from "../components/common";
import { formatDate, formatNumber, truncate } from "../lib/format";
import { saveBytes } from "../lib/backend";
import { navigate } from "../lib/router";
import { fetchWebsiteStats } from "../lib/websites";
import type { ExportJob, Project } from "@autobacklinker/shared-types";

const PAGE_SIZE = 20;

/**
 * The project the reports view opens with.
 *
 * The desktop router only knows the plain route names - a project is handed
 * over to the next mount of the reports view instead of being part of the
 * hash.
 */
let pendingProjectId = "";

/** Opens the reports view with the given project preselected. */
export function openReportForProject(projectId: string): void {
  pendingProjectId = projectId;
  navigate("reports");
}

export function ReportsPage() {
  const toast = useToast();
  const [page, setPage] = React.useState(1);
  const [projectId, setProjectId] = React.useState("");
  const [format, setFormat] = React.useState<"xlsx" | "csv">("xlsx");
  const [generating, setGenerating] = React.useState(false);
  const [downloadingId, setDownloadingId] = React.useState<string | null>(null);

  const projects = useAsync(
    () => api.projects.list(apiClient, { page: 1, page_size: 100 }),
    [],
  );
  const reports = useAsync(
    () =>
      api.reports.list(apiClient, {
        page,
        page_size: PAGE_SIZE,
        project_id: projectId || undefined,
      }),
    [page, projectId],
  );
  const websiteStats = useAsync(
    () => fetchWebsiteStats(projectId || undefined),
    [projectId],
  );

  // A project that was handed over by the project page is preselected.
  const bootstrapped = React.useRef(false);
  React.useEffect(() => {
    if (bootstrapped.current) return;
    bootstrapped.current = true;
    if (!pendingProjectId) return;
    setProjectId(pendingProjectId);
    pendingProjectId = "";
  }, []);

  const items = reports.data?.items ?? [];

  async function generate() {
    setGenerating(true);
    try {
      await api.reports.generate(apiClient, {
        project_id: projectId || undefined,
        format,
      });
      toast.push("Report generation started", "success");
      reports.reload();
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

  const statsRows = websiteStats.data ?? [];

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Reports"
        description="Generated exports. Downloads are saved with the native dialog."
        actions={
          <Button
            size="sm"
            variant="outline"
            onClick={() => navigate("projects")}
          >
            Open My projects
          </Button>
        }
      />

      <p className="text-xs text-content-muted">
        To retry failed websites, open a project and press{" "}
        <span className="font-medium text-content">Restart failed</span>.
      </p>

      <Card>
        <CardHeader title="Generate a report" />
        <CardBody>
          <div className="flex flex-wrap items-end gap-3">
            <div className="w-72">
              <Field label="Project">
                <Select
                  value={projectId}
                  onChange={(event) => {
                    setProjectId(event.target.value);
                    setPage(1);
                  }}
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
        />
        <CardBody className="p-0">
          {websiteStats.loading && !websiteStats.data ? (
            <div className="p-4">
              <LoadingBlock rows={4} />
            </div>
          ) : null}

          {websiteStats.error ? (
            <div className="p-4">
              <ErrorBlock
                message={websiteStats.error}
                onRetry={websiteStats.reload}
              />
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
                  </tr>
                ))}
              </tbody>
            </Table>
          ) : null}

          <p className="border-t border-line px-4 py-3 text-xs text-content-muted">
            Verified links are never submitted again. Use Imports to bring a
            report back in - verified rows are skipped, failed rows are
            retried.
          </p>
        </CardBody>
      </Card>
    </div>
  );
}
