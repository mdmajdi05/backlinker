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
import { formatDate, formatNumber } from "../lib/format";
import { saveBytes } from "../lib/backend";
import type { ExportJob, Project } from "@autobacklinker/shared-types";

const PAGE_SIZE = 20;

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
    () => api.reports.list(apiClient, { page, page_size: PAGE_SIZE }),
    [page],
  );

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
                  onChange={(event) =>
                    setFormat(event.target.value as "xlsx" | "csv")
                  }
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
    </div>
  );
}
