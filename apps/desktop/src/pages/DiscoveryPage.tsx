import * as React from "react";
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
import { OpportunityCategory } from "@autobacklinker/shared-types";
import { api, apiClient } from "../lib/api";
import { useAsync } from "../lib/useAsync";
import { ErrorBlock, LoadingBlock, NothingYet, PageHeader } from "../components/common";
import { formatDate, formatNumber, titleCase } from "../lib/format";
import { navigate } from "../lib/router";
import { sendNativeNotification } from "../lib/backend";
import type { DiscoveryRun, Opportunity, Project } from "@autobacklinker/shared-types";

const PAGE_SIZE = 20;

const CATEGORIES = Object.values(OpportunityCategory);

function errorText(error: unknown, fallback: string): string {
  if (error && typeof error === "object" && "message" in error) {
    return String((error as { message: unknown }).message);
  }
  return fallback;
}

function splitList(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

export function DiscoveryPage() {
  const toast = useToast();
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
  const [running, setRunning] = React.useState(false);
  const [runError, setRunError] = React.useState<string | null>(null);

  const projects = useAsync(
    () => api.projects.list(apiClient, { page: 1, page_size: 100 }),
    [],
  );
  const providers = useAsync(() => api.discovery.providers(apiClient), []);
  const runs = useAsync(
    () => api.discovery.list(apiClient, { page, page_size: PAGE_SIZE }),
    [page],
  );

  const runOpportunities = useAsync(
    () =>
      selectedRun
        ? api.opportunities.list(apiClient, {
            page: 1,
            page_size: 25,
            project_id: selectedRun.project_id,
          })
        : Promise.resolve(null),
    [selectedRun?.id, selectedRun?.project_id],
  );

  const providerItems = providers.data ?? [];
  const projectItems = projects.data?.items ?? [];
  const runItems = runs.data?.items ?? [];

  const selectedProvider = providerItems.find((item) => item.key === provider);

  // The run does not carry the identifiers of the opportunities it produced -
  // they are the entries of the project that were created while the run was
  // running and that carry the provider of the run.
  const produced: Opportunity[] = React.useMemo(() => {
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

  async function runDiscovery() {
    setRunError(null);
    if (!projectId) {
      setRunError("Select the project this discovery belongs to.");
      return;
    }
    if (!provider) {
      setRunError("Select a discovery provider.");
      return;
    }

    setRunning(true);
    try {
      const result = await api.discovery.run(apiClient, {
        project_id: projectId,
        provider,
        query: query.trim() || undefined,
        keywords: splitList(keywords),
        countries: splitList(countries),
        language: language.trim() || undefined,
        category: (category || undefined) as OpportunityCategory | undefined,
        limit: Number.parseInt(limit, 10) || undefined,
      });
      toast.push(`Discovery run ${result.status.toLowerCase()}`, "success");
      void sendNativeNotification(
        "Auto Backlinker",
        `Discovery run ${result.status.toLowerCase()} (${provider}).`,
      );
      setPage(1);
      runs.reload();
    } catch (err) {
      setRunError(errorText(err, "Could not start the discovery run"));
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Find new websites"
        description="Run provider searches and inspect what they produced."
        actions={
          <Button
            size="sm"
            variant="outline"
            loading={runs.loading}
            onClick={runs.reload}
          >
            Refresh
          </Button>
        }
      />

      <div className="grid gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader
            title="Providers"
            description="Discovery sources known to the local backend"
          />
          <CardBody className="p-0">
            {providers.loading && !providers.data ? (
              <div className="p-4">
                <LoadingBlock rows={4} />
              </div>
            ) : providers.error ? (
              <div className="p-4">
                <ErrorBlock
                  message={providers.error}
                  onRetry={providers.reload}
                />
              </div>
            ) : providerItems.length === 0 ? (
              <NothingYet
                title="No providers registered"
                description="The backend did not report any discovery provider."
              />
            ) : (
              <ul className="divide-y divide-line">
                {providerItems.map((item) => (
                  <li
                    key={item.key}
                    className="flex flex-wrap items-start justify-between gap-2 p-3"
                  >
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium text-content">
                        {item.name}
                      </p>
                      <p className="truncate text-xs text-content-subtle">
                        {item.key}
                      </p>
                      {item.categories.length > 0 ? (
                        <p
                          className="mt-1 text-[11px] text-content-subtle"
                          title={item.categories.map(titleCase).join(", ")}
                        >
                          {item.categories.slice(0, 3).map(titleCase).join(", ")}
                          {item.categories.length > 3
                            ? ` +${item.categories.length - 3} more`
                            : ""}
                        </p>
                      ) : null}
                    </div>
                    <div className="flex shrink-0 flex-col items-end gap-1">
                      <Badge
                        tone={item.requires_credentials ? "warning" : "success"}
                      >
                        {item.requires_credentials
                          ? "Credentials required"
                          : "No credentials"}
                      </Badge>
                      {item.available === false ? (
                        <Badge tone="danger">Unavailable</Badge>
                      ) : (
                        <Badge tone="success">Ready</Badge>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </CardBody>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader
            title="Run discovery"
            description="Start a new provider search on this machine"
          />
          <CardBody>
            {projectItems.length === 0 && !projects.loading ? (
              <div className="mb-3">
                <NothingYet
                  title="No project yet"
                  description="A discovery run always belongs to a project."
                  action={
                    <Button size="sm" onClick={() => navigate("onboarding")}>
                      Set up a project
                    </Button>
                  }
                />
              </div>
            ) : null}

            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Project" required>
                <Select
                  value={projectId}
                  onChange={(event) => setProjectId(event.target.value)}
                >
                  <option value="">Select project…</option>
                  {projectItems.map((project: Project) => (
                    <option key={project.id} value={project.id}>
                      {project.name}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Provider" required>
                <Select
                  value={provider}
                  onChange={(event) => setProvider(event.target.value)}
                >
                  <option value="">Select provider…</option>
                  {providerItems.map((item) => (
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
                <Select
                  value={category}
                  onChange={(event) => setCategory(event.target.value)}
                >
                  <option value="">Any category</option>
                  {CATEGORIES.map((value) => (
                    <option key={value} value={value}>
                      {titleCase(value)}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Result limit" hint="1 - 500">
                <Input
                  type="number"
                  min={1}
                  max={500}
                  value={limit}
                  onChange={(event) => setLimit(event.target.value)}
                />
              </Field>
              {selectedProvider?.requires_credentials ? (
                <div className="rounded-md border border-line bg-surface-sunken p-3 sm:col-span-2">
                  <p className="text-xs text-content-muted">
                    This provider needs an API key. Save it once in API keys &amp; integrations;
                    every discovery run reads the stored key automatically.
                  </p>
                  <Button
                    size="sm"
                    variant="outline"
                    className="mt-2"
                    onClick={() => navigate("integrations")}
                  >
                    Open API keys &amp; integrations
                  </Button>
                </div>
              ) : null}
            </div>

            {selectedProvider?.available === false ? (
              <p className="mt-3 rounded-md border border-warning/30 bg-warning-soft px-3 py-2 text-xs text-warning">
                {selectedProvider.reason ??
                  "This provider is not configured on the local backend."}
              </p>
            ) : null}

            {runError ? (
              <p className="mt-3 rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-xs text-danger">
                {runError}
              </p>
            ) : null}

            <div className="mt-3 flex justify-end">
              <Button
                loading={running}
                disabled={!projectId || !provider}
                onClick={runDiscovery}
              >
                Start discovery
              </Button>
            </div>
          </CardBody>
        </Card>
      </div>

      <Card>
        <CardHeader
          title="Recent runs"
          description="Discovery runs recorded by the local backend"
        />
        <CardBody className="p-0">
          {runs.loading && !runs.data ? (
            <div className="p-4">
              <LoadingBlock rows={5} />
            </div>
          ) : runs.error ? (
            <div className="p-4">
              <ErrorBlock message={runs.error} onRetry={runs.reload} />
            </div>
          ) : runItems.length === 0 ? (
            <NothingYet
              title="No discovery runs yet"
              description="Start a discovery run to populate the registry."
            />
          ) : (
            <>
              <Table>
                <thead>
                  <tr>
                    <Th>Provider</Th>
                    <Th>Query</Th>
                    <Th>Status</Th>
                    <Th className="text-right">Discovered</Th>
                    <Th className="text-right">New</Th>
                    <Th className="text-right">Dupes</Th>
                    <Th className="text-right">Rejected</Th>
                    <Th>Started</Th>
                    <Th />
                  </tr>
                </thead>
                <tbody>
                  {runItems.map((run) => (
                    <tr key={run.id}>
                      <Td>
                        <p className="text-sm font-medium text-content">
                          {run.provider}
                        </p>
                        {run.error ? (
                          <p
                            className="max-w-xs truncate text-xs text-danger"
                            title={run.error}
                          >
                            {run.error}
                          </p>
                        ) : null}
                      </Td>
                      <Td className="max-w-[180px] truncate text-xs text-content-muted">
                        {run.query ?? "-"}
                      </Td>
                      <Td>
                        <StatusBadge status={run.status} />
                      </Td>
                      <Td className="text-right text-xs">
                        {formatNumber(run.discovered_count)}
                      </Td>
                      <Td className="text-right text-xs">
                        {formatNumber(run.new_count)}
                      </Td>
                      <Td className="text-right text-xs">
                        {formatNumber(run.duplicate_count)}
                      </Td>
                      <Td className="text-right text-xs">
                        {formatNumber(run.rejected_count)}
                      </Td>
                      <Td className="whitespace-nowrap text-xs text-content-muted">
                        {formatDate(run.started_at ?? run.created_at)}
                      </Td>
                      <Td className="text-right">
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => setSelectedRun(run)}
                        >
                          Opportunities
                        </Button>
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
              <Pagination
                page={page}
                pages={runs.data?.pages ?? 1}
                total={runs.data?.total ?? 0}
                onPageChange={setPage}
              />
            </>
          )}
        </CardBody>
      </Card>

      {selectedRun ? (
        <Card>
          <CardHeader
            title={`Opportunities from run ${selectedRun.provider}`}
            description={`${formatNumber(selectedRun.discovered_count)} discovered · ${formatNumber(
              selectedRun.new_count,
            )} new · started ${formatDate(
              selectedRun.started_at ?? selectedRun.created_at,
            )}`}
            action={
              <Button
                size="sm"
                variant="outline"
                onClick={() => setSelectedRun(null)}
              >
                Close
              </Button>
            }
          />
          <CardBody className="p-0">
            {runOpportunities.loading && !runOpportunities.data ? (
              <div className="p-4">
                <LoadingBlock rows={4} />
              </div>
            ) : runOpportunities.error ? (
              <div className="p-4">
                <ErrorBlock
                  message={runOpportunities.error}
                  onRetry={runOpportunities.reload}
                />
              </div>
            ) : produced.length === 0 ? (
              <NothingYet
                title="No opportunities stored for this run"
                description="The registry does not contain matching opportunities for this provider and project."
              />
            ) : (
              <Table>
                <thead>
                  <tr>
                    <Th>Name</Th>
                    <Th>Domain</Th>
                    <Th>Category</Th>
                    <Th className="text-right">Score</Th>
                    <Th>Status</Th>
                  </tr>
                </thead>
                <tbody>
                  {produced.map((item) => (
                    <tr key={item.id}>
                      <Td className="max-w-[260px] truncate text-xs">
                        {item.name}
                      </Td>
                      <Td className="text-xs">{item.domain}</Td>
                      <Td>
                        <Badge tone="neutral">{titleCase(item.category)}</Badge>
                      </Td>
                      <Td className="text-right text-xs">
                        {formatNumber(Math.round(item.score))}
                      </Td>
                      <Td>
                        <StatusBadge status={item.status} />
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
          </CardBody>
        </Card>
      ) : null}
    </div>
  );
}
