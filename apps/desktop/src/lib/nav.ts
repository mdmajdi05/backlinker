/** Navigation model - mirrors the web client, desktop conventions applied. */

export type RouteId =
  | "overview"
  | "projects"
  | "discovery"
  | "registry"
  | "queue"
  | "automation"
  | "verification"
  | "reports"
  | "imports"
  | "integrations"
  | "devices"
  | "activity"
  | "settings";

export interface NavEntry {
  id: RouteId;
  label: string;
  description: string;
  group: "workspace" | "operations" | "system";
  /** Routes that are not part of the desktop build yet. */
  implemented: boolean;
}

export const NAV_ENTRIES: NavEntry[] = [
  {
    id: "overview",
    label: "Overview",
    description: "Live metrics and activity of this installation.",
    group: "workspace",
    implemented: true,
  },
  {
    id: "projects",
    label: "Projects",
    description: "Campaigns, targets and their execution settings.",
    group: "workspace",
    implemented: true,
  },
  {
    id: "discovery",
    label: "Discovery",
    description: "Provider driven opportunity discovery.",
    group: "workspace",
    implemented: false,
  },
  {
    id: "registry",
    label: "Registry",
    description: "Every discovered opportunity and its review state.",
    group: "workspace",
    implemented: true,
  },
  {
    id: "queue",
    label: "Queue",
    description: "Tasks, leases and local execution controls.",
    group: "operations",
    implemented: true,
  },
  {
    id: "automation",
    label: "Automation",
    description: "Adapters and automation settings.",
    group: "operations",
    implemented: true,
  },
  {
    id: "verification",
    label: "Verification",
    description: "Backlink records and live verification runs.",
    group: "operations",
    implemented: true,
  },
  {
    id: "reports",
    label: "Reports",
    description: "Generated exports and downloads.",
    group: "operations",
    implemented: true,
  },
  {
    id: "imports",
    label: "Imports",
    description: "Import Excel/CSV files from this machine.",
    group: "operations",
    implemented: true,
  },
  {
    id: "integrations",
    label: "Integrations",
    description: "Third party credentials and webhooks.",
    group: "system",
    implemented: false,
  },
  {
    id: "devices",
    label: "Devices",
    description: "Registered devices and the local agent.",
    group: "system",
    implemented: true,
  },
  {
    id: "activity",
    label: "Activity",
    description: "Persisted event log of the backend.",
    group: "system",
    implemented: true,
  },
  {
    id: "settings",
    label: "Settings",
    description: "Local backend, notifications, theme and cloud sync.",
    group: "system",
    implemented: true,
  },
];

export const NAV_GROUPS: Array<{
  id: NavEntry["group"];
  label: string;
}> = [
  { id: "workspace", label: "Workspace" },
  { id: "operations", label: "Operations" },
  { id: "system", label: "System" },
];

export function navEntry(id: string): NavEntry | undefined {
  return NAV_ENTRIES.find((entry) => entry.id === id);
}
