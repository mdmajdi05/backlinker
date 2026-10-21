/** Helpers of the central website list (the websites a project gets backlinks on). */

import { WEBSITE_STATUSES } from "@autobacklinker/shared-types";
import { humanize } from "@/lib/format";

/**
 * The states the user can assign to a website from the list.
 *
 * They are the states of the product spec - a site that stopped working is
 * marked "NOT_WORKING", a site that is gone "DELETED".
 */
export const WEBSITE_STATUS_CHOICES = [
  "ACTIVE",
  "NEEDS_REVIEW",
  "APPROVED",
  "NOT_WORKING",
  "EXCLUDED",
  "REJECTED",
  "DELETED",
] as const;

export type WebsiteStatusChoice = (typeof WEBSITE_STATUS_CHOICES)[number];

/** Human readable labels of the states of a website. */
export const WEBSITE_STATUS_LABELS: Record<string, string> = {
  DISCOVERED: "Discovered",
  NEEDS_REVIEW: "Needs review",
  APPROVED: "Approved",
  ACTIVE: "Active",
  NOT_WORKING: "Not working",
  DELETED: "Deleted",
  EXCLUDED: "Excluded",
  REJECTED: "Rejected",
  DUPLICATE: "Duplicate",
};

/** Every state the backend knows - the filter offers all of them. */
export const ALL_WEBSITE_STATUSES: string[] = [...WEBSITE_STATUSES];

/** The label of a state (falls back to a readable version of the raw value). */
export function websiteStatusLabel(status: string | null | undefined): string {
  if (!status) return "—";
  return WEBSITE_STATUS_LABELS[status] ?? humanize(status);
}

/** True when the state says that the site does not work any more. */
export function isDeadWebsiteStatus(status: string | null | undefined): boolean {
  return status === "NOT_WORKING" || status === "DELETED" || status === "REJECTED";
}

/** The counters the report and the list show per website. */
export interface WebsiteCounters {
  submitted: number;
  verified: number;
  failed: number;
  pending: number;
}

/** Reads the counters of a row without inventing values. */
export function readCounters(source: {
  submitted?: number | null;
  verified?: number | null;
  failed?: number | null;
  pending?: number | null;
} | null | undefined): WebsiteCounters | null {
  if (!source) return null;
  return {
    submitted: source.submitted ?? 0,
    verified: source.verified ?? 0,
    failed: source.failed ?? 0,
    pending: source.pending ?? 0,
  };
}
