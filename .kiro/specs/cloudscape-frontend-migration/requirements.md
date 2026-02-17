# Requirements Document

## Introduction

Migrate the CloudFormation Security Analyzer frontend from vanilla HTML/JS/CSS to a React 18 + TypeScript application using the Cloudscape Design System. The new frontend replaces the existing `frontend/` directory contents with a Vite-based React project that builds to static files for S3 + CloudFront hosting. All existing business logic (quick scan SSE, detailed analysis WebSocket, PDF report generation, real-time progress) is preserved. The backend (FastAPI on EKS) and all APIs remain unchanged.

## Glossary

- **App**: The top-level React component that composes all sections and manages application layout using Cloudscape AppLayout.
- **InputSection**: The React component containing the URL input field, analysis type selector, and submit button.
- **ProgressSection**: The React component displaying analysis progress via a ProgressBar and activity log table.
- **ResultsSection**: The React component displaying severity summary stats, risk level filter, property cards grid, and PDF report button.
- **PropertyCard**: The React component rendering a single security property finding with risk badge, security impact, key threat, and recommendation.
- **useAnalysis**: A custom React hook managing analysis state, REST API calls, result fetching, and coordination of useWebSocket/useSSE.
- **useWebSocket**: A custom React hook managing WebSocket connection lifecycle, message routing, and reconnection for detailed analysis.
- **useSSE**: A custom React hook managing SSE streaming via fetch ReadableStream for quick scan results.
- **Config**: The TypeScript module (`config.ts`) exporting API_BASE_URL, WEBSOCKET_URL, and feature/timeout settings.
- **Normalizer**: The `normalizePropertyData` utility function that transforms raw API/WebSocket/SSE property payloads into a consistent PropertyData shape.
- **Parser**: The `parseNumberedList` utility function that converts numbered text strings into structured list data.
- **Cloudscape**: The open-source AWS design system (`@cloudscape-design/components`) providing UI components.
- **Vite**: The build tool used to bundle the React application into static files.

## Requirements

### Requirement 1: Project Scaffolding and Build Configuration

**User Story:** As a developer, I want a properly configured React + TypeScript + Vite project with Cloudscape dependencies, so that I can develop and build the frontend application.

#### Acceptance Criteria

1. THE Vite build system SHALL produce static files (HTML, JS, CSS) in a `dist/` output directory suitable for S3 + CloudFront hosting
2. THE project SHALL use React 18, TypeScript, and Vite as the core build stack
3. THE project SHALL include `@cloudscape-design/components` and `@cloudscape-design/global-styles` as dependencies
4. THE project SHALL include `vitest` and `@testing-library/react` as dev dependencies for testing
5. THE TypeScript configuration SHALL enforce strict type checking

### Requirement 2: Application Layout and Navigation

**User Story:** As a user, I want a consistent application layout with a header and breadcrumb navigation, so that I can identify the application and orient myself within it.

#### Acceptance Criteria

1. THE App SHALL render a Cloudscape AppLayout with a navigation header displaying the application name "CloudFormation Security Analyzer"
2. THE App SHALL render a BreadcrumbGroup component for navigation context
3. THE App SHALL compose the InputSection, ProgressSection, and ResultsSection within the AppLayout content area using SpaceBetween for vertical spacing

### Requirement 3: Analysis Input Form

**User Story:** As a user, I want to enter a CloudFormation documentation URL and choose an analysis type, so that I can initiate a security analysis.

#### Acceptance Criteria

1. THE InputSection SHALL render a Cloudscape Container with a Header titled "Analyze CloudFormation Documentation"
2. THE InputSection SHALL render a FormField with an Input component for entering a CloudFormation documentation URL
3. THE InputSection SHALL render a SegmentedControl with two options: "Quick Scan" and "Detailed Analysis"
4. THE InputSection SHALL render a Button labeled "Start Security Analysis" that initiates the analysis
5. WHEN the user submits the form with an empty or whitespace-only URL, THE InputSection SHALL display a FormField error message and prevent submission
6. WHEN the user submits a valid URL, THE InputSection SHALL call the useAnalysis hook's startAnalysis function with the URL and selected analysis type
7. WHILE an analysis is in progress, THE InputSection SHALL disable the submit Button and display a loading indicator

### Requirement 4: Analysis State Management

**User Story:** As a user, I want the application to manage analysis lifecycle state, so that the UI reflects the current status of my analysis.

