"use client";

import * as React from "react";
import { usePathname } from "next/navigation";
import { Badge, Button, IconButton, Tooltip } from "@autobacklinker/ui";
import { useAuth } from "@/lib/auth";
import { useStorage } from "@/lib/storage";
import { useTheme } from "@/lib/theme";
import { navTitleFor } from "@/lib/nav";
import { STORAGE_MODE_LABELS } from "@/lib/constants";

const MODE_TONES: Record<string, "info" | "accent" | "success"> = {
  LOCAL: "info",
  CLOUD: "accent",
  HYBRID: "success",
};

export function TopBar() {
  const pathname = usePathname();
  const { user, logout } = useAuth();
  const { status, error, loading, connected } = useStorage();
  const { resolved, toggle } = useTheme();
  const [menuOpen, setMenuOpen] = React.useState(false);
  const menuRef = React.useRef<HTMLDivElement | null>(null);

  React.useEffect(() => {
    if (!menuOpen) return;
    const onClick = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setMenuOpen(false);
      }
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMenuOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [menuOpen]);

  const title = navTitleFor(pathname);
  const mode = status?.mode;
  const modeLabel = mode ? (STORAGE_MODE_LABELS[mode] ?? mode) : "Storage mode unknown";

  const connectionLabel = loading
    ? "Checking connection…"
    : error
      ? "Backend unreachable"
      : connected
        ? "Connected"
        : "Not connected";

  const connectionTone = loading
    ? "neutral"
    : error
      ? "danger"
      : connected
        ? "success"
        : "warning";

  return (
    <header className="flex h-14 shrink-0 items-center justify-between gap-3 border-b border-line bg-surface px-4">
      <h1 className="truncate text-sm font-semibold text-content">{title}</h1>

      <div className="flex items-center gap-2">
        <Tooltip
          label={
            mode
              ? `${modeLabel} · ${status?.database_type ?? "unknown"} · ${
                  status?.database_url_masked || "unknown url"
                }`
              : "Storage mode is reported by the backend at /api/v1/storage/status"
          }
        >
          <Badge tone={mode ? MODE_TONES[mode] ?? "neutral" : "neutral"}>{modeLabel}</Badge>
        </Tooltip>

        <Tooltip label={connectionLabel}>
          <Badge tone={connectionTone}>
            <span
              aria-hidden
              className={`mr-1 inline-block h-1.5 w-1.5 rounded-full ${
                connected ? "bg-success" : error ? "bg-danger" : "bg-content-subtle"
              }`}
            />
            {loading ? "Connecting" : error ? "Offline" : connected ? "Online" : "Degraded"}
          </Badge>
        </Tooltip>

        <Tooltip label={resolved === "dark" ? "Switch to light mode" : "Switch to dark mode"}>
          <IconButton
            label={resolved === "dark" ? "Switch to light mode" : "Switch to dark mode"}
            onClick={toggle}
          >
            {resolved === "dark" ? "☀" : "☾"}
          </IconButton>
        </Tooltip>

        <div className="relative" ref={menuRef}>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setMenuOpen((open) => !open)}
            aria-haspopup="menu"
            aria-expanded={menuOpen}
          >
            <span aria-hidden className="flex h-5 w-5 items-center justify-center rounded-full bg-accent-soft text-[10px] font-semibold text-accent">
              {(user?.name ?? user?.email ?? "?").slice(0, 1).toUpperCase()}
            </span>
            <span className="hidden max-w-[140px] truncate sm:inline">
              {user?.name ?? user?.email ?? "Account"}
            </span>
          </Button>

          {menuOpen ? (
            <div
              role="menu"
              className="absolute right-0 top-full z-40 mt-1 w-60 rounded-lg border border-line bg-surface p-1 shadow-pop"
            >
              <div className="px-2 py-2">
                <p className="truncate text-sm font-medium text-content">{user?.name ?? "Account"}</p>
                <p className="truncate text-xs text-content-muted">{user?.email ?? "—"}</p>
              </div>
              <div className="my-1 h-px bg-line" />
              <button
                role="menuitem"
                type="button"
                onClick={logout}
                className="w-full rounded-md px-2 py-1.5 text-left text-sm text-danger transition-colors hover:bg-danger-soft"
              >
                Sign out
              </button>
            </div>
          ) : null}
        </div>
      </div>
    </header>
  );
}
