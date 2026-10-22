/** Primary application navigation, in the order required by the product spec. */
export interface NavItem {
  href: string;
  label: string;
  icon: string;
  group: "workspace" | "operations" | "system";
}

export const NAV_ITEMS: NavItem[] = [
  { href: "/", label: "Overview", icon: "◧", group: "workspace" },
  { href: "/projects", label: "Projects", icon: "▤", group: "workspace" },
  { href: "/discovery", label: "Opportunity Discovery", icon: "◎", group: "workspace" },
  { href: "/registry", label: "Website Registry", icon: "▦", group: "workspace" },
  { href: "/websites", label: "Website list", icon: "▥", group: "workspace" },
  { href: "/queue", label: "Backlink Queue", icon: "≣", group: "operations" },
  { href: "/automation", label: "Live Automation", icon: "◈", group: "operations" },
  { href: "/verification", label: "Verification", icon: "✓", group: "operations" },
  { href: "/reports", label: "Reports & Exports", icon: "▧", group: "operations" },
  { href: "/recycle-bin", label: "Recycle bin", icon: "⌫", group: "operations" },
  { href: "/imports", label: "Import Center", icon: "↥", group: "operations" },
  { href: "/integrations", label: "Integrations", icon: "⚯", group: "system" },
  { href: "/devices", label: "Devices & Agents", icon: "⌸", group: "system" },
  { href: "/activity", label: "Activity Logs", icon: "≡", group: "system" },
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
