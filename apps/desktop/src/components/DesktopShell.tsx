import * as React from "react";
import { Badge, Button, IconButton, Tooltip } from "@autobacklinker/ui";
import { Icon, type IconName } from "./icons";
import { NAV_ENTRIES, NAV_GROUPS, navEntry, type NavEntry } from "../lib/nav";
import { useBackend } from "../lib/backendState";
import { useTheme } from "../lib/theme";
import { useNotifications } from "../lib/notifications";
import { useAuth } from "../lib/auth";
import { useRoute } from "../lib/router";
import { getApiToken, getLocalToken } from "../lib/api";
import { OverviewPage } from "../pages/OverviewPage";
import { ProjectsPage } from "../pages/ProjectsPage";
import { ProjectDetailPage } from "../pages/ProjectDetailPage";
import { DiscoveryPage } from "../pages/DiscoveryPage";
import { IntegrationsPage } from "../pages/IntegrationsPage";
import { OnboardingPage } from "../pages/OnboardingPage";
import { RegistryPage } from "../pages/RegistryPage";
import { WebsiteListPage } from "../pages/WebsiteListPage";
import { QueuePage } from "../pages/QueuePage";
import { AutomationPage } from "../pages/AutomationPage";
import { AutomationPanel } from "./AutomationPanel";
import { VerificationPage } from "../pages/VerificationPage";
import { ReportsPage } from "../pages/ReportsPage";
import { RecycleBinPage } from "../pages/RecycleBinPage";
import { ImportsPage } from "../pages/ImportsPage";
import { DevicesPage } from "../pages/DevicesPage";
import { ActivityPage } from "../pages/ActivityPage";
import { SettingsPage } from "../pages/SettingsPage";
import { NotImplementedPage } from "../pages/NotImplementedPage";
import { LoadingBlock } from "./common";

interface ShellEntry {
  id: string;
  label: string;
  description: string;
  group: NavEntry["group"];
  icon: IconName | { glyph: string };
}

/**
 * Entries of the navigation model that the desktop build adds itself - the
 * shared navigation model is owned by the web client.
 */
const EXTRA_ENTRIES: ShellEntry[] = [
  {
    id: "onboarding",
    label: "Setup",
    description: "Business profile, SEO configuration and the first project.",
    group: "workspace",
    icon: "play",
  },
];

/**
 * Routes that the desktop build implements even though the shared navigation
 * model still lists them as pending.
 */
const IMPLEMENTED_ROUTES = new Set(["discovery", "integrations"]);

function shellEntries(): ShellEntry[] {
  const entries: ShellEntry[] = NAV_ENTRIES.map((entry) => ({
    id: entry.id,
    label: entry.label,
    description: entry.description,
    group: entry.group,
    // Shared navigation entries may carry a text glyph (e.g. the recycle
    // bin); the desktop icons stay the default everywhere else.
    icon: entry.icon ? { glyph: entry.icon } : (entry.id as IconName),
  }));
  return [...entries, ...EXTRA_ENTRIES];
}

/** The route without its query string - the hash router keeps `kind` there. */
function routePath(route: string): string {
  return route.split("?")[0] ?? route;
}

function isActive(route: string, id: string): boolean {
  const path = routePath(route);
  // The review tab is part of website discovery.
  if (id === "discovery" && path === "registry") return true;
  return path === id || path.startsWith(`${id}/`);
}

function NavIcon({ icon }: { icon: ShellEntry["icon"] }) {
  if (typeof icon === "string") return <Icon name={icon} />;
  return (
    <span
      aria-hidden
      className="flex h-4 w-4 items-center justify-center text-sm leading-none"
    >
      {icon.glyph}
    </span>
  );
}

/**
 * The desktop client needs a session before it may talk to the backend: the
 * bundled sidecar authenticates with a machine token, the browser preview
 * signs the local account in.  A page that fires its requests before the
 * session exists would only receive 401 - therefore the shell waits for it.
 */
