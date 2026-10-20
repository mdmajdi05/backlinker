/** Small formatting helpers shared by the desktop views. */

export function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return new Intl.NumberFormat().format(value);
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

export function formatRelative(value: string | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const diff = date.getTime() - Date.now();
  const abs = Math.abs(diff);
  const units: Array<[Intl.RelativeTimeFormatUnit, number]> = [
    ["second", 1000],
    ["minute", 60_000],
    ["hour", 3_600_000],
    ["day", 86_400_000],
  ];
  const formatter = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
  let unit: Intl.RelativeTimeFormatUnit = "second";
  let size = 1000;
  for (const [candidate, ms] of units) {
    if (abs >= ms) {
      unit = candidate;
      size = ms;
    }
  }
  return formatter.format(Math.round(diff / size), unit);
}

export function truncate(value: string | null | undefined, max = 48): string {
  if (!value) return "-";
  return value.length > max ? `${value.slice(0, max - 1)}…` : value;
}

export function hostOf(url: string | null | undefined): string {
  if (!url) return "-";
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

export function titleCase(value: string): string {
  return value
    .toLowerCase()
    .split(/[\s_-]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}