#### Acceptance Criteria

1. THE useAnalysis hook SHALL maintain state for: analysis status (idle, in_progress, completed, failed), current analysis ID, analysis results, progress percentage, progress message, and activity log entries
2. WHEN startAnalysis is called with analysisType "quick", THE useAnalysis hook SHALL delegate to the useSSE hook to stream results via SSE
3. WHEN startAnalysis is called with analysisType "detailed", THE useAnalysis hook SHALL first establish a WebSocket connection via useWebSocket, then POST to `{API_BASE_URL}/analysis` with the resourceUrl and analysisType, and subscribe to WebSocket updates using the returned analysisId
4. WHEN a detailed analysis completes, THE useAnalysis hook SHALL fetch final results from `GET {API_BASE_URL}/analysis/{analysisId}` and parse the response
5. IF the REST API call to start an analysis fails, THEN THE useAnalysis hook SHALL set the status to "failed" and store the error message
6. THE useAnalysis hook SHALL expose a resetAnalysis function that clears all state back to idle


### Requirement 5: WebSocket Connection Management

**User Story:** As a user running a detailed analysis, I want real-time progress updates via WebSocket, so that I can see each property result as it completes.

#### Acceptance Criteria

1. WHEN the useWebSocket hook connects, THE hook SHALL open a WebSocket connection to the configured WEBSOCKET_URL
2. WHEN a WebSocket message with step "crawl" is received, THE useWebSocket hook SHALL invoke the onCrawlComplete callback with the message data
3. WHEN a WebSocket message with step "property_analyzed" is received, THE useWebSocket hook SHALL normalize the property data using normalizePropertyData and invoke the onPropertyAnalyzed callback
4. WHEN a WebSocket message with step "complete" is received, THE useWebSocket hook SHALL invoke the onComplete callback
5. WHEN a WebSocket message with type "error" is received, THE useWebSocket hook SHALL invoke the onError callback with the error message
6. IF the WebSocket connection closes unexpectedly, THEN THE useWebSocket hook SHALL attempt reconnection up to the configured maxReconnectAttempts with exponential backoff
7. THE useWebSocket hook SHALL expose a subscribe function that sends a JSON message `{action: "subscribe", analysisId}` over the open connection
8. THE useWebSocket hook SHALL expose a disconnect function that closes the WebSocket connection and stops reconnection attempts

### Requirement 6: SSE Streaming for Quick Scan

**User Story:** As a user running a quick scan, I want to see property results stream in real-time via SSE, so that I get immediate feedback as each property is analyzed.

#### Acceptance Criteria

1. WHEN the useSSE hook starts streaming, THE hook SHALL POST to `{API_BASE_URL}/analysis/stream` with the resourceUrl and analysisType, and read the response body as a ReadableStream
2. WHEN an SSE event with type "status" is received, THE useSSE hook SHALL store the analysisId and invoke the onStatus callback
3. WHEN an SSE event with type "property" is received, THE useSSE hook SHALL invoke the onProperty callback with the property data (name, riskLevel, securityImplication, recommendation, index, total)
4. WHEN an SSE event with type "complete" is received, THE useSSE hook SHALL invoke the onComplete callback with the totalProperties count
5. WHEN an SSE event with type "error" is received, THE useSSE hook SHALL invoke the onError callback with the error message
6. IF the SSE stream ends without a terminal event (complete or error) and an analysisId exists, THEN THE useSSE hook SHALL fall back to polling `GET {API_BASE_URL}/analysis/{analysisId}` every 2 seconds until status is COMPLETED or FAILED
7. THE useSSE hook SHALL parse the SSE text buffer by splitting on double newlines, extracting "event:" and "data:" fields, and JSON-parsing the data field

### Requirement 7: Progress Display

**User Story:** As a user, I want to see analysis progress with a progress bar and activity log, so that I know the analysis is running and can track its steps.

#### Acceptance Criteria

1. WHILE an analysis is in progress, THE ProgressSection SHALL be visible
2. THE ProgressSection SHALL render a Cloudscape ProgressBar reflecting the current progress percentage
3. THE ProgressSection SHALL render a Cloudscape Table displaying activity log entries with columns: timestamp, event title, and details
4. THE ProgressSection SHALL display an elapsed time counter that increments every second during analysis
5. WHEN the analysis completes or fails, THE ProgressSection SHALL become hidden

