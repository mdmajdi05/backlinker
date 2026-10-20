import type { ReactNode } from "react";

export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-surface-sunken p-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center justify-center gap-2">
          <span
            aria-hidden
            className="flex h-9 w-9 items-center justify-center rounded-lg bg-accent text-sm font-bold text-accent-fg"
          >
            AB
          </span>
          <div>
            <p className="text-sm font-semibold text-content">Auto Backlinker</p>
            <p className="text-[11px] text-content-subtle">Autonomous backlink workspace</p>
          </div>
        </div>
        {children}
        <p className="mt-6 text-center text-[11px] text-content-subtle">
          The backend must be running and reachable through NEXT_PUBLIC_API_BASE_URL.
        </p>
      </div>
    </div>
  );
}
