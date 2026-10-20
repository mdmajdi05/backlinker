import type { ReactNode } from "react";
import { StorageProvider } from "@/lib/storage";
import { AppGuard } from "@/components/AppGuard";
import { AppShell } from "@/components/AppShell";

export default function AppLayout({ children }: { children: ReactNode }) {
  return (
    <StorageProvider>
      <AppGuard>
        <AppShell>{children}</AppShell>
      </AppGuard>
    </StorageProvider>
  );
}
