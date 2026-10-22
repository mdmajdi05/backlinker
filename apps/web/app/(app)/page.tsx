"use client";

import * as React from "react";
import Link from "next/link";
import { api } from "@autobacklinker/api-client";
import type { ActivityEvent, DashboardMetrics } from "@autobacklinker/shared-types";
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  MetricTile,
  Table,
  Td,
  Th,
} from "@autobacklinker/ui";
import { apiClient, errorMessage } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import { formatDateTime, formatNumber, formatRelative, humanize } from "@/lib/format";
import { CATEGORY_LABELS, TASK_STATUS_LABELS } from "@/lib/constants";
import { PageHeader } from "@/components/PageHeader";
import { AsyncSection, CardSkeleton, ErrorPanel, TableSkeleton } from "@/components/States";
import { BarList } from "@/components/BarList";

const LEVEL_TONES: Record<string, "info" | "warning" | "danger" | "success" | "neutral"> = {
  INFO: "info",
  WARNING: "warning",
  ERROR: "danger",
  SUCCESS: "success",
};

/** Normalises an arbitrary SSE payload into an activity row. */
function toActivityEvent(payload: unknown, fallbackIndex: number): ActivityEvent | null {
  if (!payload || typeof payload !== "object") return null;
  const raw = payload as Record<string, unknown>;
  const message =
    typeof raw.message === "string"
      ? raw.message
      : typeof raw.detail === "string"
        ? raw.detail
        : typeof raw.status === "string"
          ? raw.status
          : null;
  if (!message) return null;
  return {
    id: typeof raw.id === "string" ? raw.id : `live-${fallbackIndex}`,
    event_type: typeof raw.event_type === "string" ? raw.event_type : "EVENT",
    level:
      raw.level === "INFO" ||
      raw.level === "WARNING" ||
      raw.level === "ERROR" ||
      raw.level === "SUCCESS"
        ? raw.level
        : "INFO",
    message,
    project_id: typeof raw.project_id === "string" ? raw.project_id : null,
    project_name: typeof raw.project_name === "string" ? raw.project_name : null,
    task_id: typeof raw.task_id === "string" ? raw.task_id : null,
    opportunity_id: typeof raw.opportunity_id === "string" ? raw.opportunity_id : null,
    website: typeof raw.website === "string" ? raw.website : null,
    execution_environment:
      raw.execution_environment === "CLOUD" || raw.execution_environment === "LOCAL"
        ? raw.execution_environment
        : null,
    metadata: null,
    created_at: typeof raw.created_at === "string" ? raw.created_at : new Date().toISOString(),
  };
}

