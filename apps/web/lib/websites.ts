/** Helpers of the central website list (the websites a project gets backlinks on). */

import { WEBSITE_STATUSES } from "@autobacklinker/shared-types";
import { humanize } from "@/lib/format";

/**
 * The state a removed website carries.
 *
 * The delete action does not destroy a website - it takes it out of the list
 * and marks it as `DELETED`.  The backend hides those rows from the normal
 * list and only shows them when the filter asks for them (the recycle bin).
 */
export const REMOVED_WEBSITE_STATUS = "DELETED";

/** The badge of a website that lives in the recycle bin. */
export const REMOVED_WEBSITE_LABEL = "Removed";

/**
 * The states the user can assign to a website from the list.
 *
 * They are the states of the product spec - a site that stopped working is
 * marked "NOT_WORKING".  `DELETED` is not one of them: a website leaves the
 * list through the delete action, not through the state drop-down.
 */
export const WEBSITE_STATUS_CHOICES = [
  "ACTIVE",
  "NEEDS_REVIEW",
  "APPROVED",
  "NOT_WORKING",
  "EXCLUDED",
  "REJECTED",
] as const;

export type WebsiteStatusChoice = (typeof WEBSITE_STATUS_CHOICES)[number];

/** Human readable labels of the states of a website. */
export const WEBSITE_STATUS_LABELS: Record<string, string> = {
  DISCOVERED: "Discovered",
  NEEDS_REVIEW: "Needs review",
  APPROVED: "Approved",
  ACTIVE: "Active",
  NOT_WORKING: "Not working",
  DELETED: REMOVED_WEBSITE_LABEL,
  EXCLUDED: "Excluded",
  REJECTED: "Rejected",
  DUPLICATE: "Duplicate",
};

/** Every state the backend knows - the filter offers all of them. */
export const ALL_WEBSITE_STATUSES: string[] = [...WEBSITE_STATUSES];

/**
 * The states the status filter offers.
 *
 * The removed websites have their own view (the recycle bin) - the filter
 * therefore does not offer "Deleted" a second time.
 */
export const WEBSITE_STATUS_FILTERS: string[] = ALL_WEBSITE_STATUSES.filter(
  (value) => value !== REMOVED_WEBSITE_STATUS,
);

/**
 * True when the website was removed from the list.
 *
 * A removed website lives in the recycle bin: it is hidden in the normal
 * view, its history is kept and it can be restored.
 */
export function isRemovedWebsite(status: string | null | undefined): boolean {
  return (status ?? "").trim().toUpperCase() === REMOVED_WEBSITE_STATUS;
}

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