function useSessionReady(): boolean {
  const [ready, setReady] = React.useState<boolean>(
    () => Boolean(getApiToken() || getLocalToken()),
  );

  React.useEffect(() => {
    if (ready) return;
    const timer = window.setInterval(() => {
      if (getApiToken() || getLocalToken()) setReady(true);
    }, 150);
    // The backend may be unreachable - the pages then show their own error
    // state instead of blocking the whole window.
    const timeout = window.setTimeout(() => setReady(true), 4000);
    return () => {
      window.clearInterval(timer);
      window.clearTimeout(timeout);
    };
  }, [ready]);

  return ready;
}

function Sidebar() {
  const [route, go] = useRoute();
  const { status, native } = useBackend();
  const entries = shellEntries();

  return (
    <aside className="flex h-full w-64 shrink-0 flex-col border-r border-line bg-surface">
      <div className="flex items-center gap-2 border-b border-line px-4 py-3">
        <div className="flex h-8 w-8 items-center justify-center rounded-md bg-accent text-accent-fg">
          <Icon name="automation" className="h-4 w-4" />
        </div>
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-content">
            Auto Backlinker
          </p>
          <p className="truncate text-[11px] text-content-subtle">
            Desktop workspace
          </p>
        </div>
      </div>

      <nav className="flex-1 overflow-y-auto px-2 py-3">
        {NAV_GROUPS.map((group) => (
          <div key={group.id} className="mb-4">
            <p className="px-2 pb-1 text-[10px] font-semibold uppercase tracking-wider text-content-subtle">
              {group.label}
            </p>
            <ul className="flex flex-col gap-0.5">
              {entries
                .filter((entry) => entry.group === group.id)
                .map((entry) => {
                  const active = isActive(route, entry.id);
                  const pending =
                    !IMPLEMENTED_ROUTES.has(entry.id) &&
                    navEntry(entry.id)?.implemented === false;
                  return (
                    <li key={entry.id}>
                      <button
                        onClick={() => go(entry.id)}
                        aria-current={active ? "page" : undefined}
                        className={
                          active
                            ? "flex w-full items-center gap-2 rounded-md bg-accent-soft px-2 py-1.5 text-left text-sm font-medium text-accent"
                            : "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm text-content-muted transition-colors hover:bg-surface-sunken hover:text-content"
                        }
                      >
                        <NavIcon icon={entry.icon} />
                        <span className="flex-1 truncate">{entry.label}</span>
                        {pending ? (
                          <span className="text-[10px] text-content-subtle">
                            soon
                          </span>
                        ) : null}
                      </button>
                    </li>
                  );
                })}
            </ul>
          </div>
        ))}
      </nav>

      <div className="border-t border-line px-3 py-2.5">
        <div className="flex items-center justify-between gap-2">
          <span className="text-[11px] text-content-subtle">Local backend</span>
          <BackendPill compact />
        </div>
        <p className="mt-1 truncate text-[11px] text-content-subtle">
          {native
            ? status?.dataDir ?? "Data directory unknown"
            : "Browser preview - native backend unavailable"}
        </p>
      </div>
    </aside>
  );
}

export function BackendPill({ compact = false }: { compact?: boolean }) {
  const { status, native, error } = useBackend();

  if (!native) {
    return (
      <Badge tone="neutral" className={compact ? "" : undefined}>
        Browser preview
      </Badge>
    );
  }
  if (!status) {
    return (
      <Badge tone="neutral" className={compact ? "" : undefined}>
        {error ? "Unavailable" : "Checking…"}
      </Badge>
    );
  }
  if (status.healthy) {
    return (
      <Badge tone="success" className={compact ? "" : undefined}>
        Running · {status.port}
      </Badge>
    );
  }
  if (status.running) {
    return (
      <Badge tone="warning" className={compact ? "" : undefined}>
        Starting…
      </Badge>
    );
  }
  return (
    <Badge tone="danger" className={compact ? "" : undefined}>
      Stopped
    </Badge>
  );
}

