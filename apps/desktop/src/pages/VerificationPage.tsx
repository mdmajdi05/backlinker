import * as React from "react";
import {
  Badge,
  Button,
  Card,
  CardBody,
  Drawer,
  Pagination,
  StatusBadge,
  Table,
  Td,
  Th,
  useToast,
} from "@autobacklinker/ui";
import { api, apiClient } from "../lib/api";
import { useAsync } from "../lib/useAsync";
import { ErrorBlock, LoadingBlock, NothingYet, PageHeader } from "../components/common";
import { formatDate, hostOf, truncate } from "../lib/format";
import type { BacklinkRecord } from "@autobacklinker/shared-types";

const PAGE_SIZE = 25;

export function VerificationPage() {
  const toast = useToast();
  const [page, setPage] = React.useState(1);
  const [running, setRunning] = React.useState(false);
  const [selected, setSelected] = React.useState<BacklinkRecord | null>(null);

  const records = useAsync(
    () =>
      api.verification.list(apiClient, {
        page,
        page_size: PAGE_SIZE,
      }),
    [page],
  );

  const history = useAsync(
    () =>
      selected
        ? api.verification.history(apiClient, selected.id)
        : Promise.resolve([]),
    [selected?.id],
  );

  const items = records.data?.items ?? [];

  async function runVerification() {
    setRunning(true);
    try {
      const result = await api.verification.run(apiClient, { force: false });
      toast.push(`${result.scheduled} records queued for verification`, "success");
      records.reload();
    } catch (err) {
      toast.push(
        err && typeof err === "object" && "message" in err
          ? String((err as { message: unknown }).message)
          : "Could not schedule the verification run",
        "error",
      );
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Verification"
        description="Backlink records and the verification history of every link."
        actions={
          <Button loading={running} onClick={runVerification}>
            Run verification
          </Button>
        }
      />

      {records.loading && !records.data ? <LoadingBlock /> : null}
      {records.error ? (
        <ErrorBlock message={records.error} onRetry={records.reload} />
      ) : null}

      {!records.loading && items.length === 0 && !records.error ? (
        <NothingYet
          title="No backlink records"
          description="Records appear here once a submission has been published."
        />
      ) : null}

      {items.length > 0 ? (
        <Card>
          <CardBody className="p-0">
            <Table>
              <thead>
                <tr>
                  <Th>Published page</Th>
                  <Th>Expected link</Th>
                  <Th>Destination</Th>
                  <Th>Status</Th>
                  <Th>HTTP</Th>
                  <Th>Verified</Th>
                  <Th>Next run</Th>
                  <Th />
                </tr>
              </thead>
              <tbody>
                {items.map((record: BacklinkRecord) => (
                  <tr key={record.id}>
                    <Td className="max-w-[240px] truncate text-xs">
                      {record.published_page_url ?? "-"}
                    </Td>
                    <Td className="max-w-[200px] truncate text-xs">
                      {hostOf(record.expected_link_url)}
                    </Td>
                    <Td className="max-w-[200px] truncate text-xs text-content-muted">
                      {record.expected_destination_url}
                    </Td>
                    <Td>
                      <StatusBadge status={record.verification_status} />
                    </Td>
                    <Td className="text-xs">
                      {record.http_status ?? "-"}
                    </Td>
                    <Td className="whitespace-nowrap text-xs text-content-muted">
                      {formatDate(record.verified_at)}
                    </Td>
                    <Td className="whitespace-nowrap text-xs text-content-muted">
                      {formatDate(record.next_verification_at)}
                    </Td>
                    <Td className="text-right">
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => setSelected(record)}
                      >
                        History
                      </Button>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
            <Pagination
              page={page}
              pages={records.data?.pages ?? 1}
              total={records.data?.total ?? 0}
              onPageChange={setPage}
            />
          </CardBody>
        </Card>
      ) : null}

      <Drawer
        open={selected !== null}
        onClose={() => setSelected(null)}
        title="Verification history"
        width="lg"
      >
        {selected ? (
          <div className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone="accent">{selected.verification_status}</Badge>
              <span className="text-xs text-content-muted">
                {truncate(selected.published_page_url ?? "-", 60)}
              </span>
            </div>

            {history.loading ? <LoadingBlock rows={3} /> : null}
            {history.error ? (
              <ErrorBlock
                message={history.error}
                onRetry={history.reload}
              />
            ) : null}
            {(history.data ?? []).length > 0 ? (
              <Table>
                <thead>
                  <tr>
                    <Th>When</Th>
                    <Th>Status</Th>
                    <Th>HTTP</Th>
                    <Th>Anchor</Th>
                    <Th>Error</Th>
                  </tr>
                </thead>
                <tbody>
                  {(history.data ?? []).map((run) => (
                    <tr key={run.id}>
                      <Td className="whitespace-nowrap text-xs">
                        {formatDate(run.verified_at)}
                      </Td>
                      <Td>
                        <StatusBadge status={run.status} />
                      </Td>
                      <Td className="text-xs">{run.http_status ?? "-"}</Td>
                      <Td className="max-w-[160px] truncate text-xs">
                        {run.observed_anchor_text ?? "-"}
                      </Td>
                      <Td className="max-w-[200px] truncate text-xs text-danger">
                        {run.error ?? "-"}
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            ) : history.loading ? null : (
              <NothingYet
                title="No verification runs"
                description="This record has not been verified yet."
              />
            )}
          </div>
        ) : null}
      </Drawer>
    </div>
  );
}
