"use client";

import * as React from "react";
import { formatNumber } from "@/lib/format";

export interface BarItem {
  label: string;
  value: number;
  hint?: string;
}

/**
 * Horizontal bar rows computed from real counts (no charts, no fake data).
 */
export function BarList({
  items,
  emptyLabel = "No data",
}: {
  items: BarItem[];
  emptyLabel?: string;
}) {
  if (items.length === 0) {
    return <p className="px-1 py-3 text-xs text-content-subtle">{emptyLabel}</p>;
  }
  const max = Math.max(1, ...items.map((item) => item.value));
  return (
    <div className="space-y-2">
      {items.map((item) => {
        const pct = Math.max(0, Math.min(100, (item.value / max) * 100));
        return (
          <div key={item.label} className="flex items-center gap-3">
            <span
              className="w-44 shrink-0 truncate text-xs text-content-muted"
              title={item.hint ?? item.label}
            >
              {item.hint ?? item.label}
            </span>
            <div className="h-2 min-w-0 flex-1 overflow-hidden rounded-full bg-surface-sunken">
              <div
                className="h-full rounded-full bg-accent transition-[width] duration-300"
                style={{ width: `${pct}%` }}
              />
            </div>
            <span className="w-12 shrink-0 text-right text-xs tabular-nums text-content">
              {formatNumber(item.value)}
            </span>
          </div>
        );
      })}
    </div>
  );
}
