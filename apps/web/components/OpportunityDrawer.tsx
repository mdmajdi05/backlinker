"use client";

import * as React from "react";
import { api } from "@autobacklinker/api-client";
import { OpportunityStatus, type Opportunity } from "@autobacklinker/shared-types";
import {
  Alert,
  Badge,
  Button,
  Dialog,
  Drawer,
  Field,
  Input,
  KeyValue,
  Select,
  Skeleton,
  StatusBadge,
  Tabs,
  Tooltip,
} from "@autobacklinker/ui";
import { apiClient, errorMessage } from "@/lib/api";
import { useAction, useResource } from "@/lib/hooks";
import { useToast } from "@autobacklinker/ui";
import { formatDateTime, formatDecimal, humanize } from "@/lib/format";
import {
  CATEGORY_LABELS,
  SCORE_COMPONENT_LABELS,
  SUBMISSION_METHOD_LABELS,
  VERIFICATION_STATUS_LABELS,
} from "@/lib/constants";
import { DetailsStateBadge, SubmissionDetailsPanel } from "@/components/SubmissionDetailsPanel";
import { ErrorPanel } from "@/components/States";
import { loadDetailsGap, type DetailsGap, type GapField } from "@/lib/details-gap";

export type OpportunityDrawerTab = "details" | "gap" | "overview";

/** The report before the backend answered. */
const EMPTY_GAP: DetailsGap = {
  required: [],
  filled: [],
  missing: [],
  derivable: [],
  notDerivable: [],
  source: "none",
};

