"use client";

import * as React from "react";

import { Badge, Button, ProgressBar, cn } from "./components";

/**
 * The account of one website, as the campaign report shows it.
 *
 * Mirrors `SiteAccount` of the shared types without importing the package, so
 * the UI package stays usable on its own (the same pattern as the login view).
 */
export interface SiteAccountView {
  strategy: "GOOGLE" | "SIGNUP" | "EXISTING" | "DIRECT" | "MANUAL" | "UNKNOWN";
  status:
    | "NOT_STARTED"
    | "QUEUED"
    | "DETECTING"
    | "CREATING"
    | "OTP_PENDING"
    | "ACTIVE"
    | "NEEDS_HUMAN"
    | "FAILED";
  email: string | null;
  username: string | null;
  password: string | null;
  otp_state: "NONE" | "WAITING" | "RECEIVED" | "USED" | "EXPIRED";
  backlink_url: string | null;
  backlink_confidence: number;
  backlink_status?: "NONE" | "POSTED" | "VERIFIED" | "NEEDS_HUMAN" | "FAILED";
  site_intel?: {
    platform?: string;
    plan?: string;
    signup_urls?: string[];
    oauth?: { provider?: string; how?: string }[];
    backlink_urls?: string[];
    fields?: { filled?: string[]; skipped?: { field?: string; why?: string }[] };
    notes?: string[];
    direct?: { kind?: string } | null;
  };
  backlink_published_url?: string | null;
  backlink_note?: string | null;
  last_error: string | null;
}

export interface AccountBatchView {
  running: boolean;
  total: number;
  done: number;
  message: string | null;
  active_name: string | null;
  error: string | null;
  counts?: Record<string, number>;
}

const STRATEGY_LABEL: Record<SiteAccountView["strategy"], string> = {
  GOOGLE: "Google",
  SIGNUP: "User + pass",
  EXISTING: "Already there",
  DIRECT: "No account needed",
  MANUAL: "Manual",
  UNKNOWN: "Not detected",
};

const STATUS_LABEL: Record<SiteAccountView["status"], string> = {
  NOT_STARTED: "Not created",
  QUEUED: "Queued",
  DETECTING: "Detecting",
  CREATING: "Creating",
  OTP_PENDING: "Waiting for code",
  ACTIVE: "Active",
  NEEDS_HUMAN: "Needs you",
  FAILED: "Failed",
};

const STATUS_TONE: Record<
  SiteAccountView["status"],
  "success" | "warning" | "danger" | "info" | "neutral"
> = {
  NOT_STARTED: "neutral",
  QUEUED: "info",
  DETECTING: "info",
  CREATING: "info",
  OTP_PENDING: "info",
  ACTIVE: "success",
  NEEDS_HUMAN: "warning",
  FAILED: "danger",
};

function CopyButton({ value }: { value: string }) {
  const [copied, setCopied] = React.useState(false);
  return (
    <button
      type="button"
      className="rounded border border-line px-1 text-[9px] text-content-subtle hover:text-content"
      title={`Copy ${value}`}
      onClick={() => {
        void (async () => {
          try {
            await navigator.clipboard.writeText(value);
            setCopied(true);
            window.setTimeout(() => setCopied(false), 1200);
          } catch {
            setCopied(false);
          }
        })();
      }}
    >
      {copied ? "ok" : "copy"}
    </button>
  );
}

function CredentialRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center gap-1">
      <span className="w-7 shrink-0 text-[9px] uppercase tracking-wide text-content-subtle">
        {label}
      </span>
      <code
        className="min-w-0 flex-1 truncate font-mono text-[10px] text-content"
        title={value}
      >
        {value}
      </code>
      <CopyButton value={value} />
    </div>
  );
}

/**
 * One cell of the report: the strategy, the generated username / password and
 * the real state of the account.  A CAPTCHA is never hidden - the row says
 * *Needs you* and offers the retry button.
 */
