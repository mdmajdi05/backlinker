/** Navigation model - mirrors the web client, in the order of the daily workflow. */

export type RouteId =
  | "overview"
  | "projects"
  | "discovery"
  | "registry"
  | "websites"
  | "queue"
  | "automation"
  | "verification"
  | "reports"
  | "recycle-bin"
  | "imports"
  | "integrations"
  | "devices"
  | "activity"
  | "settings";

export interface NavEntry {
  id: RouteId;
  label: string;
  description: string;
  group: "workspace" | "operations" | "system" | "advanced";
  /** Routes that are not part of the desktop build yet. */
  implemented: boolean;
  /**
   * Optional glyph of the shared navigation model. The desktop shell renders
   * its SVG icons by route id and falls back to this glyph when there is none.
   */
  icon?: string;
}

export const NAV_ENTRIES: NavEntry[] = [
  {
    id: "overview",
    label: "Dashboard",
    description: "Live metrics and activity of this installation.",
    group: "workspace",
    implemented: true,
  },
  {
    id: "projects",
    label: "My projects",
    description: "One project per website, with its own details and websites.",
    group: "workspace",
    implemented: true,
  },
  {
    id: "websites",
    label: "Backlink websites",
    description: "The central list of websites where backlinks can be made.",
    group: "workspace",
    implemented: true,
  },
  {
    id: "queue",
    label: "Task queue",
    description: "Every queued, running and paused task.",
    group: "operations",
    implemented: true,
  },
  {
    id: "reports",
    label: "Reports",
    description: "Results and downloadable reports.",
    group: "operations",
    implemented: true,
  },
  {
    id: "recycle-bin",
    label: "Recycle bin",
    description:
      "Deleted projects, websites, business profiles and opportunities wait here until they are restored or deleted forever.",
    group: "system",
    implemented: true,
    icon: "⌫",
  },
  {
    id: "settings",
    label: "Settings",
    description: "Local backend, optional hosted backend, notifications and theme.",
    group: "system",
    implemented: true,
  },
  {
    id: "discovery",
    label: "Find new websites",
    description: "Provider driven discovery of new backlink websites.",
    group: "advanced",
    implemented: true,
  },
  {
    id: "verification",
    label: "All backlinks",
    description: "Every backlink record and its live verification.",
    group: "advanced",
    implemented: true,
  },
  {
    id: "automation",
    label: "Automation rules",
    description: "Adapters and automation settings.",
    group: "advanced",
    implemented: true,
  },
  {
    id: "integrations",
    label: "API keys & integrations",
    description: "API keys for discovery and AI, plus submission adapters.",
    group: "advanced",
    implemented: true,
  },
  {
    id: "imports",
    label: "Import old report",
    description: "Import an Excel/CSV report from this machine.",
    group: "advanced",
    implemented: true,
  },
  {
    id: "devices",
    label: "Devices",
    description: "Registered devices and the local agent.",
    group: "advanced",
    implemented: true,
  },
  {
    id: "activity",
    label: "Activity log",
    description: "Persisted event log of the backend.",
    group: "advanced",
    implemented: true,
  },
];

export const NAV_GROUPS: Array<{
  id: NavEntry["group"];
  label: string;
}> = [
  { id: "workspace", label: "Workspace" },
  { id: "operations", label: "Work" },
  { id: "system", label: "System" },
  { id: "advanced", label: "More tools" },
];

export function navEntry(id: string): NavEntry | undefined {
  return NAV_ENTRIES.find((entry) => entry.id === id);
}
