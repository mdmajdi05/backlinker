import * as React from "react";
import {
  Alert,
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  Checkbox,
  Pagination,
  Select,
  StatusBadge,
  Table,
  Td,
  Th,
  useToast,
} from "@autobacklinker/ui";
import { api, apiClient, type AutoPilotState } from "../lib/api";
import { useAsync } from "../lib/useAsync";
import { ErrorBlock, LoadingBlock, NothingYet, PageHeader } from "../components/common";
import { OpportunityDrawer } from "../components/OpportunityDrawer";
import { useSubmissionDetailsStates } from "../components/SubmissionDetailsPanel";
import { formatNumber, hostOf, truncate } from "../lib/format";
import { navigate } from "../lib/router";
import type { Opportunity, Project } from "@autobacklinker/shared-types";

const PAGE_SIZE = 25;

const STATUS_FILTERS = [
  "",
  "NEEDS_REVIEW",
  "APPROVED",
  "QUEUED",
  "IN_PROGRESS",
  "COMPLETED",
  "FAILED",
  "REJECTED",
  "EXCLUDED",
];

export function RegistryPage() {
  const toast = useToast();
  const [page, setPage] = React.useState(1);
  const [status, setStatus] = React.useState("");
  const [projectId, setProjectId] = React.useState("");
  const [selected, setSelected] = React.useState<string[]>([]);
  const [busy, setBusy] = React.useState(false);
  const [detailsFor, setDetailsFor] = React.useState<Opportunity | null>(null);
  const [autoPilot, setAutoPilot] = React.useState<AutoPilotState | null>(null);

  const projects = useAsync(
    () => api.projects.list(apiClient, { page: 1, page_size: 100 }),
    [],
  );

  const opportunities = useAsync(
    () =>
      api.opportunities.list(apiClient, {
        page,
        page_size: PAGE_SIZE,
        status: status || undefined,
        project_id: projectId || undefined,
      }),
    [page, status, projectId],
  );

  const items = React.useMemo(
    () => opportunities.data?.items ?? [],
    [opportunities.data],
  );

  // The state of the details of every row - the backend answers per
  // opportunity.
  const detailStates = useSubmissionDetailsStates(items.map((item) => item.id));

  // The auto pilot of the selected project explains what an approval does.
  React.useEffect(() => {
    if (!projectId) {
      setAutoPilot(null);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const result = await api.autoPilot.get(apiClient, projectId);
        if (!cancelled) setAutoPilot(result);
      } catch {
        // The backend may not know the endpoint yet - the hint is simply
        // not shown then.
        if (!cancelled) setAutoPilot(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  React.useEffect(() => {
    setSelected([]);
  }, [page, status, projectId]);

  function toggle(id: string) {
    setSelected((previous) =>
      previous.includes(id)
        ? previous.filter((item) => item !== id)
        : [...previous, id],
    );
  }

  async function runBulk(action: "approve" | "reject" | "queue" | "exclude") {
    if (selected.length === 0) return;
    setBusy(true);
    try {
      const result = await api.opportunities.bulk(apiClient, {
        opportunity_ids: selected,
        action,
        project_id: projectId || undefined,
      });
      toast.push(`${result.affected} opportunities updated`, "success");
      setSelected([]);
      opportunities.reload();
    } catch (err) {
      toast.push(
        err && typeof err === "object" && "message" in err
          ? String((err as { message: unknown }).message)
          : "Bulk action failed",
        "error",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Registry"
        description="Every discovered opportunity with its review and execution state."
      />

      <Card>
        <CardHeader
          title="Filters"
          action={
            <div className="flex items-center gap-2">
              <Button
                size="sm"
                variant="outline"
                disabled={selected.length === 0 || busy}
                onClick={() => runBulk("approve")}
              >
                Approve
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={selected.length === 0 || busy}
                onClick={() => runBulk("queue")}
              >
                Queue
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={selected.length === 0 || busy}
                onClick={() => runBulk("exclude")}
              >
                Exclude
              </Button>
              <Button
                size="sm"
                variant="danger"
                disabled={selected.length === 0 || busy}
                onClick={() => runBulk("reject")}
              >
                Reject
              </Button>
            </div>
          }
        />
        <CardBody>
          <div className="flex flex-wrap items-end gap-3">
            <div className="w-48">
              <label className="mb-1 block text-xs font-medium text-content-muted">
                Status
              </label>
              <Select
                value={status}
                onChange={(event) => {
                  setStatus(event.target.value);
                  setPage(1);
                }}
              >
                {STATUS_FILTERS.map((value) => (
                  <option key={value} value={value}>
                    {value ? value.replace(/_/g, " ") : "All statuses"}
                  </option>
                ))}
              </Select>
            </div>
            <div className="w-64">
              <label className="mb-1 block text-xs font-medium text-content-muted">
                Project
              </label>
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
            </div>
            <p className="pb-2 text-xs text-content-subtle">
              {selected.length} selected of {formatNumber(opportunities.data?.total)}
            </p>
          </div>
        </CardBody>
      </Card>

      {autoPilot ? (
        <Alert
          tone={autoPilot.enabled ? "info" : "neutral"}
          title={
            autoPilot.enabled
              ? "The auto pilot is on for this project"
              : "The auto pilot is off for this project"
          }
          action={
            <Button
              size="sm"
              variant="outline"
              onClick={() => navigate(`projects/${projectId}`)}
            >
              Open the project
            </Button>
          }
        >
          {autoPilot.enabled ? (
            <p>
              Approving an opportunity queues the submission automatically. A
              task that waits for a missing detail stays in the queue - it does
              not fail.
            </p>
          ) : (
            <p>
              Approving an opportunity only marks it as approved. Switch the
              auto pilot on in the project to submit it automatically.
            </p>
          )}
        </Alert>
      ) : null}

      {opportunities.loading && !opportunities.data ? <LoadingBlock /> : null}
      {opportunities.error ? (
        <ErrorBlock message={opportunities.error} onRetry={opportunities.reload} />
      ) : null}

      {detailStates.supported === false ? (
        <Alert
          tone="warning"
          title="The backend does not report the submission details yet"
        >
          The state of the details is read by the backend. An older local
          backend can not show it - update the backend and reload this view.
        </Alert>
      ) : null}

      {!opportunities.loading && items.length === 0 && !opportunities.error ? (
        <NothingYet
          title="No opportunities"
          description="Nothing matches the current filter. Run a discovery to populate the registry."
        />
      ) : null}

      {items.length > 0 ? (
        <Card>
          <CardBody className="p-0">
            <Table>
              <thead>
                <tr>
                  <Th className="w-8">
                    <Checkbox
                      aria-label="Select all"
                      checked={
                        selected.length > 0 && selected.length === items.length
                      }
                      onChange={(event) =>
                        setSelected(
                          event.target.checked
                            ? items.map((item) => item.id)
                            : [],
                        )
                      }
                    />
                  </Th>
                  <Th>Opportunity</Th>
                  <Th>Category</Th>
                  <Th>Method</Th>
                  <Th className="text-right">Score</Th>
                  <Th>Status</Th>
                  <Th>Details</Th>
                  <Th>Backlink</Th>
                  <Th>Adapter</Th>
                  <Th />
                </tr>
              </thead>
              <tbody>
                {items.map((item: Opportunity) => {
                  const details = detailStates.states[item.id];
                  return (
                    <tr key={item.id}>
                      <Td>
                        <Checkbox
                          aria-label={`Select ${item.name}`}
                          checked={selected.includes(item.id)}
                          onChange={() => toggle(item.id)}
                        />
                      </Td>
                      <Td>
                        <div className="min-w-0">
                          <p className="truncate text-sm text-content">
                            {item.name}
                          </p>
                          <p className="truncate text-xs text-content-subtle">
                            {hostOf(item.opportunity_url)}
                          </p>
                        </div>
                      </Td>
                      <Td className="whitespace-nowrap text-xs">
                        {truncate(item.category.replace(/_/g, " "), 26)}
                      </Td>
                      <Td className="whitespace-nowrap text-xs">
                        <Badge tone="neutral">
                          {item.submission_method.replace(/_/g, " ")}
                        </Badge>
                      </Td>
                      <Td className="text-right text-xs">
                        {formatNumber(Math.round(item.score))}
                      </Td>
                      <Td>
                        <StatusBadge status={item.status} />
                      </Td>
                      <Td className="whitespace-nowrap">
                        {details ? (
                          details.complete ? (
                            <Badge tone="success">Complete</Badge>
                          ) : details.missing.length > 0 ? (
                            <Badge tone="warning">
                              {details.missing.length} missing
                            </Badge>
                          ) : (
                            <Badge tone="neutral">Unknown</Badge>
                          )
                        ) : (
                          <span className="text-xs text-content-subtle">-</span>
                        )}
                      </Td>
                      <Td>
                        <StatusBadge status={item.backlink_status} />
                      </Td>
                      <Td className="max-w-[160px] truncate text-xs text-content-muted">
                        {item.adapter_id ?? "-"}
                      </Td>
                      <Td className="whitespace-nowrap text-right">
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => setDetailsFor(item)}
                        >
                          Details
                        </Button>
                      </Td>
                    </tr>
                  );
                })}
              </tbody>
            </Table>
            <Pagination
              page={page}
              pages={opportunities.data?.pages ?? 1}
              total={opportunities.data?.total ?? 0}
              onPageChange={setPage}
            />
          </CardBody>
        </Card>
      ) : null}

      {detailsFor ? (
        <OpportunityDrawer
          opportunity={detailsFor}
          onClose={() => setDetailsFor(null)}
          onChanged={detailStates.reload}
        />
      ) : null}
    </div>
  );
}