function routeHeadline(route: string): { title: string; description: string } {
  const path = routePath(route);
  if (path.startsWith("projects/")) {
    return {
      title: "Project",
      description: "Counters, execution settings and landing pages of one project.",
    };
  }
  // Reviewing discovered websites is the second step of "Find new websites".
  // The route exists for that step but is intentionally not a navigation item.
  if (path === "registry") {
    return {
      title: "Review found websites",
      description:
        "Approve, exclude or queue the websites a discovery run found.",
    };
  }
  const extra = EXTRA_ENTRIES.find((entry) => entry.id === path);
  if (extra) {
    return { title: extra.label, description: extra.description };
  }
  const entry = navEntry(path);
  return {
    title: entry?.label ?? "Overview",
    description: entry?.description ?? "",
  };
}

function TopBar() {
  const [route] = useRoute();
  const { resolved, toggle } = useTheme();
  const { enabled, supported, setEnabled } = useNotifications();
  const { user, mode, logout } = useAuth();
  const headline = routeHeadline(route);

  return (
    <header className="flex h-14 shrink-0 items-center justify-between gap-4 border-b border-line bg-surface px-5">
      <div className="min-w-0">
        <h1 className="truncate text-sm font-semibold text-content">
          {headline.title}
        </h1>
        <p className="truncate text-xs text-content-muted">
          {headline.description}
        </p>
      </div>

      <div className="flex items-center gap-2">
        <BackendPill />

        {supported ? (
          <Tooltip
            label={
              enabled
                ? "Disable native notifications"
                : "Enable native notifications"
            }
          >
            <IconButton
              label="Native notifications"
              onClick={() => setEnabled(!enabled)}
              className={enabled ? "text-accent" : undefined}
            >
              <Icon name="bell" />
            </IconButton>
          </Tooltip>
        ) : null}

        <Tooltip
          label={resolved === "dark" ? "Switch to light theme" : "Switch to dark theme"}
        >
          <IconButton label="Toggle theme" onClick={toggle}>
            <Icon name={resolved === "dark" ? "sun" : "moon"} />
          </IconButton>
        </Tooltip>

        <div className="flex items-center gap-2 border-l border-line pl-3">
          <div className="text-right">
            <p className="text-xs font-medium text-content">
              {user?.name ?? (mode === "local" ? "Local session" : "Signed out")}
            </p>
            <p className="text-[11px] text-content-subtle">
              {mode === "local" ? "This device" : (user?.email ?? "")}
            </p>
          </div>
          {mode === "cloud" ? (
            <Button size="sm" variant="outline" onClick={logout}>
              Sign out
            </Button>
          ) : null}
        </div>
      </div>
    </header>
  );
}

function renderRoute(route: string) {
  const path = routePath(route);
  if (path.startsWith("projects/")) {
    const projectId = path.slice("projects/".length).trim();
    if (projectId) return <ProjectDetailPage projectId={projectId} />;
  }

  switch (path) {
    case "overview":
      return <OverviewPage />;
    case "projects":
      return <ProjectsPage />;
    case "discovery":
      return <DiscoveryPage />;
    case "registry":
      return <RegistryPage />;
    case "websites":
      return <WebsiteListPage />;
    case "queue":
      return <QueuePage />;
    case "automation":
      return (
        <div className="flex flex-col gap-4">
          <AutomationPage />
          <AutomationPanel />
        </div>
      );
    case "verification":
      return <VerificationPage />;
    case "reports":
      return <ReportsPage />;
    case "recycle-bin":
      return <RecycleBinPage />;
    case "imports":
      return <ImportsPage />;
    case "integrations":
      return <IntegrationsPage />;
    case "devices":
      return <DevicesPage />;
    case "activity":
      return <ActivityPage />;
    case "settings":
      return <SettingsPage />;
    case "onboarding":
      return <OnboardingPage />;
    default:
      return <NotImplementedPage route={path} />;
  }
}

export function DesktopShell() {
  const [route] = useRoute();
  const ready = useSessionReady();

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-surface-sunken text-content">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar />
        <main className="flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-[1400px] p-5">
            {ready ? renderRoute(route) : <LoadingBlock rows={5} />}
          </div>
        </main>
      </div>
    </div>
  );
}
