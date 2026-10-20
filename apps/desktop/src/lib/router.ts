import * as React from "react";

/**
 * Minimal hash based router - a desktop app does not need a full routing
 * library and this keeps the bundle small.
 */

export function currentRoute(): string {
  if (typeof window === "undefined") return "overview";
  const hash = window.location.hash.replace(/^#\/?/, "").trim();
  return hash || "overview";
}

export function navigate(route: string): void {
  const target = `#/${route}`;
  if (window.location.hash === target) return;
  window.location.hash = target;
}

export function useRoute(): [string, (route: string) => void] {
  const [route, setRoute] = React.useState<string>(currentRoute);

  React.useEffect(() => {
    const handler = () => setRoute(currentRoute());
    window.addEventListener("hashchange", handler);
    return () => window.removeEventListener("hashchange", handler);
  }, []);

  const go = React.useCallback((next: string) => navigate(next), []);
  return [route, go];
}
