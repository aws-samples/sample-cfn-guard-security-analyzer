import { useReducer, useCallback, useMemo, useState } from "react";
import type {
  AnalysisState,
  AnalysisType,
  PropertyData,
  ActivityLogEntry,
  SSEPropertyEvent,
  WebSocketMessage,
} from "../types";
import { API_BASE_URL } from "../config";
import { pollUntilDone, PollTimeoutError } from "../utils/poll";

/**
 * Normalize a backend property record to the frontend PropertyData shape.
 * The agents emit camelCase fields (`riskLevel`, `securityImplication`,
 * `recommendation`) while the UI expects snake_case (`risk_level`,
 * `security_impact`, `key_threat`, ...). Backend renames would ripple through
 * caches, PDF generation, and Guard rule generation; doing this once at the
 * boundary keeps both sides ergonomic.
 */
function normalizeProperty(raw: unknown): PropertyData {
  const r = (raw ?? {}) as Record<string, unknown>;
  const get = (...keys: string[]): string => {
    for (const k of keys) {
      const v = r[k];
      if (typeof v === "string" && v.length > 0) return v;
    }
    return "";
  };
  const risk = (get("risk_level", "riskLevel") || "MEDIUM").toUpperCase();
  return {
    name: get("name", "propertyName"),
    risk_level: (["CRITICAL", "HIGH", "MEDIUM", "LOW"].includes(risk)
      ? risk
      : "MEDIUM") as PropertyData["risk_level"],
    description: get("description"),
    // Quick scan emits singular (securityImplication/recommendation); the
    // detailed property_analyzer agent emits plural (securityImplications/
    // recommendations). Accept both.
    security_impact: get(
      "security_impact",
      "securityImplication",
      "securityImplications",
      "securityImpact",
    ),
    key_threat: get("key_threat", "keyThreat"),
    secure_configuration: get("secure_configuration", "secureConfiguration"),
    recommendation: get("recommendation", "recommendations"),
    property_path: get("property_path", "propertyPath"),
    best_practices: Array.isArray(r.best_practices)
      ? (r.best_practices as string[])
      : Array.isArray(r.bestPractices)
        ? (r.bestPractices as string[])
        : [],
    common_misconfigurations: Array.isArray(r.common_misconfigurations)
      ? (r.common_misconfigurations as string[])
      : Array.isArray(r.commonMisconfigurations)
        ? (r.commonMisconfigurations as string[])
        : [],
  };
}

function normalizeProperties(raw: unknown): PropertyData[] {
  return Array.isArray(raw) ? raw.map(normalizeProperty) : [];
}
import { useSSE } from "./useSSE";
import { useWebSocket } from "./useWebSocket";

/**
 * Per-resource analysis returned from POST /analysis/batch.
 *
 * The batch handler returns one entry per submitted URL, keyed by the
 * discovered CFN resource type (or the URL itself when the type couldn't be
 * determined). Each entry mirrors the shape of a single quick-scan response:
 * `analysisId`, `cached`, `cached_at`, and a `results` payload containing the
 * `properties` array plus `resourceType`.
 */
export interface BatchPerResourceResult {
  analysisId: string;
  status: string;
  cached: boolean;
  cached_at: string | null;
  results: {
    resourceType?: string;
    properties?: unknown[];
    [k: string]: unknown;
  };
}

/** Aggregate response shape returned by analyzeBatch. */
export interface BatchAnalysisResponse {
  batchId: string;
  count: number;
  /** Resource-keyed map of per-URL successes. */
  results: Record<string, BatchPerResourceResult>;
  /** Resource-keyed map of per-URL failures. */
  errors: Record<string, string>;
  /** Original submission URL -> response key for re-keying by submission order. */
  urlToKey: Record<string, string>;
}

/**
 * Return value from the useAnalysis hook.
 * Validates: Requirement 4.1
 */
