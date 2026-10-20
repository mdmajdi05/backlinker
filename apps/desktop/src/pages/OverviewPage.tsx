import * as React from "react";
import {
  Badge,
  Card,
  CardBody,
  CardHeader,
  MetricTile,
  Table,
  Td,
  Th,
} from "@autobacklinker/ui";
import { api, apiClient } from "../lib/api";
import { activityStream, type LiveEvent } from "../lib/activity";
import { useAsync } from "../lib/useAsync";
import { ErrorBlock, LoadingBlock, NothingYet, PageHeader } from "../components/common";
import { formatDate, formatNumber, formatRelative } from "../lib/format";
import { useBackend } from "../lib/backendState";

function LiveFeed() {
  const [events, setEvents] = React.useState<LiveEvent[]>([]);
  const [connected, setConnected] = React.useState(false);

  React.useEffect(() => {
    const unsubscribe = activityStream.subscribe((event) => {
      setConnected(true);
      setEvents((previous) => [event, ...previous].slice(0, 40));
    });
    return unsubscribe;
  }, []);

  return (
    <Card className="min-w-0">
      <CardHeader
        title="Live activity"
        description="Server-sent events from the local backend"
        action={
          <Badge tone={connected ? "success" : "neutral"}>
            {connected ? "Streaming" : "Idle"}
          </Badge>
        }
      />
      <CardBody className="p-0">
        {events.length === 0 ? (
          <NothingYet
            title="No live events yet"
            description="Events appear here as soon as the backend publishes them."
          />
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>When</Th>
                <Th>Type</Th>
                <Th>Message</Th>
                <Th>Level</Th>
              </tr>
            </thead>
            <tbody>
              {events.map((event, index) => (
                <tr key={`${event.id ?? "evt"}-${index}`}>
                  <Td className="whitespace-nowrap text-xs text-content-muted">
                    {formatRelative(event.created_at)}
                  </Td>
                  <Td className="whitespace-nowrap text-xs">
                    {event.event_type ?? "-"}
                  </Td>
                  <Td className="text-xs">{event.message ?? "-"}</Td>
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
                      {event.level ?? "INFO"}
                    </Badge>
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </CardBody>
    </Card>
  );
}

export function OverviewPage() {
  const { data, error, loading, reload } = useAsync(
    () => api.dashboard.metrics(apiClient),
    [],
  );
  const { status } = useBackend();

  if (loading && !data) return <LoadingBlock rows={6} />;
  if (error && !data) return <ErrorBlock message={error} onRetry={reload} />;

  const metrics = data;

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Overview"
        description={`Metrics generated at ${formatDate(metrics?.generated_at)}`}
      />

      {error ? <ErrorBlock message={error} onRetry={reload} /> : null}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
        <MetricTile
          label="Projects"
          value={formatNumber(metrics?.projects)}
          hint={`${formatNumber(metrics?.opportunities)} opportunities`}
        />
        <MetricTile
          label="Queued"
          value={formatNumber(metrics?.queued)}
          hint={`${formatNumber(metrics?.running)} running`}
          tone="info"
        />
        <MetricTile
          label="Published"
          value={formatNumber(metrics?.published)}
          hint={`${formatNumber(metrics?.verified_live)} verified live`}
          tone="accent"
        />
        <MetricTile
          label="Pending manual"
          value={formatNumber(metrics?.pending_manual)}
          hint={`${formatNumber(metrics?.awaiting_retry)} awaiting retry`}
          tone="warning"
        />
        <MetricTile
          label="Failed"
          value={formatNumber(metrics?.failed)}
          hint={`${formatNumber(metrics?.sync_errors)} sync errors`}
          tone="danger"
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader
            title="Opportunities by status"
            description="Straight from /api/v1/dashboard/metrics"
          />
          <CardBody className="p-0">
            {metrics && Object.keys(metrics.by_status ?? {}).length > 0 ? (
              <Table>
                <thead>
                  <tr>
                    <Th>Status</Th>
                    <Th className="text-right">Count</Th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(metrics.by_status).map(([status, count]) => (
                    <tr key={status}>
                      <Td>
                        <Badge tone="neutral">{status.replace(/_/g, " ")}</Badge>
                      </Td>
                      <Td className="text-right text-xs">
                        {formatNumber(count)}
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            ) : (
              <NothingYet
                title="No status breakdown"
                description="The backend did not report any opportunity counts yet."
              />
            )}
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="Local installation" />
          <CardBody>
            <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-2 text-xs">
              <dt className="text-content-muted">Backend</dt>
              <dd className="text-content">
                {status?.healthy
                  ? `Running on ${status.baseUrl}`
                  : (status?.running ?? false)
                    ? "Starting…"
                    : "Stopped"}
              </dd>
              <dt className="text-content-muted">Devices</dt>
              <dd className="text-content">
                {formatNumber(metrics?.connected_devices)} connected ·{" "}
                {formatNumber(metrics?.cloud_workers)} cloud workers
              </dd>
              <dt className="text-content-muted">Local jobs</dt>
              <dd className="text-content">
                {formatNumber(metrics?.running_local_jobs)}
              </dd>
              <dt className="text-content-muted">Data directory</dt>
              <dd className="break-all text-content">
                {status?.dataDir ?? "-"}
              </dd>
            </dl>
          </CardBody>
        </Card>
      </div>

      <LiveFeed />
    </div>
  );
}
