/** Risk level for a security property finding. */
export type RiskLevel = "CRITICAL" | "HIGH" | "MEDIUM" | "LOW";

/** Activity log entry type. */
export type LogEntryType = "info" | "success" | "error";

/** Analysis status. */
export type AnalysisStatus = "idle" | "in_progress" | "completed" | "failed";

/** Analysis type. */
export type AnalysisType = "quick" | "detailed";

/**
 * A single security property finding returned by the analysis.
 * Validates: Requirement 12.1
 */
export interface PropertyData {
  name: string;
  risk_level: RiskLevel;
  description: string;
  security_impact: string;
  key_threat: string;
  secure_configuration: string;
  recommendation: string;
  property_path: string;
  best_practices: string[];
  common_misconfigurations: string[];
}

/**
 * A generated CloudFormation Guard rule.
 */
export interface GuardRule {
  ruleName: string;
  resourceType: string;
  propertyName: string;
  guardRule: string;
  description: string;
  passTemplate: string;
  failTemplate: string;
  riskLevel: RiskLevel;
}

/**
 * An entry in the analysis activity log.
 * Validates: Requirement 12.3
 */
export interface ActivityLogEntry {
  timestamp: string;
  title: string;
  details: string;
  type: LogEntryType;
}

/**
 * The full analysis state managed by the useAnalysis hook.
 * Validates: Requirement 12.2
 */
export interface AnalysisState {
  status: AnalysisStatus;
  analysisId: string | null;
  analysisType: AnalysisType;
  results: PropertyData[];
  progress: number;
  progressMessage: string;
  activityLog: ActivityLogEntry[];
  error: string | null;
  resourceUrl: string | null;
  resourceType: string | null;
}

/**
 * A parsed SSE event from the streaming response.
 * Validates: Requirement 12.5
 */
export interface SSEEvent {
  event: string;
  data: unknown;
}

/**
 * SSE property event payload for quick scan streaming.
 * Validates: Requirement 12.5
 */
export interface SSEPropertyEvent {
  name: string;
  riskLevel: string;
  securityImplication: string;
  recommendation: string;
  index: number;
  total: number;
}

/**
 * WebSocket message received during detailed analysis.
 * Validates: Requirement 12.5
 */
export interface WebSocketMessage {
  step?: string;
  type?: string;
  action?: string;
  detail?: Record<string, unknown>;
  progress?: number;
  total?: number;
  error?: string;
  message?: string;
}

/**
 * Application configuration shape.
 * Validates: Requirement 12.4
 */
export interface AppConfig {
  API_BASE_URL: string;
  WEBSOCKET_URL: string;
  AUTH: {
    useIAM: boolean;
    useCognito: boolean;
  };
  FEATURES: {
    batchAnalysis: boolean;
    pdfReports: boolean;
    realtimeUpdates: boolean;
  };
  TIMEOUTS: {
    analysisTimeout: number;
    websocketTimeout: number;
    maxReconnectAttempts: number;
  };
}
