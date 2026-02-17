/**
 * Parse text that may contain numbered items (e.g., "1. Do X 2. Do Y")
 * into a structured result.
 *
 * Returns an array of string items when 2+ numbered items are found,
 * or the original string when no numbered pattern is detected.
 * Returns empty string for null/empty input.
 *
 * Validates: Requirements 10.4, 10.5
 */
export function parseNumberedList(
  text: string | null | undefined,
): string[] | string {
  if (!text) return "";

  // Try "1. " format first
  let items = text.split(/(?:^|\s)(?=\d+\.\s)/).filter((s) => s.trim());
  let prefixRegex = /^\d+\.\s*/;

  if (items.length < 2) {
    // Try "1) " format (some agents use parentheses)
    items = text.split(/(?:^|[\s:])(?=\d+\)\s)/).filter((s) => s.trim());
    prefixRegex = /^\d+\)\s*/;
  }

  if (items.length >= 2) {
    return items.map((item) => item.replace(prefixRegex, "").trim());
  }

  return text;
}