export interface UseAnalysisReturn {
  status: AnalysisState["status"];
  analysisId: string | null;
  results: PropertyData[];
  progress: number;
  progressMessage: string;
  activityLog: ActivityLogEntry[];
  error: string | null;
  resourceUrl: string | null;
  resourceType: string | null;
  analysisType: AnalysisType;
  /** True when the latest results came from the orchestrator's DynamoDB cache. */
  cached: boolean;
  /** ISO timestamp the cached entry was originally written, or null. */
  cachedAt: string | null;
  /**
   * Start an analysis. Pass `refresh=true` to force a cache miss and rewrite
   * (Refresh button on the results pane). Default is to allow cache hits.
   */
  startAnalysis: (
    url: string,
    type: AnalysisType,
    refresh?: boolean,
  ) => Promise<void>;
  /**
   * Start a multi-resource batch quick-scan against POST /analysis/batch.
   * Resolves with the aggregated per-resource results + per-resource errors.
   * Up to 5 URLs (enforced server-side); the hook still tracks an in-flight
   * flag via `batchAnalyzing` so the UI can disable the trigger.
   */
  analyzeBatch: (urls: string[]) => Promise<BatchAnalysisResponse | null>;
  /** True while a batch analysis is in flight. */
  batchAnalyzing: boolean;
  /** Batch-only error message (single-URL errors keep using `error`). */
  batchError: string | null;
  /** Latest batch response, or null when idle / pre-first-batch. */
  batchResponse: BatchAnalysisResponse | null;
  /** Reset batch state without touching single-URL state. */
  clearBatch: () => void;
  resetAnalysis: () => void;
}

// --- Reducer ---

type Action =
  | { type: "START"; analysisType: AnalysisType; resourceUrl: string }
  | { type: "SET_ANALYSIS_ID"; analysisId: string }
  | { type: "ADD_RESULT"; property: PropertyData }
  | { type: "SET_PROGRESS"; progress: number; message: string }
  | { type: "ADD_LOG"; entry: ActivityLogEntry }
  | {
      type: "COMPLETE";
      results?: PropertyData[];
      cached?: boolean;
      cachedAt?: string | null;
    }
  | { type: "FAIL"; error: string }
  | { type: "SET_RESOURCE_TYPE"; resourceType: string }
  | { type: "RESET" };

const initialState: AnalysisState = {
  status: "idle",
  analysisId: null,
  analysisType: "quick",
  results: [],
  progress: 0,
  progressMessage: "",
  activityLog: [],
  error: null,
  resourceUrl: null,
  resourceType: null,
  cached: false,
  cachedAt: null,
};

function analysisReducer(state: AnalysisState, action: Action): AnalysisState {
  switch (action.type) {
    case "START":
      return {
        ...initialState,
        status: "in_progress",
        analysisType: action.analysisType,
        resourceUrl: action.resourceUrl,
      };
    case "SET_ANALYSIS_ID":
      return { ...state, analysisId: action.analysisId };
    case "ADD_RESULT":
      return { ...state, results: [...state.results, action.property] };
    case "SET_PROGRESS":
      return {
        ...state,
        progress: action.progress,
        progressMessage: action.message,
      };
    case "ADD_LOG":
      return {
        ...state,
        activityLog: [...state.activityLog, action.entry],
      };
    case "COMPLETE":
      return {
        ...state,
        status: "completed",
        progress: 100,
        progressMessage: "Analysis complete",
        results: action.results ?? state.results,
        cached: action.cached ?? state.cached,
        cachedAt: action.cachedAt ?? state.cachedAt,
      };
    case "FAIL":
      return { ...state, status: "failed", error: action.error };
    case "SET_RESOURCE_TYPE":
      return { ...state, resourceType: action.resourceType };
    case "RESET":
      return initialState;
    default:
      return state;
  }
}

/** Helper to create a timestamped activity log entry. */
function logEntry(
  title: string,
  details: string,
  type: ActivityLogEntry["type"] = "info",
): ActivityLogEntry {
  return { timestamp: new Date().toLocaleTimeString(), title, details, type };
}

/**
 * Custom React hook that orchestrates analysis state, SSE streaming (quick scan),
 * and WebSocket updates (detailed analysis).
 *
 * Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5, 4.6
 */
