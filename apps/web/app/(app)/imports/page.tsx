"use client";

import * as React from "react";
import { api } from "@autobacklinker/api-client";
import type { ImportAction, ImportJob, ImportPreview } from "@autobacklinker/shared-types";
import {
  Alert,
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  Checkbox,
  Field,
  Pagination,
  Select,
  StatusBadge,
  Table,
  Td,
  Th,
  useToast,
} from "@autobacklinker/ui";
import { apiClient, errorMessage } from "@/lib/api";
import { useAction, useResource } from "@/lib/hooks";
import { formatDateTime, formatNumber } from "@/lib/format";
import { ALL_IMPORT_ACTIONS, IMPORT_ACTION_LABELS } from "@/lib/constants";
import { PageHeader } from "@/components/PageHeader";
import { AsyncSection, TableSkeleton } from "@/components/States";

const PAGE_SIZE = 20;
const ALL_ACTIONS = ALL_IMPORT_ACTIONS as readonly ImportAction[];

export default function ImportsPage() {
  const toast = useToast();
  const action = useAction();
  const fileInputRef = React.useRef<HTMLInputElement | null>(null);

  const [page, setPage] = React.useState(1);
  const [projectId, setProjectId] = React.useState("");
  const [preview, setPreview] = React.useState<ImportPreview | null>(null);
  const [selectedActions, setSelectedActions] = React.useState<ImportAction[]>([...ALL_ACTIONS]);
  const [dragActive, setDragActive] = React.useState(false);
  const [uploading, setUploading] = React.useState(false);
  const [uploadError, setUploadError] = React.useState<string | null>(null);

  const projects = useResource(() => api.projects.list(apiClient, { page: 1, page_size: 100 }), []);
  const history = useResource(() => api.imports.list(apiClient, { page, page_size: PAGE_SIZE }), [page]);

  const upload = async (file: File) => {
    setUploading(true);
    setUploadError(null);
    try {
      const result = await api.imports.preview(apiClient, file, projectId || undefined);
      setPreview(result);
      setSelectedActions([...ALL_ACTIONS]);
      toast.push(`Preview generated for ${result.file_name}`, "success");
    } catch (err) {
      setUploadError(errorMessage(err));
      setPreview(null);
    } finally {
      setUploading(false);
    }
  };

  const commit = async (dryRun: boolean) => {
    if (!preview) return;
    const outcome = await action.run(() =>
      api.imports.commit(apiClient, preview.import_job_id, {
        apply_actions: selectedActions,
        dry_run: dryRun,
      }),
    );
    if (outcome.ok && outcome.data) {
      toast.push(
        dryRun
          ? `Dry run finished with status ${outcome.data.status}`
          : `Import committed with status ${outcome.data.status}`,
        "success",
      );
      history.reload();
      if (!dryRun) setPreview(null);
    }
  };

  const downloadErrorReport = async (jobId: string) => {
    try {
      await api.imports.errorReport(apiClient, jobId);
      toast.push("Error report downloaded", "success");
    } catch (err) {
      toast.push(errorMessage(err), "error");
    }
  };

  const grouped = React.useMemo(() => {
    if (!preview) return [];
    const order = [...ALL_ACTIONS];
    return order
      .map((actionName) => ({
        action: actionName,
        rows: preview.rows.filter((row) => row.action === actionName),
      }))
      .filter((group) => group.rows.length > 0);
  }, [preview]);

  const toggleAction = (actionName: ImportAction) => {
    setSelectedActions((prev) =>
      prev.includes(actionName)
        ? prev.filter((item) => item !== actionName)
        : [...prev, actionName],
    );
  };

  return (
    <div className="space-y-4">
      <PageHeader
        title="Import Center"
        description="Upload CSV or XLSX files, review the plan and commit it."
        actions={
          <Button variant="outline" size="sm" onClick={history.reload} loading={history.refreshing}>
            Refresh
          </Button>
        }
      />

      <Card>
        <CardHeader title="Upload file" description="CSV or XLSX with opportunity data" />
        <CardBody>
          <div className="grid gap-3 sm:grid-cols-[260px_1fr]">
            <Field label="Target project" hint="Optional — used to resolve existing rows.">
              <Select value={projectId} onChange={(event) => setProjectId(event.target.value)}>
                <option value="">No specific project</option>
                {(projects.data?.items ?? []).map((project) => (
                  <option key={project.id} value={project.id}>
                    {project.name}
                  </option>
                ))}
              </Select>
            </Field>

            <div
              onDragOver={(event) => {
                event.preventDefault();
                setDragActive(true);
              }}
              onDragLeave={() => setDragActive(false)}
              onDrop={(event) => {
                event.preventDefault();
                setDragActive(false);
                const file = event.dataTransfer.files?.[0];
                if (file) void upload(file);
              }}
              className={`flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed p-6 text-center transition-colors ${
                dragActive ? "border-accent bg-accent-soft" : "border-line bg-surface-raised"
              }`}
            >
              <p className="text-sm text-content">Drop a file here or choose one</p>
              <input
                ref={fileInputRef}
                type="file"
                accept=".csv,.xlsx,.xls"
                className="sr-only"
                id="import-file"
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) void upload(file);
                  event.target.value = "";
                }}
              />
              <Button
                type="button"
                variant="outline"
                loading={uploading}
                onClick={() => fileInputRef.current?.click()}
              >
                Choose file
              </Button>
              {uploadError ? (
                <p className="text-xs text-danger">{uploadError}</p>
              ) : null}
            </div>
          </div>
        </CardBody>
      </Card>

      {preview ? (
        <Card>
          <CardHeader
            title={`Preview · ${preview.file_name}`}
            description={`${formatNumber(preview.counts.total)} rows · job ${preview.import_job_id}`}
            action={
              <div className="flex gap-2">
                <Button variant="outline" size="sm" onClick={() => commit(true)} loading={action.pending}>
                  Dry run
                </Button>
                <Button
                  size="sm"
                  onClick={() => commit(false)}
                  loading={action.pending}
                  disabled={selectedActions.length === 0}
                  title={
                    selectedActions.length === 0
                      ? "Select at least one action to apply"
                      : undefined
                  }
                >
                  Apply import
                </Button>
              </div>
            }
          />
          <CardBody>
            <div className="space-y-4">
              <div>
                <p className="mb-2 text-xs font-semibold text-content">Detected column mapping</p>
                {preview.detected_mapping.length === 0 ? (
                  <p className="text-xs text-content-subtle">
                    The backend did not detect any column mapping.
                  </p>
                ) : (
                  <Table>
                    <thead>
                      <tr>
                        <Th>Source column</Th>
                        <Th>Target field</Th>
                        <Th className="w-28">Confidence</Th>
                        <Th className="w-24">Required</Th>
                      </tr>
                    </thead>
                    <tbody>
                      {preview.detected_mapping.map((mapping) => (
                        <tr key={mapping.source_column}>
                          <Td>{mapping.source_column}</Td>
                          <Td>{mapping.target_field}</Td>
                          <Td className="tabular-nums">
                            {Math.round((mapping.confidence ?? 0) * 100)}%
                          </Td>
                          <Td>
                            {mapping.required ? (
                              <Badge tone="warning">required</Badge>
                            ) : (
                              <Badge tone="neutral">optional</Badge>
                            )}
                          </Td>
                        </tr>
                      ))}
                    </tbody>
                  </Table>
                )}
              </div>

              <div>
                <p className="mb-2 text-xs font-semibold text-content">
                  Actions to apply
                </p>
                <div className="flex flex-wrap gap-3">
                  {ALL_ACTIONS.map((actionName) => (
                    <label key={actionName} className="flex items-center gap-2 text-xs text-content">
                      <Checkbox
                        checked={selectedActions.includes(actionName)}
                        onChange={() => toggleAction(actionName)}
                      />
                      {IMPORT_ACTION_LABELS[actionName] ?? actionName}
                      <span className="text-content-subtle">
                        ({formatNumber(preview.counts[actionName.toLowerCase() as keyof typeof preview.counts] ?? 0)})
                      </span>
                    </label>
                  ))}
                </div>
              </div>

              {grouped.map((group) => (
                <div key={group.action}>
                  <p className="mb-2 text-xs font-semibold text-content">
                    {IMPORT_ACTION_LABELS[group.action] ?? group.action} ·{" "}
                    {group.rows.length} row(s)
                  </p>
                  <Table>
                    <thead>
                      <tr>
                        <Th className="w-20">Row</Th>
                        <Th className="w-48">Reason</Th>
                        <Th>Values</Th>
                        <Th className="w-48">Errors</Th>
                      </tr>
                    </thead>
                    <tbody>
                      {group.rows.map((row) => (
                        <tr key={`${group.action}-${row.row_number}`}>
                          <Td className="tabular-nums">{row.row_number}</Td>
                          <Td className="text-xs">{row.reason || "—"}</Td>
                          <Td className="max-w-md">
                            <code className="block max-h-24 overflow-auto text-[11px] text-content-muted">
                              {JSON.stringify(row.values ?? {}, null, 2)}
                            </code>
                          </Td>
                          <Td className="text-xs text-danger">
                            {row.errors.length > 0 ? row.errors.join(", ") : "—"}
                          </Td>
                        </tr>
                      ))}
                    </tbody>
                  </Table>
                </div>
              ))}
            </div>
          </CardBody>
        </Card>
      ) : null}

      {action.error ? (
        <Alert tone="danger" title="Import failed">
          {errorMessage(action.error)}
        </Alert>
      ) : null}

      <Card>
        <CardHeader title="Import history" description="Previous import jobs" />
        <CardBody className="p-0">
          <AsyncSection
            loading={history.loading}
            error={history.error}
            data={history.data}
            onRetry={history.reload}
            isEmpty={(history.data?.items ?? []).length === 0}
            emptyTitle="No imports yet"
            emptyDescription="Uploaded files and their import jobs appear here."
            skeleton={<TableSkeleton rows={6} columns={8} />}
          >
            <Table>
              <thead>
                <tr>
                  <Th>File</Th>
                  <Th className="w-32">Status</Th>
                  <Th className="w-20 text-right">Total</Th>
                  <Th className="w-20 text-right">Created</Th>
                  <Th className="w-20 text-right">Updated</Th>
                  <Th className="w-20 text-right">Skipped</Th>
                  <Th className="w-20 text-right">Invalid</Th>
                  <Th className="w-36">Created at</Th>
                  <Th className="w-36">Error report</Th>
                </tr>
              </thead>
              <tbody>
                {(history.data?.items ?? []).map((job: ImportJob) => (
                  <tr key={job.id}>
                    <Td>{job.file_name}</Td>
                    <Td>
                      <StatusBadge status={job.status} />
                    </Td>
                    <Td className="text-right tabular-nums">{formatNumber(job.total_rows)}</Td>
                    <Td className="text-right tabular-nums">{formatNumber(job.created_count)}</Td>
                    <Td className="text-right tabular-nums">{formatNumber(job.updated_count)}</Td>
                    <Td className="text-right tabular-nums">{formatNumber(job.skipped_count)}</Td>
                    <Td className="text-right tabular-nums">{formatNumber(job.invalid_count)}</Td>
                    <Td className="text-xs text-content-muted">{formatDateTime(job.created_at)}</Td>
                    <Td>
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={job.invalid_count === 0 && job.conflict_count === 0}
                        onClick={() => downloadErrorReport(job.id)}
                        title={
                          job.invalid_count === 0 && job.conflict_count === 0
                            ? "This import has no invalid or conflicting rows"
                            : "Download the error report"
                        }
                      >
                        Download
                      </Button>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
            {history.data ? (
              <Pagination
                page={history.data.page}
                pages={history.data.pages}
                total={history.data.total}
                onPageChange={setPage}
              />
            ) : null}
          </AsyncSection>
        </CardBody>
      </Card>
    </div>
  );
}
