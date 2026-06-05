/**
 * Format a "Cached" badge label from an ISO timestamp.
 *
 * Single source of truth for the cached-at display across single-scan,
 * discovery, and batch results — so every "Cached" badge reads the same way
 * instead of one showing a localized date and another the raw ISO string.
 *
 * Uses `toLocaleString` with an explicit short time-zone name, so the time is
 * rendered in the VIEWER's local zone with the zone labelled. A user in IST
 * sees IST; a user in Sydney sees AEST/AEDT — each based on where they run the
 * query, which is what we want for a shared/forwarded cache timestamp.
 */
export function formatCachedLabel(cachedAt: string | null | undefined): string {
  if (!cachedAt) return "Cached";
  const date = new Date(cachedAt);
  if (Number.isNaN(date.getTime())) return "Cached";
  // `timeZoneName: "short"` appends the viewer's zone abbreviation (e.g. GMT+5:30,
  // AEST). The browser's default locale + zone drive the rest, so no hard-coded
  // region — it adapts to whoever is viewing.
  const formatted = date.toLocaleString(undefined, {
    year: "numeric",
    month: "numeric",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
    timeZoneName: "short",
  });
  return `Cached ${formatted}`;
}
