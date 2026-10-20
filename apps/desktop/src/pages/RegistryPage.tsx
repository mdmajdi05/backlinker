import * as React from "react";
import {
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
import { api, apiClient } from "../lib/api";
import { useAsync } from "../lib/useAsync";
import { ErrorBlock, LoadingBlock, NothingYet, PageHeader } from "../components/common";
import { formatNumber, hostOf, truncate } from "../lib/format";
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

  const items = opportunities.data?.items ?? [];

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

      {opportunities.loading && !opportunities.data ? <LoadingBlock /> : null}
      {opportunities.error ? (
        <ErrorBlock message={opportunities.error} onRetry={opportunities.reload} />
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
                  <Th>Backlink</Th>
                  <Th>Adapter</Th>
                </tr>
              </thead>
              <tbody>
                {items.map((item: Opportunity) => (
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
                    <Td>
                      <StatusBadge status={item.backlink_status} />
                    </Td>
                    <Td className="max-w-[160px] truncate text-xs text-content-muted">
                      {item.adapter_id ?? "-"}
                    </Td>
                  </tr>
                ))}
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
    </div>
  );
}
