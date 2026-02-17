import { useRef, useState, useCallback } from "react";
import type { SSEEvent, SSEPropertyEvent } from "../types";
import { API_BASE_URL } from "../config";

/**
 * Options for the useSSE hook — callbacks invoked when SSE events arrive.
 * Validates: Requirements 6.2, 6.3, 6.4, 6.5
 */
export interface UseSSEOptions {
  onStatus: (analysisId: string) => void;
  onProperty: (property: SSEPropertyEvent) => void;
  onComplete: (totalProperties: number) => void;
  onError: (message: string) => void;
}

/**
 * Return value from the useSSE hook.
 */
export interface UseSSEReturn {
  startStream: (url: string) => Promise<void>;
  isStreaming: boolean;
}

/**
 * Parse an SSE text buffer into structured events.
 *
 * Splits on double newlines to find complete event blocks, extracts
 * `event:` and `data:` fields from each block, and JSON-parses the data.
 * Returns parsed events plus any remaining incomplete buffer text.
 *
 * Validates: Requirement 6.7
 *
 * @param buffer - Raw text buffer from the SSE stream
 * @returns Object with `parsed` SSEEvent array and `remaining` incomplete buffer
 */
export function parseSSEBuffer(buffer: string): {
  parsed: SSEEvent[];
  remaining: string;
} {
  const events: SSEEvent[] = [];
  const blocks = buffer.split("\n\n");
  // Last element may be an incomplete block
  const remaining = blocks.pop() ?? "";

  for (const block of blocks) {
    if (!block.trim()) continue;
    let eventType: string | null = null;
    let data: unknown = null;

    for (const line of block.split("\n")) {
      if (line.startsWith("event: ")) {
        eventType = line.slice(7);
      } else if (line.startsWith("data: ")) {
        try {
          data = JSON.parse(line.slice(6));
        } catch {
          data = line.slice(6);
        }
      }
    }

    if (eventType) {
      events.push({ event: eventType, data });
    }
  }

  return { parsed: events, remaining };
}

/**
 * Route a single parsed SSE event to the appropriate callback.
 *
 * Validates: Requirements 6.2, 6.3, 6.4, 6.5
 *
 * @param sseEvent - A parsed SSE event with event type and data
 * @param options  - Callback options to invoke
 */
export function routeSSEEvent(
  sseEvent: SSEEvent,
  options: UseSSEOptions,
): void {
  const { event, data } = sseEvent;

  switch (event) {
    case "status": {
      const d = data as { analysisId: string };
      options.onStatus(d.analysisId);
      break;
    }
    case "property": {
      options.onProperty(data as SSEPropertyEvent);
      break;
    }
    case "complete": {
      const d = data as { totalProperties: number };
      options.onComplete(d.totalProperties);
      break;
    }
    case "error": {
      const d = data as { message?: string };
      options.onError(d.message ?? "Unknown SSE error");
      break;
    }
    default:
      // Unknown event type — ignore
      break;
  }
}

/**
 * Custom React hook for SSE streaming during quick scan analysis.
 *
 * Uses fetch with ReadableStream to parse SSE events as they arrive,
 * routing each event to the appropriate callback. Falls back to polling
 * if the stream ends without a terminal event.
 *
 * Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7
 */
export function useSSE(options: UseSSEOptions): UseSSEReturn {
  const [isStreaming, setIsStreaming] = useState(false);
  const abortControllerRef = useRef<AbortController | null>(null);
  const receivedTerminalEventRef = useRef(false);
  const analysisIdRef = useRef<string | null>(null);

  const startStream = useCallback(
    async (url: string) => {
      // Reset state
      receivedTerminalEventRef.current = false;
      analysisIdRef.current = null;
      setIsStreaming(true);

      // Create abort controller for cancellation
      const abortController = new AbortController();
      abortControllerRef.current = abortController;

      // Wrap onStatus to capture analysisId
      const wrappedOptions: UseSSEOptions = {
        ...options,
        onStatus: (analysisId: string) => {
          analysisIdRef.current = analysisId;
          options.onStatus(analysisId);
        },
        onComplete: (totalProperties: number) => {
          receivedTerminalEventRef.current = true;
          options.onComplete(totalProperties);
        },
        onError: (message: string) => {
          receivedTerminalEventRef.current = true;
          options.onError(message);
        },
      };

      try {
        const response = await fetch(`${API_BASE_URL}/analysis/stream`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ resourceUrl: url, analysisType: "quick" }),
          signal: abortController.signal,
        });

        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`);
        }

        const reader = response.body!.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });

          const result = parseSSEBuffer(buffer);
          buffer = result.remaining;

          for (const event of result.parsed) {
            routeSSEEvent(event, wrappedOptions);
          }
        }

        // Stream ended — check if we got a terminal event
        if (
          !receivedTerminalEventRef.current &&
          analysisIdRef.current
        ) {
          startFallbackPolling(analysisIdRef.current, wrappedOptions);
          return; // Don't set isStreaming false yet — polling will handle it
        }
      } catch (error: unknown) {
        if ((error as Error).name === "AbortError") {
          // Intentional abort — do nothing
          return;
        }

        if (!receivedTerminalEventRef.current) {
          if (analysisIdRef.current) {
            // Stream started but connection dropped — fall back to polling
            startFallbackPolling(analysisIdRef.current, wrappedOptions);
            return;
          } else {
            // Stream never started — show error directly
            options.onError(
              "Failed to start analysis: " + (error as Error).message,
            );
          }
        }
      } finally {
        setIsStreaming(false);
      }
    },
    [options],
  );

  return { startStream, isStreaming };
}

/**
 * Fallback polling when the SSE stream ends without a terminal event.
 * Polls GET /analysis/{analysisId} every 2 seconds until COMPLETED or FAILED.
 *
 * Validates: Requirement 6.6
 */
function startFallbackPolling(
  analysisId: string,
  options: UseSSEOptions,
): void {
  const pollInterval = setInterval(async () => {
    try {
      const response = await fetch(
        `${API_BASE_URL}/analysis/${analysisId}`,
      );

      if (!response.ok) return; // Keep polling on non-OK responses

      const data = await response.json();

      if (data.status === "COMPLETED") {
        clearInterval(pollInterval);
        options.onComplete(data.results?.properties?.length ?? 0);
      } else if (data.status === "FAILED") {
        clearInterval(pollInterval);
        options.onError(data.error ?? "Analysis failed");
      }
    } catch {
      // Keep polling — transient network errors shouldn't stop us
    }
  }, 2000);
}
