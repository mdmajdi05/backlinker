import { Badge, Button, IconButton, Tooltip } from "@autobacklinker/ui";
import { Icon, type IconName } from "./icons";
import { NAV_ENTRIES, NAV_GROUPS, navEntry, type NavEntry } from "../lib/nav";
import { useBackend } from "../lib/backendState";
import { useTheme } from "../lib/theme";
import { useNotifications } from "../lib/notifications";
import { useAuth } from "../lib/auth";
import { useRoute } from "../lib/router";
import { OverviewPage } from "../pages/OverviewPage";
import { ProjectsPage } from "../pages/ProjectsPage";
import { RegistryPage } from "../pages/RegistryPage";
import { QueuePage } from "../pages/QueuePage";
import { AutomationPage } from "../pages/AutomationPage";
import { VerificationPage } from "../pages/VerificationPage";
import { ReportsPage } from "../pages/ReportsPage";
import { ImportsPage } from "../pages/ImportsPage";
import { DevicesPage } from "../pages/DevicesPage";
import { ActivityPage } from "../pages/ActivityPage";
import { SettingsPage } from "../pages/SettingsPage";
import { NotImplementedPage } from "../pages/NotImplementedPage";

function iconFor(entry: NavEntry): IconName {
  return entry.id as IconName;
}

function Sidebar() {
  const [route, go] = useRoute();
  const { status, native } = useBackend();

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
              {NAV_ENTRIES.filter((entry) => entry.group === group.id).map(
                (entry) => {
                  const active = route === entry.id;
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
                        <Icon name={iconFor(entry)} />
                        <span className="flex-1 truncate">{entry.label}</span>
                        {!entry.implemented ? (
                          <span className="text-[10px] text-content-subtle">
                            soon
                          </span>
                        ) : null}
                      </button>
                    </li>
                  );
                },
              )}
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

function TopBar() {
  const [route] = useRoute();
  const entry = navEntry(route);
  const { resolved, toggle } = useTheme();
  const { enabled, supported, setEnabled } = useNotifications();
  const { user, mode, logout } = useAuth();

  return (
    <header className="flex h-14 shrink-0 items-center justify-between gap-4 border-b border-line bg-surface px-5">
      <div className="min-w-0">
        <h1 className="truncate text-sm font-semibold text-content">
          {entry?.label ?? "Overview"}
        </h1>
        <p className="truncate text-xs text-content-muted">
          {entry?.description ?? ""}
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
  switch (route) {
    case "overview":
      return <OverviewPage />;
    case "projects":
      return <ProjectsPage />;
    case "registry":
      return <RegistryPage />;
    case "queue":
      return <QueuePage />;
    case "automation":
      return <AutomationPage />;
    case "verification":
      return <VerificationPage />;
    case "reports":
      return <ReportsPage />;
    case "imports":
      return <ImportsPage />;
    case "devices":
      return <DevicesPage />;
    case "activity":
      return <ActivityPage />;
    case "settings":
      return <SettingsPage />;
    default:
      return <NotImplementedPage route={route} />;
  }
}

export function DesktopShell() {
  const [route] = useRoute();

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-surface-sunken text-content">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar />
        <main className="flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-[1400px] p-5">
            {renderRoute(route)}
          </div>
        </main>
      </div>
    </div>
  );
}
