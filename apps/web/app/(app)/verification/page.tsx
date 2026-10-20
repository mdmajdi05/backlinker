"use client";

import * as React from "react";
import { api } from "@autobacklinker/api-client";
import type { BacklinkRecord } from "@autobacklinker/shared-types";
import {
  Badge,
  Button,
  Card,
  CardBody,
  Field,
  Pagination,
  Select,
  StatusBadge,
  Table,
  Td,
  Th,
  Toolbar,
  useToast,
} from "@autobacklinker/ui";
import { apiClient, errorMessage } from "@/lib/api";
import { useAction, useResource } from "@/lib/hooks";
import { formatDateTime } from "@/lib/format";
import { ALL_VERIFICATION_STATUSES, VERIFICATION_STATUS_LABELS } from "@/lib/constants";
import { PageHeader } from "@/components/PageHeader";
import { AsyncSection, TableSkeleton } from "@/components/States";
import { VerificationDrawer } from "@/components/VerificationDrawer";

const PAGE_SIZE = 25;

export default function VerificationPage() {
  const toast = useToast();
  const action = useAction();

  const [page, setPage] = React.useState(1);
  const [projectId, setProjectId] = React.useState("");
  const [status, setStatus] = React.useState("");
  const [selected, setSelected] = React.useState<string[]>([]);
  const [detail, setDetail] = React.useState<BacklinkRecord | null>(null);

  const projects = useResource(() => api.projects.list(apiClient, { page: 1, page_size: 100 }), []);

  const records = useResource(
    () =>
      api.verification.list(apiClient, {
        page,
        page_size: PAGE_SIZE,
        project_id: projectId || undefined,
        status: status || undefined,
      }),
    [page, projectId, status],
  );

  const rows = records.data?.items ?? [];

  React.useEffect(() => {
    setSelected([]);
  }, [page, projectId, status]);

  const runVerification = async (ids: string[] | undefined) => {
    const outcome = await action.run(() =>
      api.verification.run(apiClient, {
        backlink_ids: ids && ids.length > 0 ? ids : undefined,
        project_id: projectId || undefined,
      }),
    );
    if (outcome.ok && outcome.data) {
      toast.push(
        `Verification scheduled for ${outcome.data.scheduled} record(s)`,
        "success",
      );
      records.reload();
    }
  };

  const counters = React.useMemo(() => {
    const counts = { verified: 0, published: 0, failed: 0, other: 0 };
    for (const row of rows) {
      if (row.verification_status === "VERIFIED_LIVE") counts.verified += 1;
      else if (row.verification_status === "PUBLISHED_UNVERIFIED") counts.published += 1;
      else if (
        row.verification_status === "VERIFICATION_FAILED" ||
        row.verification_status === "REMOVED"
      ) {
        counts.failed += 1;
      } else counts.other += 1;
    }
    return counts;
  }, [rows]);

  return (
    <div className="space-y-4">
      <PageHeader
        title="Verification"
        description="Backlink records stored by the backend with their verification history."
        actions={
          <>
            <Button
              variant="outline"
              size="sm"
              onClick={() => runVerification(selected)}
              loading={action.pending}
              disabled={selected.length === 0}
              title={
                selected.length === 0
                  ? "Select the records that should be verified"
                  : undefined
              }
            >
              Verify selected ({selected.length})
            </Button>
            <Button size="sm" onClick={() => runVerification(undefined)} loading={action.pending}>
              Run verification
            </Button>
          </>
        }
      />

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardBody className="py-3">
            <p className="text-[11px] uppercase tracking-wide text-content-muted">Verified live</p>
            <p className="text-xl font-semibold tabular-nums text-content">{counters.verified}</p>
          </CardBody>
        </Card>
        <Card>
          <CardBody className="py-3">
            <p className="text-[11px] uppercase tracking-wide text-content-muted">
              Published, unverified
            </p>
            <p className="text-xl font-semibold tabular-nums text-content">{counters.published}</p>
          </CardBody>
        </Card>
        <Card>
          <CardBody className="py-3">
            <p className="text-[11px] uppercase tracking-wide text-content-muted">Failed</p>
            <p className="text-xl font-semibold tabular-nums text-content">{counters.failed}</p>
          </CardBody>
        </Card>
        <Card>
          <CardBody className="py-3">
            <p className="text-[11px] uppercase tracking-wide text-content-muted">Other states</p>
            <p className="text-xl font-semibold tabular-nums text-content">{counters.other}</p>
          </CardBody>
        </Card>
      </div>

      {action.error ? (
        <p className="text-xs text-danger">{errorMessage(action.error)}</p>
      ) : null}

      <Card>
        <Toolbar>
          <Field label="Project" className="w-52">
            <Select
              value={projectId}
              onChange={(event) => {
                setProjectId(event.target.value);
                setPage(1);
              }}
            >
              <option value="">All projects</option>
              {(projects.data?.items ?? []).map((project) => (
                <option key={project.id} value={project.id}>
                  {project.name}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Status" className="w-56">
            <Select
              value={status}
              onChange={(event) => {
                setStatus(event.target.value);
                setPage(1);
              }}
            >
              <option value="">All statuses</option>
              {ALL_VERIFICATION_STATUSES.map((value) => (
                <option key={value} value={value}>
                  {VERIFICATION_STATUS_LABELS[value] ?? value}
                </option>
              ))}
            </Select>
          </Field>
          <Button variant="ghost" size="sm" onClick={records.reload}>
            Refresh
          </Button>
        </Toolbar>

        <CardBody className="p-0">
          <AsyncSection
            loading={records.loading}
            error={records.error}
            data={records.data}
            onRetry={records.reload}
            isEmpty={rows.length === 0}
            emptyTitle="No backlink records yet"
            emptyDescription="Records are created once a submission task reports a published page."
            skeleton={<TableSkeleton rows={8} columns={7} />}
          >
            <Table>
              <thead>
                <tr>
                  <Th className="w-10">
                    <input
                      type="checkbox"
                      aria-label="Select all records on this page"
                      checked={rows.length > 0 && rows.every((row) => selected.includes(row.id))}
                      onChange={(event) =>
                        setSelected((prev) =>
                          event.target.checked
                            ? Array.from(new Set([...prev, ...rows.map((row) => row.id)]))
                            : prev.filter((id) => !rows.some((row) => row.id === id)),
                        )
                      }
                    />
                  </Th>
                  <Th>Published page</Th>
                  <Th>Expected destination</Th>
                  <Th className="w-48">Status</Th>
                  <Th className="w-28">HTTP</Th>
                  <Th className="w-36">Verified at</Th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id} className="cursor-pointer" onClick={() => setDetail(row)}>
                    <Td onClick={(event) => event.stopPropagation()}>
                      <input
                        type="checkbox"
                        aria-label={`Select record ${row.id}`}
                        checked={selected.includes(row.id)}
                        onChange={() =>
                          setSelected((prev) =>
                            prev.includes(row.id)
                              ? prev.filter((id) => id !== row.id)
                              : [...prev, row.id],
                          )
                        }
                      />
                    </Td>
                    <Td>
                      {row.published_page_url ? (
                        <a
                          href={row.published_page_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          onClick={(event) => event.stopPropagation()}
                          className="text-accent hover:underline"
                        >
                          {row.published_page_url}
                        </a>
                      ) : (
                        <span className="text-content-subtle">No published page stored</span>
                      )}
                      <p className="text-xs text-content-muted">{row.target_website}</p>
                    </Td>
                    <Td className="max-w-xs truncate text-xs">{row.expected_destination_url}</Td>
                    <Td>
                      <div className="flex flex-wrap items-center gap-1">
                        <StatusBadge status={row.verification_status} />
                        {row.is_live === true ? <Badge tone="success">live</Badge> : null}
                        {row.is_live === false ? <Badge tone="danger">missing</Badge> : null}
                      </div>
                    </Td>
                    <Td className="tabular-nums text-xs">
                      {row.http_status === null ? "—" : row.http_status}
                    </Td>
                    <Td className="text-xs text-content-muted">
                      {formatDateTime(row.verified_at)}
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
            {records.data ? (
              <Pagination
                page={records.data.page}
                pages={records.data.pages}
                total={records.data.total}
                onPageChange={setPage}
              />
            ) : null}
          </AsyncSection>
        </CardBody>
      </Card>

      <VerificationDrawer
        record={detail}
        open={Boolean(detail)}
        onClose={() => setDetail(null)}
      />
    </div>
  );
}