export function OpportunityDrawer({
  opportunity,
  open,
  onClose,
  onChanged,
  initialTab = "details",
}: {
  opportunity: Opportunity | null;
  open: boolean;
  onClose: () => void;
  onChanged?: () => void;
  /** The tab that is shown when the drawer opens. */
  initialTab?: OpportunityDrawerTab;
}) {
  const toast = useToast();
  const action = useAction();
  const [projectId, setProjectId] = React.useState("");
  const [excludeOpen, setExcludeOpen] = React.useState(false);
  const [excludeReason, setExcludeReason] = React.useState("");
  const [tab, setTab] = React.useState<OpportunityDrawerTab>(initialTab);

  React.useEffect(() => {
    if (open) setTab(initialTab);
  }, [open, initialTab]);

  const projects = useResource(() => api.projects.list(apiClient, { page: 1, page_size: 100 }), []);

  /* The gap report answers what this site asks for and what the business
   * profile of the project can supply. */
  const gapReport = useResource(
    async () => {
      if (!opportunity) throw new Error("No opportunity selected");
      return loadDetailsGap(apiClient, opportunity.id, opportunity.project_id);
    },
    [opportunity?.id, tab],
    { enabled: Boolean(opportunity) && tab === "gap" },
  );

  const gap = gapReport.data?.gap ?? EMPTY_GAP;

  /** Fills the empty fields the business profile can supply. */
  const generateGap = async () => {
    if (!opportunity) return;
    const outcome = await action.run(() =>
      api.submissionDetails.generate(apiClient, opportunity.id),
    );
    if (outcome.ok && outcome.data) {
      const generated = outcome.data.generated.length;
      toast.push(
        generated > 0
          ? `The backend filled ${generated} field(s) from the business profile`
          : "The backend did not find anything to derive from the business profile",
        generated > 0 ? "success" : "info",
      );
      gapReport.reload();
      onChanged?.();
    }
  };

  const updateStatus = async (status: OpportunityStatus, message: string) => {
    if (!opportunity) return;
    const outcome = await action.run(() =>
      api.opportunities.update(apiClient, opportunity.id, { status }),
    );
    if (outcome.ok) {
      toast.push(message, "success");
      onChanged?.();
    }
  };

  const addToQueue = async () => {
    if (!opportunity) return;
    const outcome = await action.run(() =>
      api.queue.create(apiClient, {
        opportunity_ids: [opportunity.id],
        project_ids: projectId ? [projectId] : undefined,
      }),
    );
    if (outcome.ok && outcome.data) {
      toast.push(`Queued ${outcome.data.created} task(s)`, "success");
      onChanged?.();
    }
  };

  const retry = async () => {
    if (!opportunity) return;
    if (opportunity.task_id) {
      const outcome = await action.run(() =>
        api.tasks.retry(apiClient, opportunity.task_id as string),
      );
      if (outcome.ok) {
        toast.push("Task retried", "success");
        onChanged?.();
      }
      return;
    }
    const outcome = await action.run(() =>
      api.queue.create(apiClient, {
        opportunity_ids: [opportunity.id],
        project_ids: projectId ? [projectId] : undefined,
      }),
    );
    if (outcome.ok) {
      toast.push("Opportunity re-queued", "success");
      onChanged?.();
    }
  };

  const excludeDomain = async () => {
    if (!opportunity?.domain) return;
    const outcome = await action.run(() =>
      api.opportunities.excludeDomain(apiClient, opportunity.domain as string, {
        reason: excludeReason.trim() || undefined,
      }),
    );
    if (outcome.ok) {
      toast.push(`Domain ${opportunity.domain} excluded`, "success");
      setExcludeOpen(false);
      setExcludeReason("");
      onChanged?.();
    }
  };

  const breakdown = opportunity?.score_breakdown ?? null;

  return (
    <Drawer
      open={open && Boolean(opportunity)}
      onClose={onClose}
      title={opportunity?.name ?? "Opportunity"}
      width="lg"
      footer={
        opportunity ? (
          <>
            <Button
              variant="outline"
              size="sm"
              onClick={() => updateStatus(OpportunityStatus.REJECTED, "Opportunity rejected")}
              loading={action.pending}
            >
              Reject
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => updateStatus(OpportunityStatus.APPROVED, "Opportunity approved")}
              loading={action.pending}
            >
              Approve
            </Button>
            <Tooltip label="Retries the linked task, or creates a new queue task when none exists">
              <Button variant="outline" size="sm" onClick={retry} loading={action.pending}>
                Retry
              </Button>
            </Tooltip>
            <Tooltip label="Excludes every opportunity of this domain from discovery">
              <Button
                variant="outline"
                size="sm"
                disabled={!opportunity.domain}
                onClick={() => setExcludeOpen(true)}
              >
                Exclude domain
              </Button>
            </Tooltip>
            <Button size="sm" onClick={addToQueue} loading={action.pending}>
              Add to queue
            </Button>
          </>
        ) : null
      }
    >
      {opportunity ? (
        <div className="space-y-4">
          {action.error ? (
            <Alert tone="danger" title="Action failed">
              {errorMessage(action.error)}
            </Alert>
          ) : null}

          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={opportunity.status} />
            <Badge tone="neutral">
              {CATEGORY_LABELS[opportunity.category] ?? humanize(opportunity.category)}
            </Badge>
            <Badge tone="info">Score {formatDecimal(opportunity.score, 1)}</Badge>
            <Badge tone="neutral">
              Backlink{" "}
              {VERIFICATION_STATUS_LABELS[opportunity.backlink_status] ??
                humanize(opportunity.backlink_status)}
            </Badge>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <a
              href={opportunity.opportunity_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex h-9 items-center rounded-md border border-line-strong bg-surface px-3.5 text-sm font-medium text-content transition-colors hover:bg-surface-raised"
            >
              Open opportunity ↗
            </a>
            <Tooltip label="Copy the opportunity URL to the clipboard">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  void navigator.clipboard?.writeText(opportunity.opportunity_url);
                  toast.push("URL copied", "info");
                }}
              >
                Copy URL
              </Button>
            </Tooltip>
          </div>

          <Tabs
            tabs={[
              { id: "details", label: "Submission details" },
              { id: "gap", label: "Gap report" },
              { id: "overview", label: "Overview" },
            ]}
            active={tab}
            onChange={(id) => setTab(id as OpportunityDrawerTab)}
          />

          {tab === "details" ? (
            <SubmissionDetailsPanel opportunityId={opportunity.id} onChanged={onChanged} />
          ) : tab === "gap" ? (
            <div className="space-y-4">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                  <h3 className="text-sm font-semibold text-content">Gap report</h3>
                  <p className="text-xs text-content-muted">
                    What this site asks for, what your business profile can supply and what
                    only you can fill in.
                  </p>
                </div>
                <Button
                  size="sm"
                  onClick={generateGap}
                  loading={action.pending}
                  disabled={gap.derivable.length === 0}
                  title={
                    gap.derivable.length === 0
                      ? "There is no missing value the business profile could supply"
                      : "Fill the empty fields from the business profile"
                  }
                >
                  Generate the derivable ones
                </Button>
              </div>

              {gapReport.loading && !gapReport.data ? (
                <div className="space-y-2" aria-busy="true" aria-live="polite">
                  <span className="sr-only">Loading the gap report…</span>
                  <Skeleton className="h-4 w-48" />
                  <Skeleton className="h-20 w-full" />
                </div>
              ) : gapReport.error ? (
                <ErrorPanel
                  error={gapReport.error}
                  onRetry={gapReport.reload}
                  title="Could not load the gap report"
                />
              ) : (
                <>
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone="neutral">{gap.required.length} required</Badge>
                    <Badge tone={gap.missing.length > 0 ? "warning" : "success"}>
                      {gap.missing.length} missing
                    </Badge>
                    <Badge tone="info">{gap.derivable.length} derivable</Badge>
                    <Badge tone={gap.notDerivable.length > 0 ? "danger" : "neutral"}>
                      {gap.notDerivable.length} not derivable
                    </Badge>
                    {gap.source === "none" ? (
                      <Tooltip label="The project of this opportunity has no business profile - nothing can be derived from it.">
                        <span>
                          <Badge tone="neutral">no business profile</Badge>
                        </span>
                      </Tooltip>
                    ) : null}
                  </div>

                  {gap.required.length === 0 ? (
                    <Alert tone="neutral" title="This site does not ask for any details">
                      The backend reports no required fields for this opportunity - the
                      submission runs without asking you for anything.
                    </Alert>
                  ) : gap.missing.length === 0 ? (
                    <Alert tone="success" title="Everything this site asks for is filled in">
                      The submission can run without asking you for anything else.
                    </Alert>
                  ) : null}

                  {gap.missing.length > 0 ? (
                    <section className="rounded-lg border border-line">
                      <h4 className="border-b border-line px-3 py-2 text-xs font-semibold text-content">
                        Still missing
                      </h4>
                      <ul className="divide-y divide-line">
                        {gap.missing.map((field) => (
                          <li key={field.name} className="px-3 py-2">
                            <GapRow field={field} />
                          </li>
                        ))}
                      </ul>
                    </section>
                  ) : null}

                  {gap.filled.length > 0 ? (
                    <section className="rounded-lg border border-line">
                      <h4 className="border-b border-line px-3 py-2 text-xs font-semibold text-content">
                        Already filled in
                      </h4>
                      <ul className="divide-y divide-line">
                        {gap.filled.map((field) => (
                          <li key={field.name} className="px-3 py-2">
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="text-xs font-medium text-content">
                                {field.label}
                              </span>
                              <Badge tone="success">filled</Badge>
                            </div>
                          </li>
                        ))}
                      </ul>
                    </section>
                  ) : null}

                  <p className="text-[11px] text-content-subtle">
                    {gapReport.data?.source === "client"
                      ? "The backend does not expose the gap endpoint yet - the classification below is derived in the client from the business profile."
                      : "The classification comes from the gap endpoint of the backend - nothing is invented."}
                  </p>
                </>
              )}
            </div>
          ) : (
            <div className="space-y-4">
              <CardSection title="Submission details">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <DetailsStateBadge opportunityId={opportunity.id} />
                  <Button variant="outline" size="sm" onClick={() => setTab("details")}>
                    Open submission details
                  </Button>
                </div>
                <p className="mt-2 text-xs text-content-muted">
                  Everything this site asks for before it accepts the listing. A task with
                  missing details waits for you instead of failing.
                </p>
              </CardSection>

              <CardSection title="Details">
                <KeyValue
                  items={[
                    ["Domain", opportunity.domain],
                    ["URL", opportunity.opportunity_url],
                    ["Discovery source", opportunity.discovery_source],
                    ["Provider", opportunity.discovery_provider ?? "—"],
                    ["Adapter", opportunity.adapter_id ?? "—"],
                    [
                      "Submission method",
                      SUBMISSION_METHOD_LABELS[opportunity.submission_method] ??
                        humanize(opportunity.submission_method),
                    ],
                    [
                      "Registration required",
                      opportunity.registration_required === null
                        ? "—"
                        : opportunity.registration_required
                          ? "Yes"
                          : "No",
                    ],
                    [
                      "Requires approval",
                      opportunity.requires_approval === null
                        ? "—"
                        : opportunity.requires_approval
                          ? "Yes"
                          : "No",
                    ],
                    ["Anchor text", opportunity.anchor_text ?? "—"],
                    ["Target landing page", opportunity.target_landing_page ?? "—"],
                    ["Contact e-mail", opportunity.contact_email ?? "—"],
                    [
                      "Language / region",
                      `${opportunity.language ?? "—"} / ${opportunity.region ?? "—"}`,
                    ],
                    ["Linked task", opportunity.task_id ?? "—"],
                    ["Last checked", formatDateTime(opportunity.last_checked_at)],
                    ["Created", formatDateTime(opportunity.created_at)],
                    ["Updated", formatDateTime(opportunity.updated_at)],
                  ]}
                />
              </CardSection>

              <CardSection title="Score breakdown">
                {breakdown ? (
                  <div className="space-y-3">
                    <div className="grid gap-x-4 gap-y-1 text-xs sm:grid-cols-2">
                      {Object.entries(breakdown)
                        .filter(([key]) => key !== "reasons" && key !== "unavailable_metrics")
                        .map(([key, value]) => (
                          <div key={key} className="flex items-center justify-between gap-2">
                            <span className="text-content-muted">
                              {SCORE_COMPONENT_LABELS[key] ?? humanize(key)}
                            </span>
                            <span className="tabular-nums text-content">
                              {typeof value === "number" ? formatDecimal(value, 2) : String(value)}
                            </span>
                          </div>
                        ))}
                    </div>

                    <div>
                      <p className="mb-1 text-xs font-semibold text-content">Reasons</p>
                      {breakdown.reasons.length === 0 ? (
                        <p className="text-xs text-content-subtle">No reasons recorded by the scorer.</p>
                      ) : (
                        <ul className="list-inside list-disc space-y-0.5 text-xs text-content-muted">
                          {breakdown.reasons.map((reason, index) => (
                            <li key={`${reason}-${index}`}>{reason}</li>
                          ))}
                        </ul>
                      )}
                    </div>

                    <div>
                      <p className="mb-1 text-xs font-semibold text-content">Unavailable metrics</p>
                      {breakdown.unavailable_metrics.length === 0 ? (
                        <p className="text-xs text-content-subtle">All score metrics were available.</p>
                      ) : (
                        <ul className="list-inside list-disc space-y-0.5 text-xs text-content-muted">
                          {breakdown.unavailable_metrics.map((metric, index) => (
                            <li key={`${metric}-${index}`}>{metric}</li>
                          ))}
                        </ul>
                      )}
                    </div>
                  </div>
                ) : (
                  <p className="text-xs text-content-subtle">
                    The backend did not return a score breakdown for this opportunity.
                  </p>
                )}
              </CardSection>

              <CardSection title="Notes & result">
                <KeyValue
                  items={[
                    ["Description", opportunity.description ?? "—"],
                    ["Notes", opportunity.notes ?? "—"],
                    ["Last result", opportunity.last_result ?? "—"],
                    ["Error detail", opportunity.error_detail ?? "—"],
                    ["Duplicate of", opportunity.duplicate_of ?? "—"],
                    ["Excluded until", opportunity.excluded_until ?? "—"],
                  ]}
                />
              </CardSection>

              <CardSection title="Queue target">
                <p className="mb-2 text-xs text-content-muted">
                  Queue tasks inherit the project of the opportunity when no project is selected.
                </p>
                <Select
                  value={projectId}
                  onChange={(event) => setProjectId(event.target.value)}
                  aria-label="Project for the new queue task"
                >
                  <option value="">Use the opportunity&apos;s project</option>
                  {(projects.data?.items ?? []).map((project) => (
                    <option key={project.id} value={project.id}>
                      {project.name}
                    </option>
                  ))}
                </Select>
              </CardSection>
            </div>
          )}
        </div>
      ) : null}

      <Dialog
        open={excludeOpen}
        onClose={() => setExcludeOpen(false)}
        title={`Exclude ${opportunity?.domain ?? "domain"}?`}
        description="The backend adds the domain to the exclusion list so it is not discovered again."
        width="sm"
        footer={
          <>
            <Button
              variant="outline"
              onClick={() => setExcludeOpen(false)}
              disabled={action.pending}
            >
              Cancel
            </Button>
            <Button variant="danger" onClick={excludeDomain} loading={action.pending}>
              Exclude domain
            </Button>
          </>
        }
      >
        <Field label="Reason" hint="Optional note stored with the exclusion.">
          <Input
            value={excludeReason}
            onChange={(event) => setExcludeReason(event.target.value)}
            placeholder="Spam directory"
          />
        </Field>
        {action.error ? (
          <p className="mt-2 text-xs text-danger">{errorMessage(action.error)}</p>
        ) : null}
      </Dialog>
    </Drawer>
  );
}

function CardSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-line">
      <h3 className="border-b border-line px-3 py-2 text-xs font-semibold text-content">{title}</h3>
      <div className="p-3">{children}</div>
    </section>
  );
}

/** One field of the gap report with the reason why it can (not) be derived. */
function GapRow({ field }: { field: GapField }) {
  return (
    <div className="space-y-0.5">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-medium text-content">{field.label}</span>
        {field.derivable ? (
          <Badge tone="success">derivable</Badge>
        ) : (
          <Badge tone="warning">not derivable</Badge>
        )}
        {field.field ? (
          <span className="font-mono text-[10px] text-content-subtle">{field.field}</span>
        ) : (
          <span className="font-mono text-[10px] text-content-subtle">{field.name}</span>
        )}
      </div>
      <p className="text-xs text-content-muted">{field.reason}</p>
    </div>
  );
}
