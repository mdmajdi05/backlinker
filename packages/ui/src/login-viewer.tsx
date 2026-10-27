"use client";

import * as React from "react";

import { Alert, Badge, Button, IconButton, Spinner, cn } from "./components";
import { LoginProgress, type LoginPreparationProgress } from "./login-progress";

/**
 * A live, interactive view of the login browser.
 *
 * The backend runs Chromium on the machine that owns the project profile and
 * sends JPEG frames over a WebSocket.  This component paints them on a canvas
 * and forwards pointer, wheel and keyboard input, so a web client (or a
 * desktop app talking to a hosted backend) can complete the same manual Google
 * sign-in as the native desktop window.
 *
 * The WebSocket URL contains a short lived, single use ticket - never the
 * session JWT.  A reconnect asks `issueTicket` for a fresh one.
 */
export interface LoginViewerTicket {
  /** Absolute `ws://` / `wss://` URL including the stream ticket. */
  url: string;
}

export interface LoginViewerProps {
  open: boolean;
  title?: React.ReactNode;
  description?: React.ReactNode;
  /** A warning from the backend (for example that it runs headless). */
  warning?: string | null;
  /** First-run download progress; covers the view until the window is ready. */
  preparing?: LoginPreparationProgress | null;
  /** Ask the backend for a fresh ticket and the ready WebSocket URL. */
  issueTicket: () => Promise<LoginViewerTicket>;
  onClose: () => void;
  /** The backend closed the window (login finished or cancelled). */
  onClosed?: () => void;
  /** Optional "I'm done" action of the surrounding card. */
  onSave?: () => void | Promise<void>;
  saveLabel?: string;
  saving?: boolean;
}

type ViewerStatus = "idle" | "connecting" | "live" | "closed" | "error";

const STATUS_LABELS: Record<ViewerStatus, string> = {
  idle: "Waiting",
  connecting: "Connecting",
  live: "Live",
  closed: "Closed",
  error: "Unavailable",
};

const MAX_RETRIES = 6;

function errorText(error: unknown, fallback: string): string {
  if (error && typeof error === "object" && "message" in error) {
    return String((error as { message: unknown }).message);
  }
  return fallback;
}

function modifierNames(event: {
  ctrlKey: boolean;
  altKey: boolean;
  metaKey: boolean;
  shiftKey: boolean;
}): string[] {
  const modifiers: string[] = [];
  if (event.ctrlKey) modifiers.push("Control");
  if (event.altKey) modifiers.push("Alt");
  if (event.metaKey) modifiers.push("Meta");
  if (event.shiftKey) modifiers.push("Shift");
  return modifiers;
}

function isModifierKey(key: string): boolean {
  return key === "Control" || key === "Alt" || key === "Meta" || key === "Shift";
}

function normalizeKey(key: string): string {
  if (key === " ") return "Space";
  if (key === "Spacebar") return "Space";
  if (key === "Esc") return "Escape";
  if (key === "Left") return "ArrowLeft";
  if (key === "Right") return "ArrowRight";
  if (key === "Up") return "ArrowUp";
  if (key === "Down") return "ArrowDown";
  return key;
}

function buttonName(button: number): "left" | "middle" | "right" {
  if (button === 1) return "middle";
  if (button === 2) return "right";
  return "left";
}

function clamp(value: number, low: number, high: number): number {
  return Math.max(low, Math.min(high, value));
}

