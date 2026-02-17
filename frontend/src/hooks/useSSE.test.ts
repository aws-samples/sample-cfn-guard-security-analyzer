import { describe, it, expect, vi } from "vitest";
import fc from "fast-check";
import { parseSSEBuffer, routeSSEEvent } from "./useSSE";
import type { UseSSEOptions } from "./useSSE";
import type { SSEEvent } from "../types";

/**
 * Arbitrary for a safe string that won't break JSON serialization.
 * Avoids control characters and backslashes that complicate JSON embedding.
 */
const arbSafeString = fc
  .stringOf(fc.constantFrom(..."abcdefghijklmnopqrstuvwxyz0123456789 _-,."), {
    minLength: 1,
    maxLength: 30,
  })
  .filter((s) => s.trim().length > 0)
  .map((s) => s.trim());

/** Arbitrary for a positive integer (used for index/total/count). */
const arbPositiveInt = fc.integer({ min: 1, max: 1000 });

/**
 * Arbitrary for a single well-formed SSE event block.
 * Each block has an `event:` line and a `data:` line with valid JSON.
 */
const arbSSEBlock = fc.record({
  eventType: fc.constantFrom("status", "property", "complete", "error"),
  dataObj: fc.oneof(
    // status payload
    fc.record({ analysisId: arbSafeString }).map((d) => ({
      type: "status" as const,
      data: d,
    })),
    // property payload
    fc
      .record({
        name: arbSafeString,
        riskLevel: fc.constantFrom("CRITICAL", "HIGH", "MEDIUM", "LOW"),
        securityImplication: arbSafeString,
        recommendation: arbSafeString,
        index: fc.integer({ min: 0, max: 99 }),
        total: arbPositiveInt,
      })
      .map((d) => ({ type: "property" as const, data: d })),
    // complete payload
    fc
      .record({ totalProperties: arbPositiveInt })
      .map((d) => ({ type: "complete" as const, data: d })),
    // error payload
    fc
      .record({ message: arbSafeString })
      .map((d) => ({ type: "error" as const, data: d })),
  ),
});

/**
 * Build a well-formed SSE text block from an event type and data object.
 */
function buildSSEBlock(eventType: string, data: unknown): string {
  return `event: ${eventType}\ndata: ${JSON.stringify(data)}`;
}

