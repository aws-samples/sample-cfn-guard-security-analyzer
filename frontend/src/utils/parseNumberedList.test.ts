import { describe, it, expect } from "vitest";
import fc from "fast-check";
import { parseNumberedList } from "./parseNumberedList";

/**
 * Arbitrary for safe item text — only letters and spaces, no digits,
 * so it can't accidentally create extra numbered-item patterns.
 */
const arbItemText = fc
  .stringOf(fc.constantFrom(..."abcdefghijklmnopqrstuvwxyz ABCDEFGHIJKLMNOPQRSTUVWXYZ"), {
    minLength: 2,
    maxLength: 30,
  })
  .filter((s) => s.trim().length > 0)
  .map((s) => s.trim());

/**
 * Generate a string with N numbered items in "N. text" format.
 */
const arbNumberedItems = fc
  .array(arbItemText, { minLength: 2, maxLength: 8 })
  .map((items) =>
    items.map((text, i) => `${i + 1}. ${text}`).join(" "),
  );

/**
 * Generate a string with N numbered items in "N) text" format.
 */
const arbParenNumberedItems = fc
  .array(arbItemText, { minLength: 2, maxLength: 8 })
  .map((items) =>
    items.map((text, i) => `${i + 1}) ${text}`).join(" "),
  );

describe("parseNumberedList — Property Tests", () => {
  /**
   * Property 10: Parser numbered list extraction
   *
   * For any text string containing two or more numbered items in "N. text"
   * format, parseNumberedList should return a structured list with the same
   * number of items, each containing the text after the number prefix.
   * For text without numbered patterns, it should return the original text.
   *
   * **Validates: Requirements 10.4**
   */
  it("Property 10: extracts correct number of items from dot-numbered text", () => {
    fc.assert(
      fc.property(arbNumberedItems, (text) => {
        const result = parseNumberedList(text);

        // Should return an array (not a string) since we have 2+ items
        expect(Array.isArray(result)).toBe(true);

        if (Array.isArray(result)) {
          // Count how many numbered items we generated
          const matches = text.match(/(?:^|\s)\d+\.\s/g);
          const expectedCount = matches ? matches.length : 0;

          expect(result.length).toBe(expectedCount);

          // Each extracted item should be a non-empty trimmed string
          for (const item of result) {
            expect(typeof item).toBe("string");
            expect(item.trim().length).toBeGreaterThan(0);
          }
        }
      }),
      { numRuns: 100 },
    );
  });

  it("Property 10: extracts correct number of items from paren-numbered text", () => {
    fc.assert(
      fc.property(arbParenNumberedItems, (text) => {
        const result = parseNumberedList(text);

        // Should return an array since we have 2+ items
        expect(Array.isArray(result)).toBe(true);

        if (Array.isArray(result)) {
          const matches = text.match(/(?:^|[\s:])\d+\)\s/g);
          const expectedCount = matches ? matches.length : 0;

          expect(result.length).toBe(expectedCount);

          for (const item of result) {
            expect(typeof item).toBe("string");
            expect(item.trim().length).toBeGreaterThan(0);
          }
        }
      }),
      { numRuns: 100 },
    );
  });

  it("Property 10: returns original string for non-numbered text", () => {
    fc.assert(
      fc.property(
        fc.string({ minLength: 1, maxLength: 100 }).filter((s) => {
          // Ensure the string doesn't match numbered patterns
          const trimmed = s.trim();
          if (trimmed.length === 0) return false;
          const dotItems = trimmed.split(/(?:^|\s)(?=\d+\.\s)/).filter((x) => x.trim());
          const parenItems = trimmed.split(/(?:^|[\s:])(?=\d+\)\s)/).filter((x) => x.trim());
          return dotItems.length < 2 && parenItems.length < 2;
        }),
        (text) => {
          const result = parseNumberedList(text);
          expect(result).toBe(text);
        },
      ),
      { numRuns: 100 },
    );
  });

  it("Property 10: returns empty string for null/empty input", () => {
    expect(parseNumberedList(null)).toBe("");
    expect(parseNumberedList(undefined)).toBe("");
    expect(parseNumberedList("")).toBe("");
  });
});
