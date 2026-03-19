import type { AppConfig } from "./types";

/** Whether the app is running on localhost. */
const isLocalhost =
  typeof window !== "undefined" &&
  (window.location.hostname === "localhost" ||
    window.location.hostname === "127.0.0.1");

// --- Endpoint URLs ---
// For local development, the FastAPI backend runs on localhost:8000.
// For production, set these to your ALB DNS name after deploying the EKS stack.
// The ALB endpoint is shown in the CDK output: CfnSecurityAnalyzer-Eks-v2-dev.AlbDnsName

const LOCAL_API_URL = "http://localhost:8000";
const LOCAL_WS_URL = "ws://localhost:8000/ws";

// Production: use relative URLs — CloudFront proxies /api/* and /ws to the ALB
const EKS_API_URL = "";
const EKS_WS_URL = `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}/ws`;

function resolveApiUrl(): string {
  if (isLocalhost) return LOCAL_API_URL;
  return EKS_API_URL;
}

function resolveWsUrl(): string {
  if (isLocalhost) return LOCAL_WS_URL;
  return EKS_WS_URL;
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
