import type { AppConfig } from "./types";

/** Whether the app is running on localhost. */
const isLocalhost =
  typeof window !== "undefined" &&
  (window.location.hostname === "localhost" ||
    window.location.hostname === "127.0.0.1");

// --- Endpoint URLs ---
// For local development, point at SAM local or a deployed dev stack.
// For production, the SPA is served from CloudFront which is also configured
// (via scripts/post-deploy.sh) to proxy /analysis/*, /reports/*, /guard-rules,
// and /ws to API Gateway. So in production we use relative URLs — same origin
// as the page itself — which avoids CORS entirely.

const LOCAL_API_URL = "http://localhost:3000";
const LOCAL_WS_URL = "ws://localhost:3001/ws";

// Call API Gateway directly. CloudFront's SPA error-page rewrites
// (403/404 -> /index.html) intercept anything CloudFront sees as an error,
// so same-origin '/analysis' returns the SPA HTML instead of API JSON.
// Bypass CloudFront for the API; CORS is already permitted by the API Gateway
// REST API (Access-Control-Allow-Origin: * on every Lambda response).
//
// Set these at build time via Vite env vars (see frontend/.env.example). After
// running `deploy.sh`, copy the REST API and WebSocket URLs from the CDK stack
// outputs (or `scripts/post-deploy.sh`) into `frontend/.env`:
//   VITE_API_URL=https://<rest-api-id>.execute-api.<region>.amazonaws.com/<stage>
//   VITE_WS_URL=wss://<ws-api-id>.execute-api.<region>.amazonaws.com/<stage>
// The placeholders below only let the app build before it is configured.
const PROD_API_URL =
  import.meta.env.VITE_API_URL ??
  "https://YOUR-API-ID.execute-api.us-east-1.amazonaws.com/dev";
const PROD_WS_URL =
  import.meta.env.VITE_WS_URL ??
  "wss://YOUR-WS-API-ID.execute-api.us-east-1.amazonaws.com/dev";

function resolveApiUrl(): string {
  if (isLocalhost) return LOCAL_API_URL;
  return PROD_API_URL;
}

function resolveWsUrl(): string {
  if (isLocalhost) return LOCAL_WS_URL;
  return PROD_WS_URL;
}

const config: AppConfig = {
  API_BASE_URL: resolveApiUrl(),
  WEBSOCKET_URL: resolveWsUrl(),
  AUTH: {
    useIAM: false,
    useCognito: false,
  },
  FEATURES: {
    // Phase 6: multi-resource batch flow is now wired end-to-end.
    batchAnalysis: true,
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