describe("useSSE — Property Tests", () => {
  /**
   * Property 4: SSE buffer parsing
   *
   * For any well-formed SSE buffer consisting of event blocks separated by
   * double newlines, where each block contains an `event:` line and a `data:`
   * line with valid JSON, parsing the buffer should produce an array of
   * SSEEvent objects with the correct event type and parsed data, plus any
   * remaining incomplete buffer text.
   *
   * **Validates: Requirements 6.2, 6.3, 6.4, 6.5, 6.7**
   */
  it("Property 4: parseSSEBuffer produces correct SSEEvent objects from well-formed buffers", () => {
    fc.assert(
      fc.property(
        fc.array(arbSSEBlock, { minLength: 1, maxLength: 10 }),
        (blocks) => {
          // Build a complete buffer: each block separated by \n\n, with trailing \n\n
          const buffer = blocks
            .map((b) => buildSSEBlock(b.eventType, b.dataObj.data))
            .join("\n\n") + "\n\n";

          const result = parseSSEBuffer(buffer);

          // Should produce exactly as many events as blocks
          expect(result.parsed.length).toBe(blocks.length);

          // Each parsed event should have the correct event type
          for (let i = 0; i < blocks.length; i++) {
            expect(result.parsed[i].event).toBe(blocks[i].eventType);
          }

          // Each parsed event data should deep-equal the original data
          for (let i = 0; i < blocks.length; i++) {
            expect(result.parsed[i].data).toEqual(blocks[i].dataObj.data);
          }

          // Remaining buffer should be empty for complete buffers
          expect(result.remaining).toBe("");
        },
      ),
      { numRuns: 100 },
    );
  });

  it("Property 4: parseSSEBuffer preserves incomplete trailing block as remaining", () => {
    fc.assert(
      fc.property(
        fc.array(arbSSEBlock, { minLength: 1, maxLength: 5 }),
        arbSSEBlock,
        (completeBlocks, incompleteBlock) => {
          // Build buffer with complete blocks + an incomplete trailing block (no trailing \n\n)
          const completeBuffer = completeBlocks
            .map((b) => buildSSEBlock(b.eventType, b.dataObj.data))
            .join("\n\n") + "\n\n";

          const incompleteText = buildSSEBlock(
            incompleteBlock.eventType,
            incompleteBlock.dataObj.data,
          );

          const buffer = completeBuffer + incompleteText;
          const result = parseSSEBuffer(buffer);

          // Should parse only the complete blocks
          expect(result.parsed.length).toBe(completeBlocks.length);

          // Remaining should contain the incomplete block text
          expect(result.remaining).toBe(incompleteText);
        },
      ),
      { numRuns: 100 },
    );
  });

  /**
   * Property 3: SSE event routing
   *
   * For any parsed SSE event with a known event type ("status", "property",
   * "complete", "error"), the routeSSEEvent function should invoke exactly
   * the corresponding callback with the event data.
   *
   * **Validates: Requirements 6.2, 6.3, 6.4, 6.5**
   */
  it("Property 3: routeSSEEvent invokes the correct callback for status events", () => {
    fc.assert(
      fc.property(arbSafeString, (analysisId) => {
        const options: UseSSEOptions = {
          onStatus: vi.fn(),
          onProperty: vi.fn(),
          onComplete: vi.fn(),
          onError: vi.fn(),
        };

        const event: SSEEvent = {
          event: "status",
          data: { analysisId },
        };

        routeSSEEvent(event, options);

        expect(options.onStatus).toHaveBeenCalledOnce();
        expect(options.onStatus).toHaveBeenCalledWith(analysisId);
        expect(options.onProperty).not.toHaveBeenCalled();
        expect(options.onComplete).not.toHaveBeenCalled();
        expect(options.onError).not.toHaveBeenCalled();
      }),
      { numRuns: 100 },
    );
  });

  it("Property 3: routeSSEEvent invokes the correct callback for property events", () => {
    fc.assert(
      fc.property(
        arbSafeString,
        fc.constantFrom("CRITICAL", "HIGH", "MEDIUM", "LOW"),
        arbSafeString,
        arbSafeString,
        fc.integer({ min: 0, max: 99 }),
        arbPositiveInt,
        (name, riskLevel, secImp, rec, index, total) => {
          const options: UseSSEOptions = {
            onStatus: vi.fn(),
            onProperty: vi.fn(),
            onComplete: vi.fn(),
            onError: vi.fn(),
          };

          const propertyData = {
            name,
            riskLevel,
            securityImplication: secImp,
            recommendation: rec,
            index,
            total,
          };

          const event: SSEEvent = { event: "property", data: propertyData };
          routeSSEEvent(event, options);

          expect(options.onProperty).toHaveBeenCalledOnce();
          expect(options.onProperty).toHaveBeenCalledWith(propertyData);
          expect(options.onStatus).not.toHaveBeenCalled();
          expect(options.onComplete).not.toHaveBeenCalled();
          expect(options.onError).not.toHaveBeenCalled();
        },
      ),
      { numRuns: 100 },
    );
  });

  it("Property 3: routeSSEEvent invokes the correct callback for complete events", () => {
    fc.assert(
      fc.property(arbPositiveInt, (totalProperties) => {
        const options: UseSSEOptions = {
          onStatus: vi.fn(),
          onProperty: vi.fn(),
          onComplete: vi.fn(),
          onError: vi.fn(),
        };

        const event: SSEEvent = {
          event: "complete",
          data: { totalProperties },
        };

        routeSSEEvent(event, options);

        expect(options.onComplete).toHaveBeenCalledOnce();
        expect(options.onComplete).toHaveBeenCalledWith(totalProperties);
        expect(options.onStatus).not.toHaveBeenCalled();
        expect(options.onProperty).not.toHaveBeenCalled();
        expect(options.onError).not.toHaveBeenCalled();
      }),
      { numRuns: 100 },
    );
  });

  it("Property 3: routeSSEEvent invokes the correct callback for error events", () => {
    fc.assert(
      fc.property(arbSafeString, (message) => {
        const options: UseSSEOptions = {
          onStatus: vi.fn(),
          onProperty: vi.fn(),
          onComplete: vi.fn(),
          onError: vi.fn(),
        };

        const event: SSEEvent = { event: "error", data: { message } };
        routeSSEEvent(event, options);

        expect(options.onError).toHaveBeenCalledOnce();
        expect(options.onError).toHaveBeenCalledWith(message);
        expect(options.onStatus).not.toHaveBeenCalled();
        expect(options.onProperty).not.toHaveBeenCalled();
        expect(options.onComplete).not.toHaveBeenCalled();
      }),
      { numRuns: 100 },
    );
  });
});
