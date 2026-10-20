"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { NAV_GROUPS, NAV_ITEMS } from "@/lib/nav";
import { cn } from "@autobacklinker/ui";

export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();

  const isActive = (href: string) => {
    if (href === "/") return pathname === "/";
    return pathname === href || pathname.startsWith(`${href}/`);
  };

  return (
    <nav className="flex h-full flex-col gap-4 overflow-y-auto px-3 py-4" aria-label="Main">
      <div className="flex items-center gap-2 px-2">
        <span
          aria-hidden
          className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent text-sm font-bold text-accent-fg"
        >
          AB
        </span>
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-content">Auto Backlinker</p>
          <p className="truncate text-[11px] text-content-subtle">Automation workspace</p>
        </div>
      </div>

      {NAV_GROUPS.map((group) => {
        const items = NAV_ITEMS.filter((item) => item.group === group.id);
        if (items.length === 0) return null;
        return (
          <div key={group.id} className="space-y-1">
            <p className="px-2.5 text-[10px] font-semibold uppercase tracking-wider text-content-subtle">
              {group.label}
            </p>
            {items.map((item) => {
              const active = isActive(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  data-active={active}
                  aria-current={active ? "page" : undefined}
                  className={cn("abk-nav-link", active && "text-accent")}
                  onClick={onNavigate}
                >
                  <span aria-hidden className="w-4 text-center text-xs opacity-80">
                    {item.icon}
                  </span>
                  <span className="truncate">{item.label}</span>
                </Link>
              );
            })}
          </div>
        );
      })}
    </nav>
  );
}
