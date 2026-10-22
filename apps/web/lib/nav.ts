/** Primary application navigation, in the order required by the product spec. */
export interface NavItem {
  href: string;
  label: string;
  icon: string;
  group: "workspace" | "operations" | "system";
}

export const NAV_ITEMS: NavItem[] = [
  // Workspace: your projects, the sites they work on and where they come from.
  { href: "/", label: "Overview", icon: "◧", group: "workspace" },
  { href: "/projects", label: "Projects", icon: "▤", group: "workspace" },
  { href: "/discovery", label: "Discovery", icon: "◎", group: "workspace" },
  { href: "/registry", label: "Opportunities", icon: "▦", group: "workspace" },
  { href: "/websites", label: "Websites", icon: "▥", group: "workspace" },
  // Operations: what the system does with them.
  { href: "/queue", label: "Queue", icon: "≣", group: "operations" },
  { href: "/automation", label: "Automation", icon: "◈", group: "operations" },
  { href: "/verification", label: "Verification", icon: "✓", group: "operations" },
  { href: "/reports", label: "Reports", icon: "▧", group: "operations" },
  { href: "/imports", label: "Opportunity import", icon: "↥", group: "operations" },
  // System: the workspace itself.
  { href: "/devices", label: "Devices", icon: "⌸", group: "system" },
  { href: "/activity", label: "Activity", icon: "≡", group: "system" },
  { href: "/recycle-bin", label: "Recycle bin", icon: "⌫", group: "system" },
  { href: "/settings", label: "Settings", icon: "⚙", group: "system" },
];

export const NAV_GROUPS: Array<{ id: NavItem["group"]; label: string }> = [
  { id: "workspace", label: "Workspace" },
  { id: "operations", label: "Operations" },
  { id: "system", label: "System" },
];

/** Resolves the page title for a pathname. */
export function navTitleFor(pathname: string): string {
  if (pathname === "/") return "Overview";
  const match = NAV_ITEMS.find((item) => item.href !== "/" && pathname.startsWith(item.href));
  return match?.label ?? "Overview";
}
