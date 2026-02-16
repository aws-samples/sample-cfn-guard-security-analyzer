# Requirements Document

## Introduction

This feature improves the frontend user experience of the CloudFormation Security Analyzer during analysis operations. The current UX has three key problems: (1) the "Analysis in Progress" section remains visible after results are displayed, (2) quick scan provides no feedback during a 10-15 second wait, and (3) progress indicators lack elapsed time and meaningful status messages. The improvements introduce Server-Sent Events (SSE) for streaming quick scan results, better progress indicators with elapsed timers and pulsing animations, and proper cleanup of UI state after analysis completion.

## Glossary

- **Frontend**: The vanilla HTML/JS/CSS single-page application served via S3 and CloudFront, located in `frontend/`
- **FastAPI_Service**: The Python FastAPI backend running on EKS Fargate that handles analysis requests
- **Quick_Scan**: An analysis type that invokes a single Bedrock AgentCore agent and returns results synchronously, taking 10-15 seconds
- **Detailed_Analysis**: An analysis type that orchestrates a multi-step Step Functions workflow, taking 2-5 minutes
- **Progress_Section**: The HTML element (`#progressSection`) that displays a spinner, progress bar, and activity log during analysis
- **Results_Section**: The HTML element (`#resultsSection`) that displays security analysis findings
- **SSE_Endpoint**: A new FastAPI endpoint that streams partial results to the client using Server-Sent Events
- **Elapsed_Timer**: A UI component that displays the time elapsed since analysis started
- **Activity_Log**: The scrollable list within the Progress_Section that shows timestamped status messages

## Requirements

### Requirement 1: Hide Progress Section After Completion

**User Story:** As a user, I want the progress section to disappear once results are displayed, so that I see a clean results view without redundant loading indicators.

#### Acceptance Criteria

1. WHEN the Quick_Scan results are displayed in the Results_Section, THE Frontend SHALL hide the Progress_Section
2. WHEN the Detailed_Analysis completes and results are displayed in the Results_Section, THE Frontend SHALL hide the Progress_Section
3. WHEN an analysis fails with an error, THE Frontend SHALL hide the Progress_Section and display the error message
4. WHEN a new analysis is started, THE Frontend SHALL show the Progress_Section and hide the Results_Section

### Requirement 2: SSE Streaming for Quick Scan

**User Story:** As a user, I want to see partial results streaming in during a quick scan, so that I get immediate feedback instead of staring at a blank screen for 10-15 seconds.

#### Acceptance Criteria

1. THE SSE_Endpoint SHALL accept POST requests at `/analysis/stream` with the same request body as the existing `/analysis` endpoint
2. WHEN the SSE_Endpoint receives a valid request, THE FastAPI_Service SHALL return a `text/event-stream` response with `Cache-Control: no-cache` headers
3. WHEN the SSE_Endpoint begins processing, THE FastAPI_Service SHALL emit a `status` event with `{"phase": "started", "analysisId": "<id>"}` payload
4. WHEN the Bedrock AgentCore agent returns a response, THE FastAPI_Service SHALL parse the result and emit one `property` event per security property found
5. WHEN all properties have been emitted, THE FastAPI_Service SHALL emit a `complete` event with the full analysis summary and close the stream
6. IF the Bedrock AgentCore invocation fails, THEN THE FastAPI_Service SHALL emit an `error` event with a descriptive message and close the stream
7. WHEN the Frontend initiates a quick scan, THE Frontend SHALL connect to the SSE_Endpoint instead of the REST `/analysis` endpoint
8. WHEN the Frontend receives a `property` event, THE Frontend SHALL immediately render the property card in the Results_Section
9. WHEN the Frontend receives the `complete` event, THE Frontend SHALL hide the Progress_Section and re-enable the form

### Requirement 3: Elapsed Time Display

**User Story:** As a user, I want to see how long the analysis has been running, so that I know the system is still working and can estimate remaining time.

#### Acceptance Criteria

1. WHEN an analysis starts, THE Frontend SHALL display an Elapsed_Timer in the Progress_Section showing seconds elapsed in the format "Elapsed: Xs"
2. WHILE an analysis is in progress, THE Frontend SHALL update the Elapsed_Timer every second
3. WHEN the analysis completes or fails, THE Frontend SHALL stop the Elapsed_Timer

### Requirement 4: Enhanced Progress Indicators

**User Story:** As a user, I want clear visual feedback during analysis, so that I can tell the system is actively working on my request.

#### Acceptance Criteria

1. WHILE a quick scan is in progress, THE Frontend SHALL display a pulsing animation on the Progress_Section background
2. WHILE a quick scan is in progress, THE Frontend SHALL cycle through contextual status messages every 3 seconds (e.g., "Connecting to security agent...", "Analyzing resource properties...", "Evaluating security configurations...")
3. WHEN a property is received via SSE during quick scan, THE Frontend SHALL update the progress bar proportionally based on properties received versus an estimated total
4. WHILE a detailed analysis is in progress, THE Frontend SHALL display the current workflow step received via WebSocket in the Progress_Section
5. WHEN a property_complete event is received via WebSocket during detailed analysis, THE Frontend SHALL update the progress bar based on the `progress` and `total` fields

### Requirement 5: SSE Connection Resilience

**User Story:** As a user, I want the analysis to complete even if the streaming connection drops, so that I do not lose results due to transient network issues.

#### Acceptance Criteria

1. IF the SSE connection closes before the `complete` event is received, THEN THE Frontend SHALL fall back to polling `GET /analysis/{analysisId}` every 2 seconds until the status is COMPLETED or FAILED
2. IF the SSE connection closes before the `complete` event is received, THEN THE Frontend SHALL display a message "Connection interrupted, checking for results..." in the Activity_Log
3. WHEN the fallback polling receives a COMPLETED status, THE Frontend SHALL display the results from the polling response and hide the Progress_Section

### Requirement 6: Form State Management

**User Story:** As a user, I want the analyze button and form to behave predictably during and after analysis, so that I can start new analyses without confusion.

#### Acceptance Criteria

1. WHILE an analysis is in progress, THE Frontend SHALL disable the submit button and display "Analyzing..." with a spinner icon
2. WHEN an analysis completes successfully, THE Frontend SHALL re-enable the submit button and restore the original button text
3. WHEN an analysis fails, THE Frontend SHALL re-enable the submit button and restore the original button text
4. WHEN a new analysis is started, THE Frontend SHALL clear any previous results from the Results_Section
