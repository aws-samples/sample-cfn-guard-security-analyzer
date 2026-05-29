import { describe, it, expect } from "vitest";
import fc from "fast-check";
import { validateUrl } from "./InputSection";

/**
 * Property 1: Whitespace URL rejection
 * For any string composed entirely of whitespace characters (including empty string),
 * submitting it as the URL input should be rejected with a validation error,
 * and no analysis should be started.
 *
 * **Validates: Requirements 3.5**
 */
describe("Property 1: Whitespace URL rejection", () => {
  it("rejects empty string", () => {
    expect(validateUrl("")).toBe(false);
  });

  it("rejects any whitespace-only string", () => {
    fc.assert(
      fc.property(
        fc.stringOf(fc.constantFrom(" ", "\t", "\n", "\r", "\f", "\v"), { minLength: 0, maxLength: 50 }),
        (whitespaceStr) => {
          expect(validateUrl(whitespaceStr)).toBe(false);
        },
      ),
      { numRuns: 100 },
    );
  });

  it("accepts any string with at least one non-whitespace character", () => {
    fc.assert(
      fc.property(
        fc.tuple(
          fc.string({ minLength: 0, maxLength: 20 }),
          fc.char().filter((c) => c.trim().length > 0),
          fc.string({ minLength: 0, maxLength: 20 }),
        ),
        ([prefix, nonWs, suffix]) => {
          const url = prefix + nonWs + suffix;
          expect(validateUrl(url)).toBe(true);
        },
      ),
      { numRuns: 100 },
    );
  });
});
