"use client";

import * as React from "react";

import { ProgressBar, cn } from "./components";

/**
 * The progress of the first-run login browser.
 *
 * Mirrors `ProjectLoginPreparing` of the shared types without importing the
 * package, so the UI package stays usable on its own.
 */
export interface LoginPreparationProgress {
  phase: "starting" | "package" | "browser" | "done" | "error" | string;
  percent: number | null;
  message: string;
  detail?: string | null;
  elapsed?: number;
}

/** One row of the preparation checklist. */
type StepState = "done" | "active" | "pending";

function formatElapsed(seconds: number | undefined): string | null {
  if (seconds === undefined || seconds === null || seconds < 1) return null;
  const total = Math.round(seconds);
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  return minutes > 0
    ? `${minutes}:${String(rest).padStart(2, "0")} min`
    : `${rest} s`;
}

function stepState(step: "engine" | "browser" | "window", phase: string): StepState {
  const order = ["package", "browser", "done"];
  const current = order.indexOf(phase);
  const wanted = step === "engine" ? 0 : step === "browser" ? 1 : 2;
  if (current < 0) return "pending";
  if (wanted < current) return "done";
  if (wanted === current) return "active";
  return "pending";
}

function StepRow({
  state,
  title,
  detail,
}: {
  state: StepState;
  title: string;
  detail?: React.ReactNode;
}) {
  return (
    <li className="flex items-start gap-2">
      <span
        aria-hidden
        className={cn(
          "mt-px flex h-4 w-4 shrink-0 items-center justify-center rounded-full border text-[9px] font-bold",
          state === "done" && "border-success/40 bg-success-soft text-success",
          state === "active" && "border-accent/40 bg-accent-soft text-accent",
          state === "pending" && "border-line bg-surface text-content-subtle",
        )}
      >
        {state === "done" ? "✓" : state === "active" ? "•" : ""}
      </span>
      <span className="min-w-0">
        <span
          className={cn(
            "text-[11px]",
            state === "done" && "text-content-muted",
            state === "active" && "font-medium text-content",
            state === "pending" && "text-content-subtle",
          )}
        >
          {title}
        </span>
        {detail ? (
          <span className="block text-[10px] text-content-subtle">{detail}</span>
        ) : null}
      </span>
    </li>
  );
}

/**
 * What is happening, how far it is, and what the operator has to do once the
 * window opens.  Shown in the login card and inside the live viewer while the
 * backend installs the runtime on first use.
 */
export function LoginProgress({
  progress,
  compact = false,
}: {
  progress: LoginPreparationProgress;
  /** Skip the "what to do next" block (the card shows it already). */
  compact?: boolean;
}) {
  const phase = String(progress.phase || "starting");
  const percent =
    typeof progress.percent === "number" && Number.isFinite(progress.percent)
      ? Math.max(0, Math.min(100, progress.percent))
      : null;
  const elapsed = formatElapsed(progress.elapsed);
  const activeBrowser = phase === "browser";
  const done = phase === "done";

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <p className="text-xs font-medium text-content">{progress.message}</p>
        <span className="flex items-center gap-2 text-[10px] tabular-nums text-content-subtle">
          {percent !== null ? <span>{Math.round(percent)}%</span> : null}
          {elapsed ? <span>{elapsed}</span> : null}
        </span>
      </div>

      {percent !== null ? (
        <ProgressBar value={percent / 100} />
      ) : (
        <div
          className="h-1.5 w-full overflow-hidden rounded-full bg-line"
          role="progressbar"
          aria-label={progress.message}
        >
          <div className="h-full w-1/3 animate-pulse rounded-full bg-accent" />
        </div>
      )}
      {progress.detail ? (
        <p className="truncate text-[10px] text-content-subtle">{progress.detail}</p>
      ) : null}

      <ol className="space-y-1.5">
        <StepRow
          state={stepState("engine", phase)}
          title="Browser engine (Playwright)"
          detail="One-time download into the application data folder."
        />
        <StepRow
          state={stepState("browser", phase)}
          title="Chromium browser (about 104 MB)"
          detail={
            activeBrowser && percent !== null
              ? `Downloading - ${Math.round(percent)}%`
              : activeBrowser
                ? "Downloading…"
                : undefined
          }
        />
        <StepRow
          state={stepState("window", phase)}
          title="Open the login window"
          detail={
            done
              ? "The window opens in a moment."
              : "It opens automatically when the download finishes."
          }
        />
      </ol>

      {!compact ? (
        <div className="rounded-md border border-line bg-surface-raised px-3 py-2">
          <p className="text-[11px] font-semibold text-content">What to do next</p>
          <ol className="mt-1 list-decimal space-y-0.5 pl-4 text-[11px] text-content-muted">
            <li>
              Wait here. The login window opens by itself - you do not have to
              click again. First run usually takes 1-3 minutes.
            </li>
            <li>
              Sign in with the Google account of this project. Type the password
              and any 2FA code yourself; the app never fills them.
            </li>
            <li>
              When your Google account is visible, press{" "}
              <span className="font-medium text-content">
                I&apos;m done - save session
              </span>
              .
            </li>
          </ol>
          <p className="mt-1.5 text-[10px] text-content-subtle">
            Keep this page open. You can cancel at any time.
          </p>
        </div>
      ) : null}
    </div>
  );
}
