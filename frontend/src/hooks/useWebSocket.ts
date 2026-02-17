import { useRef, useState, useCallback } from "react";
import type { PropertyData, WebSocketMessage } from "../types";
import { WEBSOCKET_URL } from "../config";
import config from "../config";
import { normalizePropertyData } from "../utils/normalizePropertyData";

/**
 * Options for the useWebSocket hook — callbacks invoked when messages arrive.
 * Validates: Requirements 5.2, 5.3, 5.4, 5.5
 */
export interface UseWebSocketOptions {
  onCrawlComplete: (data: WebSocketMessage) => void;
  onPropertyAnalyzed: (property: PropertyData) => void;
  onComplete: (data: WebSocketMessage) => void;
  onError: (message: string) => void;
}

/**
 * Return value from the useWebSocket hook.
 */
export interface UseWebSocketReturn {
  connect: () => Promise<void>;
  subscribe: (analysisId: string) => void;
  disconnect: () => void;
  isConnected: boolean;
}

/**
 * Route a WebSocket message to the appropriate callback based on its
 * `step` or `type` field.
 *
 * Step-based routing (from Step Functions workflow):
 * - "crawl" → onCrawlComplete
 * - "property_analyzed" → onPropertyAnalyzed (normalizes property data)
 * - "complete" → onComplete
 *
 * Type-based routing (forward compatibility):
 * - "error" → onError
 *
 * Validates: Requirements 5.2, 5.3, 5.4, 5.5
 *
 * @param message - Parsed WebSocket message
 * @param options - Callback options to invoke
 */
export function routeWebSocketMessage(
  message: WebSocketMessage,
  options: UseWebSocketOptions,
): void {
  // Check step field first (backend Step Functions messages)
  const step = message.step;
  if (step) {
    switch (step) {
      case "crawl":
        options.onCrawlComplete(message);
        return;
      case "property_analyzed": {
        const detail = message.detail ?? {};
        const normalized = normalizePropertyData(
          detail as Record<string, unknown>,
        );
        options.onPropertyAnalyzed(normalized);
        return;
      }
      case "complete":
        options.onComplete(message);
        return;
    }
  }

  // Check type field (forward compatibility / error messages)
  const messageType = message.type ?? message.action;
  if (messageType) {
    switch (messageType) {
      case "error":
        options.onError(
          message.error ?? message.message ?? "Unknown WebSocket error",
        );
        return;
    }
  }
}

/**
 * Custom React hook for WebSocket connection management during detailed analysis.
 *
 * Handles connection lifecycle, message routing, subscribe/disconnect,
 * and reconnection with exponential backoff.
 *
 * Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8
 */
export function useWebSocket(options: UseWebSocketOptions): UseWebSocketReturn {
  const [isConnected, setIsConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const intentionalDisconnectRef = useRef(false);
  const optionsRef = useRef(options);
  optionsRef.current = options;

  const connect = useCallback((): Promise<void> => {
    return new Promise((resolve, reject) => {
      try {
        // Close existing connection if any
        if (wsRef.current) {
          wsRef.current.close();
        }

        intentionalDisconnectRef.current = false;
        const ws = new WebSocket(WEBSOCKET_URL);
        wsRef.current = ws;

        ws.onopen = () => {
          reconnectAttemptsRef.current = 0;
          setIsConnected(true);
          resolve();
        };

        ws.onmessage = (event: MessageEvent) => {
          try {
            const data: WebSocketMessage = JSON.parse(event.data);
            routeWebSocketMessage(data, optionsRef.current);
          } catch {
            // Ignore unparseable messages
          }
        };

        ws.onclose = () => {
          setIsConnected(false);

          // Attempt reconnection if not intentional
          if (
            !intentionalDisconnectRef.current &&
            reconnectAttemptsRef.current <
              config.TIMEOUTS.maxReconnectAttempts
          ) {
            reconnectAttemptsRef.current += 1;
            const delay = 2000 * reconnectAttemptsRef.current;
            setTimeout(() => {
              if (!intentionalDisconnectRef.current) {
                connect().catch(() => {
                  // Reconnection failed — will retry on next close
                });
              }
            }, delay);
          }
        };

        ws.onerror = () => {
          reject(new Error("WebSocket connection error"));
        };

        // Timeout if connection takes too long
        setTimeout(() => {
          if (ws.readyState !== WebSocket.OPEN) {
            ws.close();
            reject(new Error("WebSocket connection timeout"));
          }
        }, config.TIMEOUTS.websocketTimeout);
      } catch (error) {
        reject(error);
      }
    });
  }, []);

  /**
   * Send a subscribe message for the given analysis ID.
   * Validates: Requirement 5.7
   */
  const subscribe = useCallback((analysisId: string) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(
        JSON.stringify({ action: "subscribe", analysisId }),
      );
    }
  }, []);

  /**
   * Close the WebSocket connection and stop reconnection attempts.
   * Validates: Requirement 5.8
   */
  const disconnect = useCallback(() => {
    intentionalDisconnectRef.current = true;
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    setIsConnected(false);
  }, []);

  return { connect, subscribe, disconnect, isConnected };
}