### Requirement 8: Results Display with Severity Summary

**User Story:** As a user, I want to see a summary of findings by severity and filter results by risk level, so that I can focus on the most critical security issues.

#### Acceptance Criteria

1. WHEN analysis results are available, THE ResultsSection SHALL be visible
2. THE ResultsSection SHALL render severity summary statistics using Cloudscape KeyValuePairs, showing counts for Critical, High, Medium, and Low findings, each with a corresponding color-coded Badge
3. THE ResultsSection SHALL render a SegmentedControl with options: All, Critical, High, Medium, Low for filtering property cards by risk level
4. WHEN a risk level filter is selected, THE ResultsSection SHALL display only PropertyCard components matching the selected risk level, or all cards when "All" is selected
5. THE ResultsSection SHALL render a "Generate PDF Report" Button that triggers PDF report generation via `POST {API_BASE_URL}/reports/{analysisId}`
6. WHEN the PDF report is successfully generated, THE ResultsSection SHALL open the report URL in a new browser tab

### Requirement 9: Property Card Display

**User Story:** As a user, I want each security finding displayed as a card with risk badge, security impact, key threat, and recommendation, so that I can understand and act on each finding.

#### Acceptance Criteria

1. THE PropertyCard SHALL display the property name as the card title
2. THE PropertyCard SHALL display a color-coded Cloudscape Badge indicating the risk level (Critical=red, High=orange, Medium=yellow, Low=green)
3. THE PropertyCard SHALL display the security impact text
4. WHEN a key threat is present, THE PropertyCard SHALL display the key threat in a highlighted section
5. WHEN a recommendation is present, THE PropertyCard SHALL display the recommendation text, rendering numbered lists as ordered HTML lists using the parseNumberedList utility
6. THE ResultsSection SHALL render PropertyCard components in a responsive grid layout using Cloudscape Grid

### Requirement 10: Data Normalization Utilities

**User Story:** As a developer, I want utility functions that normalize raw API responses into consistent data shapes, so that components receive predictable data regardless of the API response format.

#### Acceptance Criteria

1. THE Normalizer SHALL accept raw property data in any of the known API formats (DynamoDB response with `propertyResult.Payload`, WebSocket message with `result`, direct object with `name` and `risk_level`) and return a consistent PropertyData object with fields: name, risk_level, description, security_impact, key_threat, secure_configuration, recommendation, property_path
2. WHEN the raw data contains a JSON string embedded in a text field, THE Normalizer SHALL extract the first balanced JSON object from the text and parse it
3. WHEN the raw data is already normalized (has `name` and `risk_level` at top level), THE Normalizer SHALL return the data unchanged
4. THE Parser SHALL accept a text string and return structured list data: an array of string items when the text contains numbered items (e.g., "1. Do X 2. Do Y"), or the original text when no numbered pattern is detected
5. WHEN the Parser receives an empty or null input, THE Parser SHALL return an empty string

### Requirement 11: Configuration Management

**User Story:** As a developer, I want API endpoints and feature flags in a separate configuration file, so that I can change deployment targets without modifying application code.

#### Acceptance Criteria

1. THE Config module SHALL export API_BASE_URL and WEBSOCKET_URL constants
2. THE Config module SHALL detect localhost and use local development URLs (`http://localhost:8000` and `ws://localhost:8000/ws`) when running locally
3. THE Config module SHALL support an EKS/Legacy toggle for production endpoint selection
4. THE Config module SHALL export timeout settings including analysisTimeout, websocketTimeout, and maxReconnectAttempts
5. THE Config module SHALL export feature flags for batchAnalysis, pdfReports, and realtimeUpdates

### Requirement 12: Type Safety

**User Story:** As a developer, I want TypeScript interfaces for all data structures, so that the codebase is type-safe and self-documenting.

#### Acceptance Criteria

1. THE types module SHALL define a PropertyData interface with fields: name, risk_level, description, security_impact, key_threat, secure_configuration, recommendation, property_path, best_practices, common_misconfigurations
2. THE types module SHALL define an AnalysisState interface with fields: status, analysisId, results, progress, progressMessage, activityLog, error
3. THE types module SHALL define an ActivityLogEntry interface with fields: timestamp, title, details, type (info, success, error)
4. THE types module SHALL define a Config interface matching the configuration structure
5. THE types module SHALL define SSEEvent and WebSocketMessage interfaces for the respective message formats
