import { describe, it, expect, vi } from "vitest";
import fc from "fast-check";
import { routeWebSocketMessage } from "./useWebSocket";
import type { UseWebSocketOptions } from "./useWebSocket";
import type { WebSocketMessage } from "../types";

const arbSafeString = fc
  .stringOf(fc.constantFrom(..."abcdefghijklmnopqrstuvwxyz0123456789 _-,."), {
    minLength: 1,
    maxLength: 30,
  })
  .filter((s) => s.trim().length > 0)
  .map((s) => s.trim());

function createMockOptions(): UseWebSocketOptions {
  return {
    onCrawlComplete: vi.fn(),
    onPropertyAnalyzed: vi.fn(),
    onComplete: vi.fn(),
    onError: vi.fn(),
  };
}

describe("useWebSocket — Property Tests", () => {
  /**
   * Property 2: WebSocket message routing
   *
   * For any WebSocket message containing a known step field ("crawl",
   * "property_analyzed", "complete") or type field ("error"), the
   * routeWebSocketMessage function should invoke exactly the corresponding
   * callback with the message data.
   *
   * **Validates: Requirements 5.2, 5.3, 5.4, 5.5**
   */
  it("Property 2: routes crawl step messages to onCrawlComplete", () => {
    fc.assert(
      fc.property(arbSafeString, (detailMessage) => {
        const options = createMockOptions();
        const message: WebSocketMessage = {
          step: "crawl",
          detail: { message: detailMessage },
        };
        routeWebSocketMessage(message, options);
        expect(options.onCrawlComplete).toHaveBeenCalledOnce();
        expect(options.onCrawlComplete).toHaveBeenCalledWith(message);
        expect(options.onPropertyAnalyzed).not.toHaveBeenCalled();
        expect(options.onComplete).not.toHaveBeenCalled();
        expect(options.onError).not.toHaveBeenCalled();
      }),
      { numRuns: 100 },
    );
  });

  it("Property 2: routes property_analyzed step messages to onPropertyAnalyzed", () => {
    fc.assert(
      fc.property(
        arbSafeString,
        fc.constantFrom("CRITICAL", "HIGH", "MEDIUM", "LOW"),
        arbSafeString,
        arbSafeString,
        (name, riskLevel, impact, rec) => {
          const options = createMockOptions();
          const message: WebSocketMessage = {
            step: "property_analyzed",
            detail: {
              name,
              risk_level: riskLevel,
              security_impact: impact,
              recommendation: rec,
              description: "",
              key_threat: "",
              secure_configuration: "",
              property_path: "",
              best_practices: [],
              common_misconfigurations: [],
            },
          };
          routeWebSocketMessage(message, options);
          expect(options.onPropertyAnalyzed).toHaveBeenCalledOnce();
          const received = (
            options.onPropertyAnalyzed as ReturnType<typeof vi.fn>
          ).mock.calls[0][0];
          expect(received.name).toBe(name);
          expect(received.risk_level).toBe(riskLevel);
          expect(options.onCrawlComplete).not.toHaveBeenCalled();
          expect(options.onComplete).not.toHaveBeenCalled();
          expect(options.onError).not.toHaveBeenCalled();
        },
      ),
      { numRuns: 100 },
    );
  });

  it("Property 2: routes complete step messages to onComplete", () => {
    fc.assert(
      fc.property(arbSafeString, (detailMessage) => {
        const options = createMockOptions();
        const message: WebSocketMessage = {
          step: "complete",
          detail: { message: detailMessage },
        };
        routeWebSocketMessage(message, options);
        expect(options.onComplete).toHaveBeenCalledOnce();
        expect(options.onComplete).toHaveBeenCalledWith(message);
        expect(options.onCrawlComplete).not.toHaveBeenCalled();
        expect(options.onPropertyAnalyzed).not.toHaveBeenCalled();
        expect(options.onError).not.toHaveBeenCalled();
      }),
      { numRuns: 100 },
    );
  });

  it("Property 2: routes error type messages to onError", () => {
    fc.assert(
      fc.property(arbSafeString, (errorMessage) => {
        const options = createMockOptions();
        const message: WebSocketMessage = {
          type: "error",
          error: errorMessage,
        };
        routeWebSocketMessage(message, options);
        expect(options.onError).toHaveBeenCalledOnce();
        expect(options.onError).toHaveBeenCalledWith(errorMessage);
        expect(options.onCrawlComplete).not.toHaveBeenCalled();
        expect(options.onPropertyAnalyzed).not.toHaveBeenCalled();
        expect(options.onComplete).not.toHaveBeenCalled();
      }),
      { numRuns: 100 },
    );
  });

  it("Property 2: routes error type messages falling back to message field", () => {
    fc.assert(
      fc.property(arbSafeString, (msg) => {
        const options = createMockOptions();
        const message: WebSocketMessage = {
          type: "error",
          message: msg,
        };
        routeWebSocketMessage(message, options);
        expect(options.onError).toHaveBeenCalledOnce();
        expect(options.onError).toHaveBeenCalledWith(msg);
        expect(options.onCrawlComplete).not.toHaveBeenCalled();
        expect(options.onPropertyAnalyzed).not.toHaveBeenCalled();
        expect(options.onComplete).not.toHaveBeenCalled();
      }),
      { numRuns: 100 },
    );
  });
});