export function LoginViewer({
  open,
  title = "Google sign-in",
  description,
  warning,
  preparing,
  issueTicket,
  onClose,
  onClosed,
  onSave,
  saveLabel = "I'm done - save session",
  saving = false,
}: LoginViewerProps) {
  const canvasRef = React.useRef<HTMLCanvasElement | null>(null);
  const surfaceRef = React.useRef<HTMLDivElement | null>(null);
  const wsRef = React.useRef<WebSocket | null>(null);
  const issueRef = React.useRef(issueTicket);
  const closedRef = React.useRef(onClosed);
  const statusRef = React.useRef<ViewerStatus>("idle");
  const sizeRef = React.useRef({ width: 1280, height: 900 });
  const drawingRef = React.useRef(false);
  const pendingFrameRef = React.useRef<Blob | null>(null);
  const heldKeysRef = React.useRef<Set<string>>(new Set());
  const moveFrameRef = React.useRef<number | null>(null);
  const movePointRef = React.useRef<{ x: number; y: number } | null>(null);

  const [status, setStatus] = React.useState<ViewerStatus>("idle");
  const [error, setError] = React.useState<string | null>(null);
  const [headless, setHeadless] = React.useState(false);
  const [serverWarning, setServerWarning] = React.useState<string | null>(null);
  const [frameSize, setFrameSize] = React.useState({ width: 1280, height: 900 });
  const [retryNonce, setRetryNonce] = React.useState(0);

  React.useEffect(() => {
    issueRef.current = issueTicket;
  }, [issueTicket]);
  React.useEffect(() => {
    closedRef.current = onClosed;
  }, [onClosed]);

  const updateStatus = React.useCallback((next: ViewerStatus) => {
    statusRef.current = next;
    setStatus(next);
  }, []);

  const send = React.useCallback((payload: unknown) => {
    const socket = wsRef.current;
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify(payload));
    }
  }, []);

  /** Draw a frame, coalescing frames that arrive while a bitmap decodes. */
  const drawFrame = React.useCallback(async (blob: Blob) => {
    if (drawingRef.current) {
      pendingFrameRef.current = blob;
      return;
    }
    drawingRef.current = true;
    try {
      const bitmap = await createImageBitmap(blob);
      const canvas = canvasRef.current;
      if (canvas) {
        if (canvas.width !== bitmap.width) canvas.width = bitmap.width;
        if (canvas.height !== bitmap.height) canvas.height = bitmap.height;
        const context = canvas.getContext("2d");
        context?.drawImage(bitmap, 0, 0);
        sizeRef.current = { width: bitmap.width, height: bitmap.height };
        setFrameSize({ width: bitmap.width, height: bitmap.height });
      }
      bitmap.close();
    } catch {
      /* an incomplete JPEG simply waits for the next frame */
    } finally {
      drawingRef.current = false;
      const next = pendingFrameRef.current;
      pendingFrameRef.current = null;
      if (next) void drawFrame(next);
    }
  }, []);

  React.useEffect(() => {
    if (!open) {
      updateStatus("idle");
      return;
    }

    let cancelled = false;
    let stopped = false;
    let socket: WebSocket | null = null;
    let timer: number | null = null;
    let retries = 0;

    setError(null);
    setHeadless(false);
    setServerWarning(null);

    const schedule = (delay: number) => {
      if (cancelled || stopped) return;
      if (retries >= MAX_RETRIES) {
        setError(
          "The live login view could not be reached. Check the backend and try again.",
        );
        updateStatus("error");
        return;
      }
      retries += 1;
      updateStatus("connecting");
      timer = window.setTimeout(() => void connect(), delay);
    };

    const connect = async () => {
      if (cancelled) return;
      updateStatus("connecting");
      setError(null);

      let url: string;
      try {
        const ticket = await issueRef.current();
        url = ticket.url;
      } catch (err) {
        if (cancelled) return;
        const code = (err as { status?: number } | null)?.status;
        setError(errorText(err, "The login view could not be opened."));
        if (code === 409) {
          // No open window (or a native one): retrying cannot help.
          stopped = true;
          updateStatus("error");
          return;
        }
        schedule(800);
        return;
      }
      if (cancelled) return;

      const ws = new WebSocket(url);
      socket = ws;
      wsRef.current = ws;
      ws.binaryType = "blob";

      ws.onopen = () => {
        if (cancelled) return;
        retries = 0;
        updateStatus("live");
      };

      ws.onmessage = (event: MessageEvent) => {
        if (cancelled) return;
        if (typeof event.data === "string") {
          let message: Record<string, unknown>;
          try {
            message = JSON.parse(event.data) as Record<string, unknown>;
          } catch {
            return;
          }
          const type = String(message.type ?? "");
          if (type === "ready") {
            const width = Number(message.width) || sizeRef.current.width;
            const height = Number(message.height) || sizeRef.current.height;
            sizeRef.current = { width, height };
            setFrameSize({ width, height });
            setHeadless(Boolean(message.headless));
            setServerWarning(
              typeof message.warning === "string" ? message.warning : null,
            );
            updateStatus("live");
          } else if (type === "ping") {
            send({ type: "ping" });
          } else if (type === "closed") {
            stopped = true;
            updateStatus("closed");
            closedRef.current?.();
          } else if (type === "error") {
            stopped = true;
            setError(
              typeof message.message === "string"
                ? message.message
                : "The live login view is unavailable.",
            );
            updateStatus("error");
          }
          return;
        }
        if (event.data instanceof Blob) {
          void drawFrame(event.data);
        }
      };

      ws.onclose = (event: CloseEvent) => {
        if (wsRef.current === ws) wsRef.current = null;
        if (cancelled || stopped) return;
        if (event.code === 4404) {
          stopped = true;
          setError("The login window is already closed.");
          updateStatus("error");
          return;
        }
        // 4401 (expired / reused ticket) is expected after a reconnect.
        schedule(700);
      };

      ws.onerror = () => {
        /* `onclose` follows and decides whether to retry */
      };
    };

    void connect();

    return () => {
      cancelled = true;
      stopped = true;
      if (timer !== null) window.clearTimeout(timer);
      if (moveFrameRef.current !== null) {
        window.cancelAnimationFrame(moveFrameRef.current);
        moveFrameRef.current = null;
      }
      const current = socket;
      socket = null;
      if (wsRef.current === current) wsRef.current = null;
      if (current) {
        try {
          current.close();
        } catch {
          /* already closed */
        }
      }
      heldKeysRef.current.clear();
    };
    // `connect` is intentionally recreated by the effect; the ticket function
    // is read through a ref so a new lambda in the parent does not reconnect.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, retryNonce, drawFrame, send, updateStatus]);

  const mapPoint = React.useCallback((clientX: number, clientY: number) => {
    const canvas = canvasRef.current;
    if (!canvas) return null;
    const rect = canvas.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return null;
    const { width, height } = sizeRef.current;
    return {
      x: clamp(((clientX - rect.left) / rect.width) * width, 0, width - 1),
      y: clamp(((clientY - rect.top) / rect.height) * height, 0, height - 1),
    };
  }, []);

  // Wheel needs a non-passive listener; React registers wheel as passive.
  React.useEffect(() => {
    if (!open) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      if (statusRef.current !== "live") return;
      const point = mapPoint(event.clientX, event.clientY);
      if (!point) return;
      send({
        type: "mouse",
        action: "wheel",
        ...point,
        dx: event.deltaX,
        dy: event.deltaY,
      });
    };
    canvas.addEventListener("wheel", onWheel, { passive: false });
    return () => canvas.removeEventListener("wheel", onWheel);
  }, [open, mapPoint, send]);

  const focusSurface = React.useCallback(() => {
    surfaceRef.current?.focus({ preventScroll: true });
  }, []);

  const queueMove = React.useCallback(
    (point: { x: number; y: number }) => {
      movePointRef.current = point;
      if (moveFrameRef.current !== null) return;
      moveFrameRef.current = window.requestAnimationFrame(() => {
        moveFrameRef.current = null;
        const pending = movePointRef.current;
        if (pending && statusRef.current === "live") {
          send({ type: "mouse", action: "move", ...pending });
        }
      });
    },
    [send],
  );

  const onPointerDown = (event: React.PointerEvent<HTMLCanvasElement>) => {
    focusSurface();
    if (statusRef.current !== "live") return;
    event.currentTarget.setPointerCapture?.(event.pointerId);
    const point = mapPoint(event.clientX, event.clientY);
    if (!point) return;
    send({
      type: "mouse",
      action: "down",
      button: buttonName(event.button),
      ...point,
    });
  };

  const onPointerMove = (event: React.PointerEvent<HTMLCanvasElement>) => {
    if (statusRef.current !== "live") return;
    const point = mapPoint(event.clientX, event.clientY);
    if (point) queueMove(point);
  };

  const onPointerUp = (event: React.PointerEvent<HTMLCanvasElement>) => {
    if (statusRef.current !== "live") return;
    const point = mapPoint(event.clientX, event.clientY);
    if (!point) return;
    send({
      type: "mouse",
      action: "up",
      button: buttonName(event.button),
      ...point,
    });
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (statusRef.current !== "live") return;
    const key = event.key;
    if (!key || key === "Unidentified" || key === "Dead" || key === "Process") {
      return;
    }
    // Let the paste event carry the text (the clipboard is not readable here).
    if ((event.metaKey || event.ctrlKey) && key.toLowerCase() === "v") return;
    event.preventDefault();

    if (isModifierKey(key)) {
      send({
        type: "key",
        action: "down",
        key,
        modifiers: modifierNames(event),
      });
      return;
    }
    if (
      !event.ctrlKey &&
      !event.metaKey &&
      !event.altKey &&
      Array.from(key).length === 1
    ) {
      send({ type: "text", text: key });
      return;
    }
    if (event.repeat) return;
    heldKeysRef.current.add(key);
    send({
      type: "key",
      action: "down",
      key: normalizeKey(key),
      modifiers: modifierNames(event),
    });
  };

  const onKeyUp = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (statusRef.current !== "live") return;
    const key = event.key;
    if (!key) return;
    if (isModifierKey(key) || heldKeysRef.current.has(key)) {
      event.preventDefault();
      heldKeysRef.current.delete(key);
      send({
        type: "key",
        action: "up",
        key: normalizeKey(key),
        modifiers: modifierNames(event),
      });
    }
  };

  const onBlur = () => {
    for (const key of heldKeysRef.current) {
      send({ type: "key", action: "up", key: normalizeKey(key), modifiers: [] });
    }
    heldKeysRef.current.clear();
    for (const modifier of ["Control", "Alt", "Meta", "Shift"]) {
      send({ type: "key", action: "up", key: modifier, modifiers: [] });
    }
  };

  const onPaste = (event: React.ClipboardEvent<HTMLDivElement>) => {
    const text = event.clipboardData?.getData("text");
    if (!text) return;
    event.preventDefault();
    send({ type: "text", text });
  };

  if (!open) return null;

  const warningText = warning || serverWarning;
  const live = status === "live";

  return (
    <div
      className="fixed inset-0 z-[70] flex items-center justify-center bg-slate-950/60 p-3"
      role="dialog"
      aria-modal="true"
      aria-label={typeof title === "string" ? title : "Login browser"}
    >
      <div className="flex max-h-[96vh] w-full max-w-5xl flex-col overflow-hidden rounded-lg border border-line bg-surface shadow-pop">
        <div className="flex items-start justify-between gap-3 border-b border-line px-4 py-2.5">
          <div className="min-w-0">
            <h2 className="text-sm font-semibold text-content">{title}</h2>
            {description ? (
              <p className="mt-0.5 text-[11px] text-content-muted">{description}</p>
            ) : null}
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <Badge tone={live ? "success" : status === "error" ? "danger" : "neutral"}>
              {preparing ? "Preparing" : STATUS_LABELS[status]}
            </Badge>
            <IconButton label="Close the login view" onClick={onClose}>
              ✕
            </IconButton>
          </div>
        </div>

        {warningText ? (
          <div className="px-4 pt-3">
            <Alert tone="warning" title="Headless login browser">
              {warningText}
            </Alert>
          </div>
        ) : null}

        <div className="flex flex-wrap items-center gap-1 border-b border-line px-3 py-1.5">
          <Button
            size="sm"
            variant="ghost"
            disabled={!live}
            onClick={() => send({ type: "navigate", action: "back" })}
          >
            ← Back
          </Button>
          <Button
            size="sm"
            variant="ghost"
            disabled={!live}
            onClick={() => send({ type: "navigate", action: "forward" })}
          >
            Forward →
          </Button>
          <Button
            size="sm"
            variant="ghost"
            disabled={!live}
            onClick={() => send({ type: "navigate", action: "reload" })}
          >
            Reload
          </Button>
          <span className="ml-auto hidden text-[11px] text-content-subtle sm:block">
            Click the view, then use the keyboard. Ctrl/Cmd+V pastes.
          </span>
        </div>

        <div
          ref={surfaceRef}
          tabIndex={0}
          onKeyDown={onKeyDown}
          onKeyUp={onKeyUp}
          onBlur={onBlur}
          onPaste={onPaste}
          className="relative flex max-h-[72vh] min-h-[280px] flex-1 items-center justify-center overflow-auto bg-slate-950 p-2 focus:outline-none"
        >
          <canvas
            ref={canvasRef}
            width={frameSize.width}
            height={frameSize.height}
            className={cn(
              "block h-auto max-h-[70vh] w-auto max-w-full touch-none select-none rounded-sm bg-black",
              !live && "opacity-60",
            )}
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onPointerCancel={onPointerUp}
            onContextMenu={(event) => event.preventDefault()}
          />

          {preparing ? (
            <div className="absolute inset-0 flex items-start justify-center overflow-auto bg-slate-950/90 p-3 sm:p-6">
              <div className="w-full max-w-lg rounded-lg border border-line bg-surface p-4 shadow-pop">
                <p className="mb-2 text-sm font-semibold text-content">
                  Preparing the login browser…
                </p>
                <LoginProgress progress={preparing} />
              </div>
            </div>
          ) : status === "connecting" || status === "idle" ? (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-slate-950/70 text-xs text-slate-200">
              <Spinner />
              <span>{headless ? "Starting the headless browser…" : "Connecting to the login browser…"}</span>
            </div>
          ) : null}

          {status === "error" ? (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-slate-950/80 p-6 text-center text-xs text-slate-200">
              <p className="max-w-md">{error ?? "The live login view is unavailable."}</p>
              <div className="flex gap-2">
                <Button size="sm" onClick={() => setRetryNonce((value) => value + 1)}>
                  Retry
                </Button>
                <Button size="sm" variant="ghost" onClick={onClose}>
                  Close
                </Button>
              </div>
            </div>
          ) : null}

          {status === "closed" ? (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-slate-950/80 text-xs text-slate-200">
              <span>The login browser is closed.</span>
              <Button size="sm" variant="ghost" onClick={onClose}>
                Close
              </Button>
            </div>
          ) : null}
        </div>

        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line px-4 py-2.5">
          <p className="text-[11px] text-content-muted">
            Passwords and two factor codes are typed by you, never filled by the app.
          </p>
          <div className="flex flex-wrap items-center gap-2">
            {onSave ? (
              <Button size="sm" loading={saving} disabled={!live || Boolean(preparing)} onClick={() => void onSave()}>
                {saveLabel}
              </Button>
            ) : null}
            <Button size="sm" variant="ghost" onClick={onClose}>
              Cancel
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
