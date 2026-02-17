import type { AppConfig } from "./types";

/** Whether the app is running on localhost. */
const isLocalhost =
  typeof window !== "undefined" &&
  (window.location.hostname === "localhost" ||
    window.location.hostname === "127.0.0.1");

/**
 * Toggle between EKS (default) and Legacy API Gateway endpoints.
 * Set to true to fall back to the original Lambda + API Gateway stack.
 */
const USE_LEGACY = false;

// --- Endpoint URLs ---

const LOCAL_API_URL = "http://localhost:8000";
const LOCAL_WS_URL = "ws://localhost:8000/ws";

const EKS_API_URL = "https://cfn-analyzer.gangprab.people.aws.dev";
const EKS_WS_URL = "wss://cfn-analyzer.gangprab.people.aws.dev/ws";

const LEGACY_API_URL =
  "https://6uyvwqy865.execute-api.us-east-1.amazonaws.com/dev";
const LEGACY_WS_URL =
  "wss://04hecd5eqj.execute-api.us-east-1.amazonaws.com/dev";

function resolveApiUrl(): string {
  if (isLocalhost) return LOCAL_API_URL;
  return USE_LEGACY ? LEGACY_API_URL : EKS_API_URL;
}

function resolveWsUrl(): string {
  if (isLocalhost) return LOCAL_WS_URL;
  return USE_LEGACY ? LEGACY_WS_URL : EKS_WS_URL;
}

// --- Exported config ---

/** Validates: Requirements 11.1, 11.2, 11.3, 11.4, 11.5 */
const config: AppConfig = {
  API_BASE_URL: resolveApiUrl(),
  WEBSOCKET_URL: resolveWsUrl(),
  AUTH: {
    useIAM: false,
    useCognito: false,
  },
  FEATURES: {
    batchAnalysis: false,
    pdfReports: true,
    realtimeUpdates: true,
  },
  TIMEOUTS: {
    analysisTimeout: 300_000, // 5 minutes
    websocketTimeout: 30_000, // 30 seconds
    maxReconnectAttempts: 5,
  },
};

export default config;

/** Re-export top-level URL constants for convenience. */
export const API_BASE_URL = config.API_BASE_URL;
export const WEBSOCKET_URL = config.WEBSOCKET_URL;
