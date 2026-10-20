import * as React from "react";
import {
  Badge,
  Card,
  CardBody,
  Pagination,
  Table,
  Td,
  Th,
} from "@autobacklinker/ui";
import { api, apiClient } from "../lib/api";
import { useAsync } from "../lib/useAsync";
import { ErrorBlock, LoadingBlock, NothingYet, PageHeader } from "../components/common";
import { formatDate, formatRelative } from "../lib/format";
import type { ActivityEvent } from "@autobacklinker/shared-types";

const PAGE_SIZE = 30;

export function ActivityPage() {
  const [page, setPage] = React.useState(1);
  const events = useAsync(
    () => api.activity.list(apiClient, { page, page_size: PAGE_SIZE }),
    [page],
  );

  const items = events.data?.items ?? [];

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Activity"
        description="The persisted event log of the backend."
      />

      {events.loading && !events.data ? <LoadingBlock /> : null}
      {events.error ? (
        <ErrorBlock message={events.error} onRetry={events.reload} />
      ) : null}

      {!events.loading && items.length === 0 && !events.error ? (
        <NothingYet
          title="No activity"
          description="The backend has not recorded any event yet."
        />
      ) : null}

      {items.length > 0 ? (
        <Card>
          <CardBody className="p-0">
            <Table>
              <thead>
                <tr>
                  <Th>When</Th>
                  <Th>Type</Th>
                  <Th>Message</Th>
                  <Th>Level</Th>
                  <Th>Environment</Th>
                  <Th>Project</Th>
                </tr>
              </thead>
              <tbody>
                {items.map((event: ActivityEvent) => (
                  <tr key={event.id}>
                    <Td
                      className="whitespace-nowrap text-xs text-content-muted"
                      title={formatDate(event.created_at)}
                    >
                      {formatRelative(event.created_at)}
                    </Td>
                    <Td className="whitespace-nowrap text-xs">
                      {event.event_type}
                    </Td>
                    <Td className="text-xs">{event.message}</Td>
                    <Td>
                      <Badge
                        tone={
                          event.level === "ERROR"
                            ? "danger"
                            : event.level === "WARNING"
                              ? "warning"
                              : event.level === "SUCCESS"
                                ? "success"
                                : "neutral"
                        }
                      >
                        {event.level}
                      </Badge>
                    </Td>
                    <Td className="text-xs">
                      {event.execution_environment ?? "-"}
                    </Td>
                    <Td className="max-w-[180px] truncate text-xs text-content-muted">
                      {event.project_name ?? event.project_id ?? "-"}
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
            <Pagination
              page={page}
              pages={events.data?.pages ?? 1}
              total={events.data?.total ?? 0}
              onPageChange={setPage}
            />
          </CardBody>
        </Card>
      ) : null}
    </div>
  );
}