export function SiteAccountCell({
  account,
  busy = false,
  onRetry,
}: {
  account: SiteAccountView | null;
  busy?: boolean;
  onRetry?: () => void;
}) {
  if (!account) {
    return <span className="text-[11px] text-content-subtle">Not created</span>;
  }
  return (
    <div className="w-56 space-y-1">
      <div className="flex flex-wrap items-center gap-1">
        <Badge tone={STATUS_TONE[account.status]} className="px-1 py-0 text-[9px]">
          {STATUS_LABEL[account.status]}
        </Badge>
        <span className="text-[10px] text-content-subtle">
          {STRATEGY_LABEL[account.strategy]}
        </span>
        {account.site_intel?.platform && account.site_intel.platform !== "unknown" ? (
          <span
            className="text-[9px] text-content-subtle"
            title={[
              ...(account.site_intel.notes ?? []),
              account.site_intel.fields?.skipped?.length
                ? "Left empty: " +
                  account.site_intel.fields.skipped
                    .map((item) => item.field)
                    .filter(Boolean)
                    .join(", ")
                : "",
            ]
              .filter(Boolean)
              .join(" ")}
          >
            {account.site_intel.platform}
            {account.site_intel.plan === "GOOGLE" ? " · Google" : ""}
          </span>
        ) : null}
      </div>
      {account.username ? (
        <CredentialRow label="user" value={account.username} />
      ) : null}
      {account.password ? (
        <CredentialRow label="pass" value={account.password} />
      ) : null}
      {account.email ? (
        <p className="truncate text-[9px] text-content-subtle" title={account.email}>
          {account.email}
        </p>
      ) : null}
      {account.otp_state === "WAITING" || account.otp_state === "RECEIVED" ? (
        <p className="text-[9px] text-info">E-mail code: {account.otp_state.toLowerCase()}</p>
      ) : null}
      {account.backlink_status && account.backlink_status !== "NONE" ? (
        <div className="space-y-0.5">
          <p
            className={cn(
              "text-[9px] font-medium",
              account.backlink_status === "VERIFIED"
                ? "text-success"
                : account.backlink_status === "POSTED"
                  ? "text-info"
                  : "text-warning",
            )}
          >
            {account.backlink_status === "VERIFIED"
              ? "Backlink verified"
              : account.backlink_status === "POSTED"
                ? "Backlink posted"
                : "Backlink needs you"}
          </p>
          {account.backlink_published_url ? (
            <a
              href={account.backlink_published_url}
              target="_blank"
              rel="noreferrer"
              className="block truncate text-[9px] text-accent underline"
              title={account.backlink_published_url}
            >
              {account.backlink_published_url}
            </a>
          ) : null}
          {account.backlink_note &&
          account.backlink_status !== "VERIFIED" &&
          account.backlink_status !== "POSTED" ? (
            <p
              className="line-clamp-2 text-[9px] text-warning"
              title={account.backlink_note}
            >
              {account.backlink_note}
            </p>
          ) : null}
        </div>
      ) : null}
      {account.last_error ? (
        <p
          className={cn(
            "line-clamp-2 text-[10px]",
            account.status === "FAILED" ? "text-danger" : "text-warning",
          )}
          title={account.last_error}
        >
          {account.last_error}
        </p>
      ) : null}
      {onRetry &&
      (account.status === "NEEDS_HUMAN" ||
        account.status === "FAILED" ||
        account.backlink_status === "NEEDS_HUMAN") ? (
        <Button size="sm" variant="outline" loading={busy} onClick={onRetry}>
          Retry
        </Button>
      ) : null}
    </div>
  );
}

/** The live state of the one account batch of a project. */
export function AccountBatchBanner({
  batch,
  busy = false,
  onStop,
  onStart,
  startLabel = "Create accounts",
}: {
  batch: AccountBatchView | null;
  busy?: boolean;
  onStop?: () => void;
  onStart?: () => void;
  startLabel?: string;
}) {
  if (!batch || (batch.total === 0 && !batch.running)) {
    return null;
  }
  const percent = batch.total > 0 ? Math.round((batch.done / batch.total) * 100) : 0;
  const needsHuman = batch.counts?.NEEDS_HUMAN ?? 0;
  const active = batch.counts?.ACTIVE ?? 0;
  return (
    <div className="mt-3 space-y-2 rounded-lg border border-accent/20 bg-accent-soft/30 px-3 py-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="text-xs font-semibold text-content">
            {batch.running
              ? `Creating accounts - ${batch.done}/${batch.total}`
              : `Account batch finished - ${active} active`}
          </p>
          <p className="truncate text-[11px] text-content-muted">
            {batch.error
              ? batch.error
              : batch.running && batch.active_name
                ? `Working on ${batch.active_name}`
                : batch.message ?? "One browser, one Gmail session."}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {batch.running && onStop ? (
            <Button size="sm" variant="outline" loading={busy} onClick={onStop}>
              Stop
            </Button>
          ) : null}
          {!batch.running && onStart ? (
            <Button size="sm" variant="outline" loading={busy} onClick={onStart}>
              {startLabel}
            </Button>
          ) : null}
        </div>
      </div>
      <ProgressBar value={percent / 100} />
      <div className="flex flex-wrap gap-3 text-[10px] text-content-subtle">
        <span>{percent}% done</span>
        {active > 0 ? <span className="text-success">{active} active</span> : null}
        {needsHuman > 0 ? <span className="text-warning">{needsHuman} need you</span> : null}
        {(batch.counts?.FAILED ?? 0) > 0 ? (
          <span className="text-danger">{batch.counts?.FAILED} failed</span>
        ) : null}
        {batch.running ? <span>You can keep using the app.</span> : null}
      </div>
    </div>
  );
}

/** The backlink page of a row: a link, the confidence and the find button. */
export function BacklinkTargetCell({
  account,
  busy = false,
  onFind,
}: {
  account: SiteAccountView | null;
  busy?: boolean;
  onFind?: () => void;
}) {
  if (!account) {
    return <span className="text-[11px] text-content-subtle">-</span>;
  }
  if (account.backlink_url) {
    return (
      <div className="w-40 space-y-1">
        <a
          href={account.backlink_url}
          target="_blank"
          rel="noopener noreferrer"
          className="block truncate text-[11px] text-accent hover:underline"
          title={account.backlink_url}
        >
          {account.backlink_url.replace(/^https?:\/\//, "")}
        </a>
        <div className="flex items-center gap-1">
          <Badge
            tone={account.backlink_confidence >= 75 ? "success" : "warning"}
            className="px-1 py-0 text-[9px]"
          >
            {account.backlink_confidence}% sure
          </Badge>
          {onFind ? (
            <Button size="sm" variant="ghost" loading={busy} onClick={onFind}>
              Find again
            </Button>
          ) : null}
        </div>
      </div>
    );
  }
  return (
    <div className="w-40 space-y-1">
      <span className="text-[11px] text-content-subtle">Not found yet</span>
      {account.status === "ACTIVE" && onFind ? (
        <Button size="sm" variant="outline" loading={busy} onClick={onFind}>
          Find page
        </Button>
      ) : null}
    </div>
  );
}
