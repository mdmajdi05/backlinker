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
import { pickAndReadFile } from "../lib/backend";
import type { ImportJob, ImportPreview, Project } from "@autobacklinker/shared-types";

const PAGE_SIZE = 20;

const IMPORT_FILTERS = [
  { name: "Excel", extensions: ["xlsx", "xls"] },
  { name: "CSV", extensions: ["csv"] },
];

export function ImportsPage() {
  const toast = useToast();
  const [page, setPage] = React.useState(1);
  const [projectId, setProjectId] = React.useState("");
  const [picked, setPicked] = React.useState<{ name: string; size: number } | null>(
    null,
  );
  const [preview, setPreview] = React.useState<ImportPreview | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const projects = useAsync(
    () => api.projects.list(apiClient, { page: 1, page_size: 100 }),
    [],
  );
  const jobs = useAsync(
    () => api.imports.list(apiClient, { page, page_size: PAGE_SIZE }),
    [page],
  );

  async function chooseFile() {
    setBusy(true);
    setError(null);
    try {
      const file = await pickAndReadFile(IMPORT_FILTERS);
      if (!file) {
        setBusy(false);
        return;
      }
      setPicked({ name: file.name, size: file.bytes.byteLength });
      const blob = new Blob([file.bytes.slice().buffer], {
        type: file.name.endsWith(".csv")
          ? "text/csv"
          : "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      });
      const handle = new File([blob], file.name, {
        type: blob.type,
      });
      const result = await api.imports.preview(
        apiClient,
        handle,
        projectId || undefined,
      );
      setPreview(result);
      toast.push(`Preview ready: ${result.rows.length} rows`, "success");
    } catch (err) {
      setError(
        err && typeof err === "object" && "message" in err
          ? String((err as { message: unknown }).message)
          : "Could not read the selected file",
      );
      setPreview(null);
    } finally {
      setBusy(false);
    }
  }

  async function commit(dryRun: boolean) {
    if (!preview) return;
    setBusy(true);
    try {
      const job = await api.imports.commit(apiClient, preview.import_job_id, {
        dry_run: dryRun,
      });
      toast.push(
        dryRun
          ? "Dry run finished"
          : `Import committed: ${job.created_count} created, ${job.updated_count} updated`,
        "success",
      );
      setPreview(null);
      setPicked(null);
      jobs.reload();
    } catch (err) {
      toast.push(
        err && typeof err === "object" && "message" in err
          ? String((err as { message: unknown }).message)
          : "Could not commit the import",
        "error",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Imports"
        description="Import opportunities from an Excel or CSV file stored on this machine."
      />

      <Card>
        <CardHeader
          title="Local import"
          description="The file never leaves this device except through your own backend."
        />
        <CardBody>
          <div className="flex flex-wrap items-end gap-3">
            <div className="w-72">
              <Field label="Target project">
                <Select
                  value={projectId}
                  onChange={(event) => setProjectId(event.target.value)}
                >
                  <option value="">No project (preview only)</option>
                  {(projects.data?.items ?? []).map((project: Project) => (
                    <option key={project.id} value={project.id}>
                      {project.name}
                    </option>
                  ))}
                </Select>
              </Field>
            </div>
            <Button loading={busy} onClick={chooseFile}>
              Choose file…
            </Button>
            {picked ? (
              <p className="pb-2 text-xs text-content-muted">
                {picked.name} · {formatNumber(Math.round(picked.size / 1024))} KB
              </p>
            ) : null}
          </div>

          {error ? (
            <div className="mt-3">
              <ErrorBlock message={error} />
            </div>
          ) : null}
        </CardBody>
      </Card>

      {preview ? (
        <Card>
          <CardHeader
            title={`Preview · ${preview.file_name}`}
            description={`${preview.rows.length} rows · ${preview.sheets.join(", ")}`}
            action={
              <div className="flex gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  disabled={busy}
                  onClick={() => commit(true)}
                >
                  Dry run
                </Button>
                <Button size="sm" disabled={busy} onClick={() => commit(false)}>
                  Apply import
                </Button>
              </div>
            }
          />
          <CardBody className="p-0">
            <div className="flex flex-wrap gap-2 border-b border-line px-4 py-3">
              <Badge tone="success">create {preview.counts.create}</Badge>
              <Badge tone="accent">update {preview.counts.update}</Badge>
              <Badge tone="neutral">skip {preview.counts.skip}</Badge>
              <Badge tone="warning">conflict {preview.counts.conflict}</Badge>
              <Badge tone="danger">invalid {preview.counts.invalid}</Badge>
              <Badge tone="info">verify {preview.counts.verify}</Badge>
            </div>
            <Table>
              <thead>
                <tr>
                  <Th>Row</Th>
                  <Th>Action</Th>
                  <Th>Reason</Th>
                  <Th>Opportunity</Th>
                  <Th>Errors</Th>
                </tr>
              </thead>
              <tbody>
                {preview.rows.slice(0, 100).map((row) => (
                  <tr key={row.row_number}>
                    <Td className="text-xs">{row.row_number}</Td>
                    <Td>
                      <Badge
                        tone={
                          row.action === "CREATE"
                            ? "success"
                            : row.action === "UPDATE"
                              ? "accent"
                              : row.action === "INVALID" ||
                                  row.action === "CONFLICT"
                                ? "danger"
                                : "neutral"
                        }
                      >
                        {row.action}
                      </Badge>
                    </Td>
                    <Td className="max-w-[260px] truncate text-xs">
                      {row.reason}
                    </Td>
                    <Td className="text-xs text-content-muted">
                      {row.opportunity_id ?? "-"}
                    </Td>
                    <Td className="max-w-[220px] truncate text-xs text-danger">
                      {row.errors.length > 0 ? row.errors.join(", ") : "-"}
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </CardBody>
        </Card>
      ) : null}

      <Card>
        <CardHeader title="Import history" />
        <CardBody className="p-0">
          {jobs.loading && !jobs.data ? (
            <div className="p-4">
              <LoadingBlock rows={3} />
            </div>
          ) : jobs.error ? (
            <div className="p-4">
              <ErrorBlock message={jobs.error} onRetry={jobs.reload} />
            </div>
          ) : (jobs.data?.items ?? []).length === 0 ? (
            <NothingYet
              title="No imports yet"
              description="Pick a spreadsheet to create the first import job."
            />
          ) : (
            <>
              <Table>
                <thead>
                  <tr>
                    <Th>File</Th>
                    <Th>Status</Th>
                    <Th className="text-right">Created</Th>
                    <Th className="text-right">Updated</Th>
                    <Th className="text-right">Skipped</Th>
                    <Th className="text-right">Invalid</Th>
                    <Th>Started</Th>
                    <Th>Committed</Th>
                  </tr>
                </thead>
                <tbody>
                  {(jobs.data?.items ?? []).map((job: ImportJob) => (
                    <tr key={job.id}>
                      <Td className="max-w-[240px] truncate text-xs">
                        {job.file_name}
                      </Td>
                      <Td>
                        <StatusBadge status={job.status} />
                      </Td>
                      <Td className="text-right text-xs">
                        {formatNumber(job.created_count)}
                      </Td>
                      <Td className="text-right text-xs">
                        {formatNumber(job.updated_count)}
                      </Td>
                      <Td className="text-right text-xs">
                        {formatNumber(job.skipped_count)}
                      </Td>
                      <Td className="text-right text-xs">
                        {formatNumber(job.invalid_count)}
                      </Td>
                      <Td className="whitespace-nowrap text-xs text-content-muted">
                        {formatDate(job.created_at)}
                      </Td>
                      <Td className="whitespace-nowrap text-xs text-content-muted">
                        {formatDate(job.committed_at)}
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
              <Pagination
                page={page}
                pages={jobs.data?.pages ?? 1}
                total={jobs.data?.total ?? 0}
                onPageChange={setPage}
              />
            </>
          )}
        </CardBody>
      </Card>
    </div>
  );
}
