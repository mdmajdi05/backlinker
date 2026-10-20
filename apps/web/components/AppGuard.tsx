"use client";

import * as React from "react";
import { usePathname, useRouter } from "next/navigation";
import { api } from "@autobacklinker/api-client";
import { apiClient } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useResource } from "@/lib/hooks";
import { FullPageLoader } from "./FullPageLoader";

/**
 * Route guard for the authenticated workspace:
 *  - unauthenticated visitors are sent to /login
 *  - workspaces without a business profile are sent to /onboarding
 */
export function AppGuard({ children }: { children: React.ReactNode }) {
  const { authenticated, loading: authLoading, token } = useAuth();
  const pathname = usePathname();
  const router = useRouter();

  const profiles = useResource(
    () => api.profiles.list(apiClient),
    [token],
    { enabled: authenticated && !authLoading },
  );

  React.useEffect(() => {
    if (authLoading) return;
    if (!authenticated) {
      const next = encodeURIComponent(pathname + window.location.search);
      router.replace(`/login?next=${next}`);
    }
  }, [authLoading, authenticated, pathname, router]);

  React.useEffect(() => {
    if (!authenticated) return;
    // Wait for the first profiles request to finish before deciding whether
    // the workspace still needs the onboarding wizard.
    if (!profiles.settled) return;
    if (profiles.error) return;
    const list = profiles.data ?? [];
    if (list.length === 0 && pathname !== "/onboarding") {
      router.replace("/onboarding");
    }
  }, [authenticated, profiles.settled, profiles.error, profiles.data, pathname, router]);

  if (authLoading || !authenticated) {
    return <FullPageLoader label="Checking your session…" />;
  }

  return <>{children}</>;
}