export function useAnalysis(): UseAnalysisReturn {
  const [state, dispatch] = useReducer(analysisReducer, initialState);

  // --- SSE callbacks (quick scan) ---
  const sseOptions = useMemo(
    () => ({
      onStatus: (analysisId: string) => {
        dispatch({ type: "SET_ANALYSIS_ID", analysisId });
        dispatch({
          type: "ADD_LOG",
          entry: logEntry(
            "Analysis Started",
            "Streaming security analysis in progress",
          ),
        });
      },
      onProperty: (property: SSEPropertyEvent) => {
        const normalized: PropertyData = {
          name: property.name,
          risk_level: (property.riskLevel as PropertyData["risk_level"]) ?? "MEDIUM",
          description: "",
          security_impact: property.securityImplication ?? "",
          key_threat: "",
          secure_configuration: "",
          recommendation: property.recommendation ?? "",
          property_path: "",
          best_practices: [],
          common_misconfigurations: [],
        };
        dispatch({ type: "ADD_RESULT", property: normalized });

        const percent = Math.round(
          ((property.index + 1) / property.total) * 100,
        );
        dispatch({
          type: "SET_PROGRESS",
          progress: percent,
          message: `Analyzed ${property.name} (${property.index + 1}/${property.total})`,
        });
        dispatch({
          type: "ADD_LOG",
          entry: logEntry(
            property.name,
            `${property.riskLevel} risk`,
            "success",
          ),
        });
      },
      onComplete: (totalProperties: number, resourceType?: string) => {
        dispatch({ type: "COMPLETE" });
        if (resourceType) {
          dispatch({ type: "SET_RESOURCE_TYPE", resourceType });
        }
        dispatch({
          type: "ADD_LOG",
          entry: logEntry(
            "Analysis Complete",
            `Found ${totalProperties} security properties`,
            "success",
          ),
        });
      },
      onError: (message: string) => {
        dispatch({ type: "FAIL", error: message });
        dispatch({
          type: "ADD_LOG",
          entry: logEntry("Error", message, "error"),
        });
      },
    }),
    [],
  );

  // Quick scan now uses async dispatch + polling (Phase 7) instead of SSE.
  // We still call useSSE so test imports + side-effect setup remain stable;
  // the returned starter is intentionally not invoked.
  void useSSE(sseOptions);

  // --- WebSocket callbacks (detailed analysis) ---
  const wsOptions = useMemo(
    () => ({
      onCrawlComplete: (data: WebSocketMessage) => {
        dispatch({
          type: "SET_PROGRESS",
          progress: 20,
          message: "Documentation crawl completed",
        });
        dispatch({
          type: "ADD_LOG",
          entry: logEntry(
            "Crawl Complete",
            (data.detail?.message as string) ??
              "Documentation crawling is complete",
            "success",
          ),
        });
      },
      onPropertyAnalyzed: (property: PropertyData) => {
        dispatch({ type: "ADD_RESULT", property });
        dispatch({
          type: "ADD_LOG",
          entry: logEntry(
            property.name,
            `${property.risk_level} risk`,
            "success",
          ),
        });
      },
      onComplete: async (data: WebSocketMessage) => {
        dispatch({
          type: "SET_PROGRESS",
          progress: 100,
          message: "Analysis complete",
        });
        dispatch({
          type: "ADD_LOG",
          entry: logEntry(
            "Workflow Complete",
            (data.detail?.message as string) ??
              "Detailed analysis workflow completed",
            "success",
          ),
        });

        // Fetch final results — the analysisId is captured in closure via state
        // We use a small delay to ensure the state has the analysisId
        // The actual fetch happens in startAnalysis after WS complete
      },
      onError: (message: string) => {
        dispatch({ type: "FAIL", error: message });
        dispatch({
          type: "ADD_LOG",
          entry: logEntry("Error", message, "error"),
        });
      },
    }),
    [],
  );

  const ws = useWebSocket(wsOptions);

  // --- Actions ---

  /**
   * Start an analysis. For quick scan, delegates to SSE streaming.
   * For detailed, connects WebSocket, POSTs to REST API, and subscribes.
   *
   * `refresh=true` appends `?refresh=true` to the request so the orchestrator
   * bypasses the DynamoDB cache and re-runs the analysis end-to-end.
   *
   * Validates: Requirements 4.2, 4.3
   */
  const startAnalysis = useCallback(
    async (url: string, type: AnalysisType, refresh?: boolean) => {
      dispatch({ type: "START", analysisType: type, resourceUrl: url });
      // Nudge the bar off 0% immediately. The time-based ramp only fires on the
      // first poll tick (3-5 s in), so without this the bar would read a literal
      // "0%" for the first few seconds and look stuck. A small starting value
      // signals "started" the instant the user clicks.
      dispatch({
        type: "SET_PROGRESS",
        progress: 5,
        message: "Starting analysis...",
      });

      const refreshSuffix = refresh ? "?refresh=true" : "";

      // Both quick and detailed go through POST /analysis. The orchestrator
      // dispatches differently per analysisType:
      //   quick    -> 202 + analysisId; the quick-scan-worker Lambda runs the
      //               scan async and the frontend polls GET /analysis/{id}.
      //   detailed -> Step Functions execution; progress streams over WebSocket.
      // This pattern unification side-steps API Gateway's 30 s integration
      // timeout for synchronous quick scans.
      try {
        // Detailed analysis uses WebSocket for LIVE progress events, but it is
        // strictly an optimization: the poll loop below (GET /analysis/{id})
        // independently guarantees the result appears. So a WS connect failure
        // must NOT abort the analysis — otherwise a flaky/unwired progress
        // socket makes the whole detailed scan "click and reset". Connect
        // best-effort; swallow the error and fall through to POST + poll.
        if (type === "detailed") {
          try {
            await ws.connect();
          } catch (wsErr) {
            dispatch({
              type: "ADD_LOG",
              entry: logEntry(
                "Live Updates Unavailable",
                "Progress socket unavailable; falling back to polling for results.",
                "info",
              ),
            });
          }
        }

        const response = await fetch(
          `${API_BASE_URL}/analysis/${type}${refreshSuffix}`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ resourceUrl: url, analysisType: type }),
          },
        );

        // 202 IN_PROGRESS for quick async; 200 for detailed-async + cache hit.
        if (!response.ok && response.status !== 202) {
          throw new Error(`HTTP error! status: ${response.status}`);
        }

        const data = await response.json();

        if (data.error) {
          dispatch({ type: "FAIL", error: data.error });
          return;
        }

        const analysisId = data.analysisId;
        dispatch({ type: "SET_ANALYSIS_ID", analysisId });

        // Cache hit (200 + cached=true): results inline. Surface immediately
        // and skip both polling (quick) and WebSocket subscription (detailed).
        if (data.cached === true && data.status === "COMPLETED" && data.results) {
          const properties: PropertyData[] = normalizeProperties(data.results.properties);
          dispatch({
            type: "COMPLETE",
            results: properties,
            cached: true,
            cachedAt: data.cached_at ?? null,
          });
          if (data.results.resourceType) {
            dispatch({
              type: "SET_RESOURCE_TYPE",
              resourceType: data.results.resourceType,
            });
          }
          dispatch({
            type: "ADD_LOG",
            entry: logEntry(
              "Cached Result",
              `Returned cached analysis from ${data.cached_at ?? "earlier"}`,
              "success",
            ),
          });
          return;
        }

        if (type === "quick") {
          // Poll GET /analysis/{id} every 3 s up to 5 min for COMPLETED/FAILED.
          // Cold-start cap is ~90 s (uvx install + Bedrock); 5 min headroom
          // covers retries.
          dispatch({
            type: "ADD_LOG",
            entry: logEntry(
              "Analysis Started",
              "Quick scan dispatched — polling for results",
            ),
          });

          const POLL_INTERVAL_MS = 3000;
          const MAX_POLL_TIME_MS = 5 * 60 * 1000;
          // Quick scans typically finish in 30-90 s (cold start dominates).
          // Ramp the bar toward 90% over that window so it visibly advances;
          // only COMPLETE sets 100%.
          const QUICK_EXPECTED_MS = 90 * 1000;
          const QUICK_PROGRESS_CAP = 90;
          const start = Date.now();

          while (Date.now() - start < MAX_POLL_TIME_MS) {
            await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
            const pollResp = await fetch(
              `${API_BASE_URL}/analysis/${analysisId}`,
            );
            if (!pollResp.ok) continue;
            const pollData = await pollResp.json();
            if (pollData.status === "COMPLETED") {
              const properties: PropertyData[] = normalizeProperties(
                pollData.results?.properties,
              );
              dispatch({
                type: "COMPLETE",
                results: properties,
                cached: false,
                cachedAt: null,
              });
              if (pollData.results?.resourceType) {
                dispatch({
                  type: "SET_RESOURCE_TYPE",
                  resourceType: pollData.results.resourceType,
                });
              }
              dispatch({
                type: "ADD_LOG",
                entry: logEntry(
                  "Analysis Complete",
                  `Found ${properties.length} security properties`,
                  "success",
                ),
              });
              return;
            }
            if (pollData.status === "FAILED") {
              dispatch({
                type: "FAIL",
                error: pollData.error || "Quick scan failed",
              });
              return;
            }
            // Time-based ramp so the bar moves instead of sitting at a static
            // value. Approaches QUICK_PROGRESS_CAP but never reaches 100% from
            // the ramp — only COMPLETE does.
            const elapsed = Date.now() - start;
            const ramped = Math.min(
              QUICK_PROGRESS_CAP,
              Math.floor((elapsed / QUICK_EXPECTED_MS) * QUICK_PROGRESS_CAP),
            );
            dispatch({
              type: "SET_PROGRESS",
              progress: ramped,
              message: "Analyzing — this can take 30-90 seconds on cold start...",
            });
          }
          dispatch({
            type: "FAIL",
            error: "Quick scan timed out after 5 minutes",
          });
          return;
        }

        // Detailed analysis: subscribe WebSocket for live progress events AND
        // poll GET /analysis/{id} as a fallback. The WebSocket makes the cards
        // populate live; the poll guarantees results still appear if any WS
        // event is missed (e.g. the progress-notifier endpoint isn't wired, or
        // the socket drops). This mirrors the quick-scan reliability pattern so
        // detailed analysis never hangs while completed results sit in DynamoDB.
        ws.subscribe(analysisId);

        dispatch({
          type: "ADD_LOG",
          entry: logEntry(
            "Analysis Started",
            "Initializing security analysis",
          ),
        });

        // Step Functions stores `results` as a stringified JSON wrapped in a
        // DynamoDB { "S": "..." } attribute, whereas quick scan stores a native
        // object. Unwrap+parse both shapes before reading `.properties`.
        const unwrapResults = (raw: unknown): { properties?: unknown[]; resourceType?: string } => {
          if (raw && typeof raw === "object" && "S" in (raw as Record<string, unknown>)) {
            try {
              return JSON.parse((raw as { S: string }).S);
            } catch {
              return {};
            }
          }
          return (raw as { properties?: unknown[]; resourceType?: string }) ?? {};
        };

        // Detailed analysis is a Step Functions Map: each element is the Map
        // iteration context, with the per-property agent output buried at
        // `propertyResult.Payload.result`. Flatten each element to that inner
        // analysis object so normalizeProperty() sees the real fields. Quick
        // scan is already flat, so elements without that nesting pass through.
        const flattenDetailed = (items: unknown[]): unknown[] =>
          items.map((it) => {
            const el = it as {
              propertyResult?: { Payload?: { result?: unknown } };
              property?: { name?: string };
            };
            const inner = el?.propertyResult?.Payload?.result;
            if (inner && typeof inner === "object") {
              // Carry the crawler-provided name as a fallback if the analyzer
              // omitted propertyName.
              return { name: el.property?.name, ...(inner as object) };
            }
            return it;
          });

        const DETAILED_POLL_MS = 5000;
        const DETAILED_MAX_MS = 10 * 60 * 1000; // detailed is slower (multi-agent fan-out)
        // Time we expect a typical detailed scan to take. The bar ramps toward
        // DETAILED_PROGRESS_CAP over this window so the user sees steady
        // movement instead of a bar frozen at 0%. We never reach 100% from the
        // ramp alone — only the COMPLETE action sets 100%, so a fast finish
        // jumps to done and a slow one keeps inching forward without lying.
        const DETAILED_EXPECTED_MS = 5 * 60 * 1000; // ~5 min for a large resource
        const DETAILED_PROGRESS_CAP = 90;
        const detailedStart = Date.now();

        // The WebSocket "complete" handler and this poll loop both dispatch the
        // same terminal COMPLETE/FAIL action — whichever lands first wins and
        // the other's dispatch is a harmless idempotent repeat of the same
        // terminal state. So the poll needs no cross-check against WS status.
        while (Date.now() - detailedStart < DETAILED_MAX_MS) {
          await new Promise((r) => setTimeout(r, DETAILED_POLL_MS));

          // Advance the progress bar based on elapsed time. WebSocket progress
          // events (if the socket connected) may overwrite this with real
          // step-based values; absent those, this time-based ramp is what keeps
          // the bar moving during the multi-minute fan-out.
          const elapsed = Date.now() - detailedStart;
          const ramped = Math.min(
            DETAILED_PROGRESS_CAP,
            Math.floor((elapsed / DETAILED_EXPECTED_MS) * DETAILED_PROGRESS_CAP),
          );
          dispatch({
            type: "SET_PROGRESS",
            progress: ramped,
            message: "Analyzing properties — this can take a few minutes...",
          });

          let pollResp: Response;
          try {
            pollResp = await fetch(`${API_BASE_URL}/analysis/${analysisId}`);
          } catch {
            continue; // transient network error — keep polling
          }
          if (!pollResp.ok) continue;
          const pollData = await pollResp.json();

          if (pollData.status === "COMPLETED") {
            const r = unwrapResults(pollData.results);
            const flattened = flattenDetailed(
              Array.isArray(r.properties) ? r.properties : [],
            );
            const properties: PropertyData[] = normalizeProperties(flattened);
            dispatch({
              type: "COMPLETE",
              results: properties,
              cached: false,
              cachedAt: null,
            });
            if (r.resourceType) {
              dispatch({ type: "SET_RESOURCE_TYPE", resourceType: r.resourceType });
            }
            dispatch({
              type: "ADD_LOG",
              entry: logEntry(
                "Analysis Complete",
                `Found ${properties.length} security properties`,
                "success",
              ),
            });
            return;
          }
          if (pollData.status === "FAILED") {
            dispatch({ type: "FAIL", error: pollData.error || "Detailed analysis failed" });
            return;
          }
        }
        dispatch({ type: "FAIL", error: "Detailed analysis timed out after 10 minutes" });
      } catch (error: unknown) {
        dispatch({
          type: "FAIL",
          error:
            "Failed to start analysis: " + (error as Error).message,
        });
      }
    },
    [ws],
  );

  /**
   * Reset all analysis state back to idle.
   * Validates: Requirement 4.6
   */
  const resetAnalysis = useCallback(() => {
    ws.disconnect();
    dispatch({ type: "RESET" });
  }, [ws]);

  // --- Batch analysis (Phase 6) ---
  // Batch state is intentionally separate from the single-URL reducer above:
  // batch is a one-shot fan-out without progress/SSE/WebSocket plumbing, and
  // mixing it into the existing reducer would force every single-URL action
  // path to also reason about a results map. Two simple useState calls keep
  // each surface understandable.
  const [batchAnalyzing, setBatchAnalyzing] = useState(false);
  const [batchError, setBatchError] = useState<string | null>(null);
  const [batchResponse, setBatchResponse] =
    useState<BatchAnalysisResponse | null>(null);

  const analyzeBatch = useCallback(
    async (urls: string[]): Promise<BatchAnalysisResponse | null> => {
      setBatchAnalyzing(true);
      setBatchError(null);

      // Phase 8 async pattern: POST returns 202 + batchId, frontend polls
      // GET /analysis/batch/{batchId} until COMPLETED or FAILED. The worker
      // runs the parallel fan-out (up to 5 quick scans) under its own
      // 15-min Lambda cap; 5 min polling timeout is plenty.
      try {
        const resp = await fetch(`${API_BASE_URL}/analysis/batch`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ resourceUrls: urls }),
        });

        if (!resp.ok && resp.status !== 202) {
          const detail = await resp.json().catch(() => ({}));
          throw new Error(
            detail.error || detail.message || `HTTP ${resp.status}`,
          );
        }

        const dispatched = await resp.json();
        const batchId: string | undefined = dispatched.batchId;

        // Backwards-compat: if the server ever returns inline results.
        if (dispatched.results && !batchId) {
          const data = dispatched as BatchAnalysisResponse;
          setBatchResponse(data);
          return data;
        }
        if (!batchId) {
          throw new Error("No batchId returned from server");
        }

        type BatchJob = {
          status: string;
          result?: BatchAnalysisResponse;
          error?: string;
        };
        const finalState = await pollUntilDone<BatchJob>(
          `${API_BASE_URL}/analysis/batch/${batchId}`,
          (d) => d.status === "COMPLETED" || d.status === "FAILED",
        );

        if (finalState.status === "FAILED") {
          throw new Error(finalState.error || "Batch analysis failed");
        }
        if (!finalState.result) {
          throw new Error("Batch completed but no result was returned");
        }
        const data: BatchAnalysisResponse = finalState.result;
        setBatchResponse(data);
        return data;
      } catch (err: unknown) {
        const msg =
          err instanceof PollTimeoutError
            ? "Batch analysis timed out after 5 minutes"
            : (err as Error).message || "Failed to run batch analysis";
        setBatchError(msg);
        return null;
      } finally {
        setBatchAnalyzing(false);
      }
    },
    [],
  );

  const clearBatch = useCallback(() => {
    setBatchAnalyzing(false);
    setBatchError(null);
    setBatchResponse(null);
  }, []);

  return {
    status: state.status,
    analysisId: state.analysisId,
    results: state.results,
    progress: state.progress,
    progressMessage: state.progressMessage,
    activityLog: state.activityLog,
    error: state.error,
    resourceUrl: state.resourceUrl,
    resourceType: state.resourceType,
    analysisType: state.analysisType,
    cached: state.cached,
    cachedAt: state.cachedAt,
    startAnalysis,
    analyzeBatch,
    batchAnalyzing,
    batchError,
    batchResponse,
    clearBatch,
    resetAnalysis,
  };
}