export default function OverviewPage() {
  const metrics = useResource(() => api.dashboard.metrics(apiClient), []);
  const activity = useResource(
    () => api.activity.list(apiClient, { page: 1, page_size: 25 }),
    [],
  );

  const [liveEvents, setLiveEvents] = React.useState<ActivityEvent[]>([]);
  const [streamState, setStreamState] = React.useState<"connecting" | "live" | "offline">(
    "connecting",
  );

  React.useEffect(() => {
    const unsubscribe = api.dashboard.stream(apiClient, undefined, (payload) => {
      const event = toActivityEvent(payload, liveEvents.length);
      if (!event) return;
      setStreamState("live");
      setLiveEvents((prev) => [event, ...prev].slice(0, 50));
    });
    const timer = window.setTimeout(() => {
      setStreamState((prev) => (prev === "connecting" ? "offline" : prev));
    }, 4000);
    return () => {
      unsubscribe();
      window.clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const merged: ActivityEvent[] = React.useMemo(() => {
    const history = activity.data?.items ?? [];
    const seen = new Set<string>();
    const result: ActivityEvent[] = [];
    for (const event of [...liveEvents, ...history]) {
      if (seen.has(event.id)) continue;
      seen.add(event.id);
      result.push(event);
    }
    return result.sort((a, b) => {
      const left = Date.parse(a.created_at) || 0;
      const right = Date.parse(b.created_at) || 0;
      return right - left;
    });
  }, [liveEvents, activity.data]);

  const data: DashboardMetrics | null = metrics.data;
  const tiles = React.useMemo(() => {
    if (!data) return [];
    return [
      { label: "Projects", value: data.projects, href: "/projects" },
      { label: "Discovered", value: data.opportunities, href: "/registry" },
      { label: "Approved", value: data.approved, href: "/registry" },
      { label: "Queued", value: data.queued, href: "/queue" },
      { label: "Running", value: data.running, href: "/automation" },
      { label: "Published", value: data.published, href: "/verification" },
      { label: "Verified live", value: data.verified_live, href: "/verification" },
      { label: "Pending manual", value: data.pending_manual, href: "/automation" },
      { label: "Failed", value: data.failed, href: "/queue" },
      { label: "Awaiting retry", value: data.awaiting_retry, href: "/queue" },
      { label: "Requiring verification", value: data.requiring_verification, href: "/verification" },
      { label: "Connected devices", value: data.connected_devices, href: "/devices" },
    ];
  }, [data]);

  const categories = React.useMemo(() => {
    if (!data) return [];
    const total = data.by_category.reduce((sum, item) => sum + item.count, 0);
    return data.by_category
      .slice()
      .sort((a, b) => b.count - a.count)
      .map((item) => ({
        ...item,
        label: CATEGORY_LABELS[item.category] ?? humanize(item.category),
        share: total > 0 ? item.count / total : 0,
      }));
  }, [data]);

  const statusBars = React.useMemo(() => {
    if (!data) return [];
    return Object.entries(data.by_status ?? {})
      .filter(([, count]) => count > 0)
      .map(([status, count]) => ({
        label: TASK_STATUS_LABELS[status] ?? humanize(status),
        value: count,
      }))
      .sort((a, b) => b.value - a.value);
  }, [data]);

  return (
    <div className="space-y-4">
      <PageHeader
        title="Overview"
        description={
          data ? `Metrics generated at ${formatDateTime(data.generated_at)}` : "Workspace metrics"
        }
        actions={
          <Button variant="outline" size="sm" onClick={metrics.reload} loading={metrics.refreshing}>
            Refresh
          </Button>
        }
      />

      {metrics.error && !data ? (
        <ErrorPanel error={metrics.error} onRetry={metrics.reload} title="Could not load dashboard metrics" />
      ) : null}

      <AsyncSection
        loading={metrics.loading}
        error={metrics.error}
        data={data}
        onRetry={metrics.reload}
        skeleton={<CardSkeleton count={6} />}
      >
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {tiles.map((tile) => (
            <Link key={tile.label} href={tile.href} className="block">
              <MetricTile label={tile.label} value={formatNumber(tile.value)} />
            </Link>
          ))}
        </div>
      </AsyncSection>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader
            title="Opportunities by category"
            description="Real counts reported by the backend"
            action={
              <Link href="/registry" className="text-xs font-medium text-accent hover:underline">
                Open Opportunities
              </Link>
            }
          />
          <CardBody className="p-0">
            {categories.length === 0 ? (
              <p className="px-4 py-6 text-center text-xs text-content-subtle">
                No category breakdown available yet.
              </p>
            ) : (
              <Table>
                <thead>
                  <tr>
                    <Th>Category</Th>
                    <Th className="w-40">Share</Th>
                    <Th className="w-20 text-right">Count</Th>
                  </tr>
                </thead>
                <tbody>
                  {categories.map((item) => (
                    <tr key={item.category}>
                      <Td>{item.label}</Td>
                      <Td>
                        <div className="h-2 w-full overflow-hidden rounded-full bg-surface-sunken">
                          <div
                            className="h-full rounded-full bg-accent"
                            style={{ width: `${Math.round(item.share * 100)}%` }}
                          />
                        </div>
                      </Td>
                      <Td className="text-right tabular-nums">{formatNumber(item.count)}</Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="Task status breakdown" description="Counts by task status" />
          <CardBody>
            <BarList items={statusBars} emptyLabel="No task statuses reported." />
          </CardBody>
        </Card>
      </div>

      <Card>
        <CardHeader
          title="Live activity"
          description="Merged live stream and recent history"
          action={
            <Badge
              tone={
                streamState === "live"
                  ? "success"
                  : streamState === "offline"
                    ? "warning"
                    : "neutral"
              }
            >
              {streamState === "live"
                ? "Stream live"
                : streamState === "offline"
                  ? "Stream offline"
                  : "Connecting"}
            </Badge>
          }
        />
        <CardBody className="p-0">
          <AsyncSection
            loading={activity.loading}
            error={activity.error}
            data={activity.data}
            onRetry={activity.reload}
            isEmpty={merged.length === 0}
            emptyTitle="No activity recorded yet"
            emptyDescription="Activity appears here as discovery, submission and verification events happen."
            skeleton={<TableSkeleton rows={8} columns={5} />}
          >
            <Table>
              <thead>
                <tr>
                  <Th className="w-44">When</Th>
                  <Th className="w-40">Project</Th>
                  <Th className="w-44">Website</Th>
                  <Th className="w-36">Status</Th>
                  <Th>Message</Th>
                </tr>
              </thead>
              <tbody>
                {merged.map((event) => (
                  <tr key={event.id}>
                    <Td className="whitespace-nowrap text-xs text-content-muted">
                      <span title={formatDateTime(event.created_at)}>
                        {formatRelative(event.created_at)}
                      </span>
                    </Td>
                    <Td className="text-xs">{event.project_name ?? event.project_id ?? "—"}</Td>
                    <Td className="truncate text-xs">{event.website ?? "—"}</Td>
                    <Td>
                      <Badge tone={LEVEL_TONES[event.level] ?? "neutral"}>
                        {humanize(event.event_type)}
                      </Badge>
                    </Td>
                    <Td className="text-xs">{event.message}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </AsyncSection>
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title="Where do I do what?"
          description="One page per job - so nothing is done twice"
        />
        <CardBody>
          <dl className="grid gap-x-6 gap-y-3 text-xs sm:grid-cols-2">
            <div>
              <dt className="font-medium text-content">Find new websites</dt>
              <dd className="text-content-muted">
                <Link className="underline" href="/discovery">Discovery</Link> runs a provider search
                - the result is reviewed in{" "}
                <Link className="underline" href="/registry">Opportunities</Link>.
              </dd>
            </div>
            <div>
              <dt className="font-medium text-content">Review and approve</dt>
              <dd className="text-content-muted">
                <Link className="underline" href="/registry">Opportunities</Link> is the only place
                where a website is approved, excluded or queued for a project.
              </dd>
            </div>
            <div>
              <dt className="font-medium text-content">Keep the site list</dt>
              <dd className="text-content-muted">
                <Link className="underline" href="/websites">Websites</Link> is the central list -
                add a site by hand or import a spreadsheet there.
              </dd>
            </div>
            <div>
              <dt className="font-medium text-content">Run a project</dt>
              <dd className="text-content-muted">
                Open a project: its websites, its execution rules, the auto pilot and its report
                live on the project page.
              </dd>
            </div>
            <div>
              <dt className="font-medium text-content">Change your company details</dt>
              <dd className="text-content-muted">
                <Link className="underline" href="/settings">Settings → Business profiles</Link> -
                every project submits with the same profile.
              </dd>
            </div>
            <div>
              <dt className="font-medium text-content">Undo a deletion</dt>
              <dd className="text-content-muted">
                Everything you delete waits in the{" "}
                <Link className="underline" href="/recycle-bin">Recycle bin</Link> - restore it
                there or delete it forever.
              </dd>
            </div>
          </dl>
        </CardBody>
      </Card>

      {metrics.error && data ? (
        <p className="text-xs text-danger">{errorMessage(metrics.error)}</p>
      ) : null}
    </div>
  );
}
