"use client";

import * as React from "react";
import { api } from "@autobacklinker/api-client";
import type { ProjectLogin } from "@autobacklinker/shared-types";
import {
  Alert,
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  LoginProgress,
  LoginViewer,
  useToast,
} from "@autobacklinker/ui";
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
  const [viewerOpen, setViewerOpen] = React.useState(false);
  const onChangedRef = React.useRef(onChanged);
  const notifiedRef = React.useRef(false);
  const dismissedRef = React.useRef(false);

  React.useEffect(() => {
    onChangedRef.current = onChanged;
  }, [onChanged]);

  React.useEffect(() => {
    if (login) setState(login);
  }, [login]);

  const loginOpen = state?.login_open ?? false;
  const streaming = loginOpen && state?.view === "remote";

  // A page reload (or a second tab) can join an already running stream, but a
  // viewer the operator explicitly closed stays closed until they open it.
  React.useEffect(() => {
    if (!loginOpen) {
      dismissedRef.current = false;
      setViewerOpen(false);
      return;
    }
    if (streaming && !dismissedRef.current) setViewerOpen(true);
  }, [loginOpen, streaming]);

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
    }, 1200);
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
      dismissedRef.current = false;
      const result = await api.projectLogin.connectGoogle(
        apiClient,
        projectId,
        state?.email ?? undefined,
        "remote",
      );
      toast.push(
        result.running
          ? result.view === "remote"
            ? "Login browser opened. Sign in in the live view below."
            : "Login window opened. Sign in with Google there - this card updates itself."
          : result.message ?? "The login window could not be opened.",
        result.running ? "success" : "info",
      );
      const next = await api.projectLogin.get(apiClient, projectId);
      setState(next);
      if (result.running && result.view === "remote") setViewerOpen(true);
    }, "The login window could not be opened");

  const finish = () =>
    run(async () => {
      const result = await api.projectLogin.finish(apiClient, projectId);
      setViewerOpen(false);
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
      setViewerOpen(false);
      setState(result.login);
      toast.push("The stored Google session was removed.", "success");
      onChanged?.();
    }, "The login could not be forgotten");

  const cancel = () =>
    run(async () => {
      await api.projectLogin.cancel(apiClient, projectId);
      setViewerOpen(false);
      setState(await api.projectLogin.get(apiClient, projectId));
    }, "The login window could not be closed");

  const closeViewer = () => {
    dismissedRef.current = true;
    setViewerOpen(false);
  };

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
        ) : !connected && !loginOpen && state?.last_error ? (
          // The last attempt did not connect: show the reason instead of only
          // "Not connected".
          <Alert tone={expired ? "warning" : "danger"} title="Google login">
            {state.last_error}
          </Alert>
        ) : null}
        {error ? (
          <Alert tone="danger" title="Google login">
            {error}
          </Alert>
        ) : null}
        {state?.preparing ? (
          <Alert tone="info" title="Preparing the login browser">
            <LoginProgress progress={state.preparing} />
          </Alert>
        ) : loginOpen ? (
          <Alert tone="info" title="The login window is open">
            Sign in with this project&apos;s Google account in the login view, then
            press <span className="font-medium text-content">I&apos;m done - save session</span>.
            Passwords and 2FA codes are typed by you only.
          </Alert>
        ) : null}

        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <p className="truncate text-sm text-content">
              {connected
                ? state?.email
                  ? `Google: connected (${state.email})`
                  : "Google: connected"
                : expired
                  ? "Google login expired - re-login to continue."
                  : status === "LOGIN_OPEN"
                    ? state?.preparing
                      ? "Preparing the login browser…"
                      : "Sign in in the login view."
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
                {streaming && !viewerOpen ? (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => {
                      dismissedRef.current = false;
                      setViewerOpen(true);
                    }}
                  >
                    Open login view
                  </Button>
                ) : null}
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

      <LoginViewer
        open={viewerOpen && streaming}
        title="Google sign-in"
        description="The browser runs on the machine that owns this project's profile. Type and click directly in the live view."
        warning={state?.warning}
        preparing={state?.preparing ?? null}
        issueTicket={() => api.projectLogin.streamTicket(apiClient, projectId)}
        onClose={closeViewer}
        onClosed={() => {
          setViewerOpen(false);
          void api.projectLogin
            .get(apiClient, projectId)
            .then((next) => {
              setState(next);
              if (next.status === "CONNECTED") onChangedRef.current?.();
            })
            .catch(() => undefined);
        }}
        onSave={finish}
        saving={busy}
      />
    </Card>
  );
}
