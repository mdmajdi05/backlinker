"use client";

import * as React from "react";
import { Button } from "@autobacklinker/ui";

export function PageHeader({
  title,
  description,
  actions,
  children,
}: {
  title: string;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  children?: React.ReactNode;
}) {
  return (
    <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        <h1 className="text-lg font-semibold tracking-tight text-content">{title}</h1>
        {description ? (
          <p className="mt-0.5 text-xs text-content-muted">{description}</p>
        ) : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
      {children}
    </div>
  );
}

/** Small labelled action button that explains why it is disabled. */
export function GuardedButton({
  disabledReason,
  children,
  ...props
}: React.ComponentProps<typeof Button> & { disabledReason?: string | null }) {
  const disabled = Boolean(disabledReason);
  return (
    <span title={disabledReason ?? undefined} className="inline-flex">
      <Button {...props} disabled={props.disabled || disabled}>
        {children}
      </Button>
    </span>
  );
}
