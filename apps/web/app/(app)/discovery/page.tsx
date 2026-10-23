"use client";

import * as React from "react";
import Link from "next/link";
import { api } from "@autobacklinker/api-client";
import type { DiscoveryRun, Opportunity, OpportunityCategory } from "@autobacklinker/shared-types";
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  Field,
  Input,
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
import { ALL_OPPORTUNITY_CATEGORIES, CATEGORY_LABELS } from "@/lib/constants";
import { PageHeader } from "@/components/PageHeader";
import { AsyncSection, TableSkeleton } from "@/components/States";

const PAGE_SIZE = 20;

export default function DiscoveryPage() {
  const toast = useToast();
  const action = useAction();

  const [page, setPage] = React.useState(1);
  const [selectedRun, setSelectedRun] = React.useState<DiscoveryRun | null>(null);

  const [projectId, setProjectId] = React.useState("");
  const [provider, setProvider] = React.useState("");
  const [query, setQuery] = React.useState("");
  const [keywords, setKeywords] = React.useState("");
  const [countries, setCountries] = React.useState("");
  const [language, setLanguage] = React.useState("");
  const [category, setCategory] = React.useState("");
  const [limit, setLimit] = React.useState("50");

  const projects = useResource(() => api.projects.list(apiClient, { page: 1, page_size: 100 }), []);
  const providers = useResource(() => api.discovery.providers(apiClient), []);
  const runs = useResource(
    () => api.discovery.list(apiClient, { page, page_size: PAGE_SIZE }),
    [page],
  );

  const runOpportunities = useResource(
    () =>
      selectedRun
        ? api.opportunities.list(apiClient, {
            page: 1,
            page_size: 25,
            project_id: selectedRun.project_id,
          })
        : Promise.resolve<{ items: Opportunity[]; total: number; page: number; page_size: number; pages: number }>(
            { items: [], total: 0, page: 1, page_size: 25, pages: 0 },
          ),
    [selectedRun?.id, selectedRun?.project_id],
    { enabled: Boolean(selectedRun) },
  );

  const produced = React.useMemo(() => {
    if (!selectedRun || !runOpportunities.data) return [];
    const startedAt = selectedRun.started_at
      ? Date.parse(selectedRun.started_at)
      : Number.NEGATIVE_INFINITY;
    return runOpportunities.data.items.filter((item) => {
      const matchesProvider =
        !selectedRun.provider ||
        item.discovery_provider === selectedRun.provider ||
        item.discovery_source === selectedRun.provider;
      const createdAt = Date.parse(item.created_at);
      return matchesProvider && createdAt >= startedAt;
    });
  }, [selectedRun, runOpportunities.data]);

  const runDiscovery = async () => {
    if (!projectId) {
      toast.push("Select the project this discovery belongs to", "error");
      return;
    }
    if (!provider) {
      toast.push("Select a discovery provider", "error");
      return;
    }
    const outcome = await action.run(() =>
      api.discovery.run(apiClient, {
        project_id: projectId,
        provider,
        query: query.trim() || undefined,
        keywords: keywords
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean),
        countries: countries
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean),
        language: language.trim() || undefined,
        category: (category || undefined) as OpportunityCategory | undefined,
        limit: Number.parseInt(limit, 10) || undefined,
      }),
    );
    if (outcome.ok && outcome.data) {
      toast.push(`Discovery run ${outcome.data.status.toLowerCase()}`, "success");
      runs.reload();
    }
  };

  return (
    <div className="space-y-4">
      <PageHeader
        title="Find new websites"
        description="Find new websites with a provider search, then review them under Review websites."
        actions={
          <div className="flex items-center gap-2">
            <Link href="/registry">
              <Button variant="primary" size="sm">
                Review websites
              </Button>
            </Link>
            <Button variant="outline" size="sm" onClick={runs.reload} loading={runs.refreshing}>
              Refresh
            </Button>
          </div>
        }
      />

      <div className="grid gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader
            title="Providers"
            description="Discovery sources known to the backend"
          />
          <CardBody className="p-0">
            <AsyncSection
              loading={providers.loading}
              error={providers.error}
              data={providers.data}
              onRetry={providers.reload}
              isEmpty={(providers.data ?? []).length === 0}
              emptyTitle="No providers registered"
              emptyDescription="The backend did not report any discovery provider."
              skeleton={<TableSkeleton rows={4} columns={3} />}
            >
              <ul className="divide-y divide-line">
                {(providers.data ?? []).map((item) => (
                  <li key={item.key} className="flex flex-wrap items-start justify-between gap-2 p-3">
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-content">{item.name}</p>
                      <p className="text-xs text-content-muted">{item.key}</p>
                      {item.categories.length > 0 ? (
                        <p className="mt-1 text-[11px] text-content-subtle">
                          {item.categories
                            .map((cat) => CATEGORY_LABELS[cat] ?? cat)
                            .join(", ")}
                        </p>
                      ) : null}
                    </div>
                    <Badge tone={item.requires_credentials ? "warning" : "success"}>
                      {item.requires_credentials ? "Credentials required" : "No credentials"}
                    </Badge>
                  </li>
                ))}
              </ul>
            </AsyncSection>
          </CardBody>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader title="Run discovery" description="Start a new provider search" />
          <CardBody>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Project" required>
                <Select value={projectId} onChange={(event) => setProjectId(event.target.value)}>
                  <option value="">Select project…</option>
                  {(projects.data?.items ?? []).map((project) => (
                    <option key={project.id} value={project.id}>
                      {project.name}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Provider" required>
                <Select value={provider} onChange={(event) => setProvider(event.target.value)}>
                  <option value="">Select provider…</option>
                  {(providers.data ?? []).map((item) => (
                    <option key={item.key} value={item.key}>
                      {item.name}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Query">
                <Input
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="directory listing"
                />
              </Field>
              <Field label="Keywords" hint="Comma separated">
                <Input
                  value={keywords}
                  onChange={(event) => setKeywords(event.target.value)}
                  placeholder="saas, directory, listing"
                />
              </Field>
              <Field label="Countries" hint="Comma separated ISO codes">
                <Input
                  value={countries}
                  onChange={(event) => setCountries(event.target.value)}
                  placeholder="US, DE"
                />
              </Field>
              <Field label="Language">
                <Input
                  value={language}
                  onChange={(event) => setLanguage(event.target.value)}
                  placeholder="en"
                />
              </Field>
              <Field label="Category">
                <Select value={category} onChange={(event) => setCategory(event.target.value)}>
                  <option value="">Any category</option>
                  {ALL_OPPORTUNITY_CATEGORIES.map((value) => (
                    <option key={value} value={value}>
                      {CATEGORY_LABELS[value] ?? value}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Result limit">
                <Input
                  type="number"
                  min={1}
                  value={limit}
                  onChange={(event) => setLimit(event.target.value)}
                />
              </Field>
            </div>

            {action.error ? (
              <p className="mt-3 rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-xs text-danger">
                {errorMessage(action.error)}
              </p>
            ) : null}

            <div className="mt-3 flex justify-end">
              <Button onClick={runDiscovery} loading={action.pending}>
                Start discovery
              </Button>
            </div>
          </CardBody>
        </Card>
      </div>

      <Card>
        <CardHeader title="Recent runs" description="Discovery runs recorded by the backend" />
        <CardBody className="p-0">
          <AsyncSection
            loading={runs.loading}
            error={runs.error}
            data={runs.data}
            onRetry={runs.reload}
            isEmpty={(runs.data?.items ?? []).length === 0}
            emptyTitle="No discovery runs yet"
            emptyDescription="Start a discovery run to populate the registry."
            skeleton={<TableSkeleton rows={6} columns={7} />}
          >
            <Table>
              <thead>
                <tr>
                  <Th>Provider</Th>
                  <Th className="w-40">Query</Th>
                  <Th className="w-32">Status</Th>
                  <Th className="w-24 text-right">Discovered</Th>
                  <Th className="w-20 text-right">New</Th>
                  <Th className="w-20 text-right">Dupes</Th>
                  <Th className="w-24 text-right">Rejected</Th>
                  <Th className="w-40">Started</Th>
                  <Th className="w-28">Inspect</Th>
                </tr>
              </thead>
              <tbody>
                {(runs.data?.items ?? []).map((run) => (
                  <tr key={run.id}>
                    <Td>
                      <p className="font-medium text-content">{run.provider}</p>
                      {run.error ? (
                        <p className="max-w-xs truncate text-xs text-danger" title={run.error}>
                          {run.error}
                        </p>
                      ) : null}
                    </Td>
                    <Td className="text-xs text-content-muted">{run.query ?? "—"}</Td>
                    <Td>
                      <StatusBadge status={run.status} />
                    </Td>
                    <Td className="text-right tabular-nums">{formatNumber(run.discovered_count)}</Td>
                    <Td className="text-right tabular-nums">{formatNumber(run.new_count)}</Td>
                    <Td className="text-right tabular-nums">{formatNumber(run.duplicate_count)}</Td>
                    <Td className="text-right tabular-nums">{formatNumber(run.rejected_count)}</Td>
                    <Td className="text-xs text-content-muted">
                      {formatDateTime(run.started_at ?? run.created_at)}
                    </Td>
                    <Td>
                      <Button size="sm" variant="ghost" onClick={() => setSelectedRun(run)}>
                        Results
                      </Button>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
            {runs.data ? (
              <Pagination
                page={runs.data.page}
                pages={runs.data.pages}
                total={runs.data.total}
                onPageChange={setPage}
              />
            ) : null}
          </AsyncSection>
        </CardBody>
      </Card>

      {selectedRun ? (
        <Card>
          <CardHeader
            title={`Websites found by ${selectedRun.provider}`}
            description={`${selectedRun.discovered_count} discovered · ${selectedRun.new_count} new · started ${formatDateTime(
              selectedRun.started_at ?? selectedRun.created_at,
            )}`}
            action={
              <Button variant="outline" size="sm" onClick={() => setSelectedRun(null)}>
                Close
              </Button>
            }
          />
          <CardBody className="p-0">
            <AsyncSection
              loading={runOpportunities.loading}
              error={runOpportunities.error}
              data={runOpportunities.data}
              onRetry={runOpportunities.reload}
              isEmpty={produced.length === 0}
              emptyTitle="No opportunities stored for this run"
              emptyDescription="The registry does not contain matching opportunities for this provider and project."
              skeleton={<TableSkeleton rows={5} columns={5} />}
            >
              <Table>
                <thead>
                  <tr>
                    <Th>Name</Th>
                    <Th>Domain</Th>
                    <Th>Category</Th>
                    <Th className="w-20 text-right">Score</Th>
                    <Th className="w-32">Status</Th>
                  </tr>
                </thead>
                <tbody>
                  {produced.map((item) => (
                    <tr key={item.id}>
                      <Td>{item.name}</Td>
                      <Td className="text-xs">{item.domain}</Td>
                      <Td>
                        <Badge tone="neutral">
                          {CATEGORY_LABELS[item.category] ?? item.category}
                        </Badge>
                      </Td>
                      <Td className="text-right tabular-nums">{item.score}</Td>
                      <Td>
                        <StatusBadge status={item.status} />
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </AsyncSection>
          </CardBody>
        </Card>
      ) : null}
    </div>
  );
}
