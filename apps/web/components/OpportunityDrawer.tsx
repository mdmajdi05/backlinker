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
  StatusBadge,
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

export function OpportunityDrawer({
  opportunity,
  open,
  onClose,
  onChanged,
}: {
  opportunity: Opportunity | null;
  open: boolean;
  onClose: () => void;
  onChanged?: () => void;
}) {
  const toast = useToast();
  const action = useAction();
  const [projectId, setProjectId] = React.useState("");
  const [excludeOpen, setExcludeOpen] = React.useState(false);
  const [excludeReason, setExcludeReason] = React.useState("");

  const projects = useResource(() => api.projects.list(apiClient, { page: 1, page_size: 100 }), []);

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
                ["Language / region", `${opportunity.language ?? "—"} / ${opportunity.region ?? "—"}`],
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
