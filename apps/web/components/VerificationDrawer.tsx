"use client";

import * as React from "react";
import { api } from "@autobacklinker/api-client";
import type { BacklinkRecord, VerificationRun } from "@autobacklinker/shared-types";
import { Alert, Badge, Drawer, KeyValue, StatusBadge } from "@autobacklinker/ui";
import { apiClient, errorMessage } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import { formatDateTime, humanize } from "@/lib/format";
import { VERIFICATION_STATUS_LABELS } from "@/lib/constants";

export function VerificationDrawer({
  record,
  open,
  onClose,
}: {
  record: BacklinkRecord | null;
  open: boolean;
  onClose: () => void;
}) {
  const recordId = record?.id ?? null;
  const history = useResource(
    () =>
      recordId
        ? api.verification.history(apiClient, recordId)
        : Promise.resolve<VerificationRun[]>([]),
    [recordId],
    { enabled: Boolean(recordId) },
  );

  return (
    <Drawer
      open={open && Boolean(record)}
      onClose={onClose}
      title={record ? `Backlink ${record.id.slice(0, 8)}` : "Backlink"}
      width="lg"
    >
      {record ? (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={record.verification_status} />
            <Badge tone={record.is_live === true ? "success" : "neutral"}>
              {record.is_live === true ? "Link live" : record.is_live === false ? "Link missing" : "Live state unknown"}
            </Badge>
            {record.link_present === true ? (
              <Badge tone="success">Link present</Badge>
            ) : record.link_present === false ? (
              <Badge tone="danger">Link absent</Badge>
            ) : null}
            {record.destination_matched === true ? (
              <Badge tone="success">Destination matched</Badge>
            ) : record.destination_matched === false ? (
              <Badge tone="danger">Destination mismatch</Badge>
            ) : null}
          </div>

          {record.verification_status === "PUBLISHED_UNVERIFIED" ? (
            <Alert tone="warning" title="Published but not verified">
              The backend recorded a submission but has not yet confirmed that the link is live.
            </Alert>
          ) : null}

          {record.verification_status === "VERIFIED_LIVE" ? (
            <Alert tone="success" title="Verified live">
              A stored verification run confirmed the link on the published page.
            </Alert>
          ) : null}

          {record.error ? (
            <Alert tone="danger" title="Last error">
              {record.error}
            </Alert>
          ) : null}

          <section className="rounded-lg border border-line">
            <h3 className="border-b border-line px-3 py-2 text-xs font-semibold text-content">
              Record
            </h3>
            <div className="p-3">
              <KeyValue
                items={[
                  ["Project", record.project_id],
                  ["Opportunity", record.opportunity_id ?? "—"],
                  ["Task", record.task_id ?? "—"],
                  ["Target website", record.target_website],
                  ["Expected link URL", record.expected_link_url],
                  ["Published page URL", record.published_page_url ?? "—"],
                  ["Expected destination", record.expected_destination_url],
                  ["Observed destination", record.observed_destination_url ?? "—"],
                  ["Observed anchor text", record.observed_anchor_text ?? "—"],
                  ["Link attribute", record.link_attribute ?? "—"],
                  ["HTTP status", record.http_status === null ? "—" : String(record.http_status)],
                  ["Verified at", formatDateTime(record.verified_at)],
                  ["Last success", formatDateTime(record.last_success_at)],
                  ["Next verification", formatDateTime(record.next_verification_at)],
                  ["Created", formatDateTime(record.created_at)],
                  ["Updated", formatDateTime(record.updated_at)],
                ]}
              />
            </div>
          </section>

          <section className="rounded-lg border border-line">
            <h3 className="border-b border-line px-3 py-2 text-xs font-semibold text-content">
              Verification history
            </h3>
            <div className="p-3">
              {history.loading ? (
                <p className="text-xs text-content-subtle">Loading history…</p>
              ) : history.error ? (
                <p className="text-xs text-danger">{errorMessage(history.error)}</p>
              ) : (history.data ?? []).length === 0 ? (
                <p className="text-xs text-content-subtle">
                  No verification run has been stored for this record yet.
                </p>
              ) : (
                <ol className="space-y-2">
                  {(history.data ?? []).map((run) => (
                    <li key={run.id} className="rounded-md border border-line p-2">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <StatusBadge status={run.status} />
                        <span className="text-[11px] text-content-muted">
                          {formatDateTime(run.verified_at)}
                        </span>
                      </div>
                      <dl className="mt-2 grid grid-cols-[120px_1fr] gap-x-3 gap-y-1 text-[11px]">
                        <dt className="text-content-muted">Anchor text</dt>
                        <dd className="text-content">{run.observed_anchor_text ?? "—"}</dd>
                        <dt className="text-content-muted">Destination</dt>
                        <dd className="break-all text-content">
                          {run.observed_destination_url ?? "—"}
                        </dd>
                        <dt className="text-content-muted">Link attribute</dt>
                        <dd className="text-content">{run.link_attribute ?? "—"}</dd>
                        <dt className="text-content-muted">HTTP status</dt>
                        <dd className="text-content">
                          {run.http_status === null ? "—" : String(run.http_status)}
                        </dd>
                        <dt className="text-content-muted">Link present</dt>
                        <dd className="text-content">
                          {run.link_present === null ? "—" : run.link_present ? "Yes" : "No"}
                        </dd>
                        <dt className="text-content-muted">Destination matched</dt>
                        <dd className="text-content">
                          {run.destination_matched === null
                            ? "—"
                            : run.destination_matched
                              ? "Yes"
                              : "No"}
                        </dd>
                        <dt className="text-content-muted">Error</dt>
                        <dd className="text-danger">{run.error ?? "—"}</dd>
                      </dl>
                      {run.evidence ? (
                        <details className="mt-2">
                          <summary className="cursor-pointer text-[11px] text-content-muted">
                            Evidence
                          </summary>
                          <pre className="mt-1 max-h-40 overflow-auto rounded bg-surface-sunken p-2 text-[10px]">
                            {JSON.stringify(run.evidence, null, 2)}
                          </pre>
                        </details>
                      ) : null}
                    </li>
                  ))}
                </ol>
              )}
            </div>
          </section>

          <p className="text-[11px] text-content-subtle">
            Status {VERIFICATION_STATUS_LABELS[record.verification_status] ??
              humanize(record.verification_status)}
          </p>
        </div>
      ) : null}
    </Drawer>
  );
}
