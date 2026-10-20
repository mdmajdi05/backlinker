"use client";

import * as React from "react";
import { Spinner } from "@autobacklinker/ui";

export function FullPageLoader({ label = "Loading workspace…" }: { label?: string }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-surface-sunken">
      <div className="flex items-center gap-2 text-sm text-content-muted">
        <Spinner />
        <span>{label}</span>
      </div>
    </div>
  );
}
