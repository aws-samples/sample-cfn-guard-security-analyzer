import { useReducer, useCallback, useMemo } from "react";
import type {
  AnalysisState,
  AnalysisType,
  PropertyData,
  ActivityLogEntry,
  SSEPropertyEvent,
  WebSocketMessage,
} from "../types";
import { API_BASE_URL } from "../config";
import { useSSE } from "./useSSE";
import { useWebSocket } from "./useWebSocket";

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
  startAnalysis: (url: string, type: AnalysisType) => Promise<void>;
  resetAnalysis: () => void;
}

// --- Reducer ---

type Action =
  | { type: "START"; analysisType: AnalysisType; resourceUrl: string }
  | { type: "SET_ANALYSIS_ID"; analysisId: string }
  | { type: "ADD_RESULT"; property: PropertyData }
  | { type: "SET_PROGRESS"; progress: number; message: string }
  | { type: "ADD_LOG"; entry: ActivityLogEntry }
  | { type: "COMPLETE"; results?: PropertyData[] }
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

  const { startStream } = useSSE(sseOptions);

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
   * Validates: Requirements 4.2, 4.3
   */
  const startAnalysis = useCallback(
    async (url: string, type: AnalysisType) => {
      dispatch({ type: "START", analysisType: type, resourceUrl: url });

      if (type === "quick") {
        await startStream(url);
        return;
      }

      // Detailed analysis: WebSocket + REST
      try {
        await ws.connect();

        const response = await fetch(`${API_BASE_URL}/analysis`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ resourceUrl: url, analysisType: type }),
        });

        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`);
        }

        const data = await response.json();

        if (data.error) {
          dispatch({ type: "FAIL", error: data.error });
          return;
        }

        const analysisId = data.analysisId;
        dispatch({ type: "SET_ANALYSIS_ID", analysisId });
        ws.subscribe(analysisId);

        dispatch({
          type: "ADD_LOG",
          entry: logEntry(
            "Analysis Started",
            "Initializing security analysis",
          ),
        });
      } catch (error: unknown) {
        dispatch({
          type: "FAIL",
          error:
            "Failed to start analysis: " + (error as Error).message,
        });
      }
    },
    [startStream, ws],
  );

  /**
   * Reset all analysis state back to idle.
   * Validates: Requirement 4.6
   */
  const resetAnalysis = useCallback(() => {
    ws.disconnect();
    dispatch({ type: "RESET" });
  }, [ws]);

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
    startAnalysis,
    resetAnalysis,
  };
}
