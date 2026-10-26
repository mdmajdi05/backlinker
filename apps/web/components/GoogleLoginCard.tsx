"use client";

import * as React from "react";
import { api } from "@autobacklinker/api-client";
import type { ProjectLogin } from "@autobacklinker/shared-types";
import { Alert, Badge, Button, Card, CardBody, CardHeader, useToast } from "@autobacklinker/ui";
import { apiClient, errorMessage } from "@/lib/api";
import { formatDateTime } from "@/lib/format";

const LOGIN_LABELS: Record<ProjectLogin["status"], string> = {
  NOT_CONNECTED: "Not connected",
  LOGIN_OPEN: "Login window open",
  CONNECTED: "Connected",
  EXPIRED: "Login expired",
  ERROR: "Error",
};

/**
 * The Google account of one project.
 *
 * The visible browser window opens on the machine that runs the backend.  In
 * the desktop app that is this Mac; a hosted deployment cannot show a window,
 * and the card says so instead of pretending that it worked.
 */
export function GoogleLoginCard({
  projectId,
  login,
  onChanged,
}: {
  projectId: string;
  login: ProjectLogin | null | undefined;
  onChanged?: () => void;
}) {
  const toast = useToast();
  const [state, setState] = React.useState<ProjectLogin | null>(login ?? null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const onChangedRef = React.useRef(onChanged);
  const notifiedRef = React.useRef(false);

  React.useEffect(() => {
    onChangedRef.current = onChanged;
  }, [onChanged]);

  React.useEffect(() => {
    if (login) setState(login);
  }, [login]);

  const loginOpen = state?.login_open ?? false;
  React.useEffect(() => {
    if (!loginOpen) return;
    let cancelled = false;
    const timer = window.setInterval(() => {
      void api.projectLogin
        .get(apiClient, projectId)
        .then((next) => {
          if (cancelled) return;
          setState(next);
          if (next.status === "CONNECTED" && !notifiedRef.current) {
            notifiedRef.current = true;
            onChangedRef.current?.();
          }
        })
        .catch(() => undefined);
    }, 2500);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [loginOpen, projectId]);

  const run = async (action: () => Promise<void>, fallback: string) => {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(errorMessage(err) || fallback);
    } finally {
      setBusy(false);
    }
  };

  const connect = () =>
    run(async () => {
      notifiedRef.current = false;
      const result = await api.projectLogin.connectGoogle(
        apiClient,
        projectId,
        state?.email ?? undefined,
      );
      toast.push(
        result.running
          ? "Login window opened. Sign in with Google there - this card updates itself."
          : result.message ?? "The login window could not be opened.",
        result.running ? "success" : "info",
      );
      setState(await api.projectLogin.get(apiClient, projectId));
    }, "The login window could not be opened");

  const finish = () =>
    run(async () => {
      const result = await api.projectLogin.finish(apiClient, projectId);
      if (result.login) setState(result.login);
      toast.push(
        result.saved
          ? result.resumed
            ? `Login saved. ${result.resumed} paused website(s) queued again.`
            : "Login saved."
          : result.message ?? "No new session was saved.",
        result.saved ? "success" : "info",
      );
      onChanged?.();
    }, "The login could not be saved");

  const forget = () =>
    run(async () => {
      const result = await api.projectLogin.forget(apiClient, projectId);
      setState(result.login);
      toast.push("The stored Google session was removed.", "success");
      onChanged?.();
    }, "The login could not be forgotten");

  const cancel = () =>
    run(async () => {
      await api.projectLogin.cancel(apiClient, projectId);
      setState(await api.projectLogin.get(apiClient, projectId));
    }, "The login window could not be closed");

  const status = state?.status ?? "NOT_CONNECTED";
  const connected = status === "CONNECTED";
  const expired = status === "EXPIRED";

  return (
    <Card>
      <CardHeader
        title="Google login"
        description="One Google account per project, stored encrypted on the machine that runs the backend."
        action={
          <Badge tone={connected ? "success" : expired ? "warning" : "neutral"}>
            {LOGIN_LABELS[status]}
          </Badge>
        }
      />
      <CardBody className="space-y-3">
        {expired ? (
          <Alert tone="warning" title="Google login expired">
            The session of this project expired. Re-login once and the paused websites
            continue automatically.
          </Alert>
        ) : null}
        {status === "ERROR" && state?.last_error ? (
          <Alert tone="danger" title="The Google session needs attention">
            {state.last_error}
          </Alert>
        ) : null}
        {error ? (
          <Alert tone="danger" title="Google login">
            {error}
          </Alert>
        ) : null}

        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <p className="truncate text-sm text-content">
              {connected && state?.email
                ? `Google: connected (${state.email})`
                : expired
                  ? "Google login expired - re-login to continue."
                  : status === "LOGIN_OPEN"
                    ? "Sign in in the browser window that just opened."
                    : "Google is not connected for this project yet."}
            </p>
            <p className="text-[11px] text-content-subtle">
              {state?.paused_tasks
                ? `${state.paused_tasks} website(s) paused at a login wall and will resume after the login.`
                : state?.last_login_at
                  ? `Last login: ${formatDateTime(state.last_login_at)}`
                  : "Passwords and two factor codes are never filled by the app."}
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {loginOpen ? (
              <>
                <Button size="sm" loading={busy} onClick={() => void finish()}>
                  I&apos;m done - save session
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={busy}
                  onClick={() => void cancel()}
                >
                  Cancel
                </Button>
              </>
            ) : (
              <Button
                size="sm"
                loading={busy}
                variant={connected ? "outline" : "primary"}
                onClick={() => void connect()}
              >
                {connected || expired ? "Re-login" : "Connect Google"}
              </Button>
            )}
            {connected && !loginOpen ? (
              <Button
                size="sm"
                variant="ghost"
                className="text-danger hover:bg-danger-soft"
                disabled={busy}
                onClick={() => void forget()}
              >
                Forget
              </Button>
            ) : null}
          </div>
        </div>

        {state?.browser_available === false ? (
          <p className="text-[11px] text-warning">
            Browser automation is turned off in Settings, so the visible login window
            cannot open.
          </p>
        ) : null}
      </CardBody>
    </Card>
  );
}
