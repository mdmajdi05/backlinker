/** Primary application navigation, in the order of the daily workflow. */
export interface NavItem {
  href: string;
  label: string;
  icon: string;
  group: "workspace" | "operations" | "system" | "advanced";
}

export const NAV_ITEMS: NavItem[] = [
  // The daily workflow: a project, its websites, the work and the result.
  { href: "/", label: "Dashboard", icon: "◧", group: "workspace" },
  { href: "/projects", label: "My projects", icon: "▤", group: "workspace" },
  { href: "/websites", label: "Backlink websites", icon: "▥", group: "workspace" },
  { href: "/queue", label: "Task queue", icon: "≣", group: "operations" },
  { href: "/reports", label: "Reports", icon: "▧", group: "operations" },
  // The workspace itself.
  { href: "/recycle-bin", label: "Recycle bin", icon: "⌫", group: "system" },
  { href: "/settings", label: "Settings", icon: "⚙", group: "system" },
  // Everything that is useful once in a while, kept out of the daily way.
  { href: "/discovery", label: "Find new websites", icon: "◎", group: "advanced" },
  { href: "/registry", label: "Review websites", icon: "▦", group: "advanced" },
  { href: "/verification", label: "All backlinks", icon: "✓", group: "advanced" },
  { href: "/automation", label: "Automation rules", icon: "◈", group: "advanced" },
  { href: "/imports", label: "Import old report", icon: "↥", group: "advanced" },
  { href: "/integrations", label: "API keys & integrations", icon: "⌘", group: "advanced" },
  { href: "/devices", label: "Devices", icon: "⌸", group: "advanced" },
  { href: "/activity", label: "Activity log", icon: "≡", group: "advanced" },
];

export const NAV_GROUPS: Array<{ id: NavItem["group"]; label: string }> = [
  { id: "workspace", label: "Workspace" },
  { id: "operations", label: "Work" },
  { id: "system", label: "System" },
  { id: "advanced", label: "More tools" },
];

/** Resolves the page title for a pathname. */
export function navTitleFor(pathname: string): string {
  if (pathname === "/") return "Dashboard";
  const match = NAV_ITEMS.find((item) => item.href !== "/" && pathname.startsWith(item.href));
  return match?.label ?? "Auto Backlinker";
}
