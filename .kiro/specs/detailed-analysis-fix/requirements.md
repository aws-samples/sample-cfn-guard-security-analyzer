# Requirements Document

## Introduction

This spec addresses two issues in the CloudFormation Security Analyzer frontend: (1) the detailed analysis WebSocket message handler does not recognize the message format sent by the backend, causing the UI to stay stuck at 0% progress even though the analysis completes successfully, and (2) the UI lacks an analysis type selector, so users cannot choose between quick scan and detailed analysis.

## Glossary

- **Frontend**: The vanilla HTML/JS/CSS single-page application served via CloudFront + S3 (`frontend/` directory)
- **WebSocket_Handler**: The `handleWebSocketMessage()` function in `frontend/app.js` that processes incoming WebSocket messages
- **Progress_Notifier**: The Lambda function that POSTs progress updates from Step Functions to the FastAPI `/callbacks/progress` endpoint
- **Callbacks_Router**: The FastAPI router at `/callbacks/progress` that receives progress updates and broadcasts them via WebSocket
- **Analysis_Form**: The HTML form in `index.html` that accepts a CloudFormation documentation URL and triggers analysis
- **Analysis_Type_Selector**: A UI control that allows users to choose between quick scan and detailed analysis
- **Progress_Section**: The UI section (`#progressSection`) that displays analysis progress bar, percentage, and activity log
- **Results_Section**: The UI section (`#resultsSection`) that displays security property cards grouped by risk level
- **Backend_Message**: A JSON object broadcast via WebSocket with the shape `{"step": "<step>", "status": "<status>", "detail": {...}}`
- **Quick_Scan**: A fast analysis (~30 seconds) that checks the top 5-10 critical security properties using SSE streaming
- **Detailed_Analysis**: A comprehensive analysis (2-5 minutes) that crawls documentation and analyzes all security properties via a Step Functions workflow with WebSocket progress updates

## Requirements

### Requirement 1: WebSocket Message Recognition

**User Story:** As a user running a detailed analysis, I want the frontend to correctly process progress messages from the backend, so that I can see real-time progress updates instead of a stuck UI.

#### Acceptance Criteria

1. WHEN the WebSocket_Handler receives a Backend_Message with a `step` field, THE WebSocket_Handler SHALL recognize the message and route it to the appropriate handler based on the `step` value
2. WHEN the WebSocket_Handler receives a Backend_Message with `step` equal to `"crawl"` and `status` equal to `"COMPLETED"`, THE Frontend SHALL update the Progress_Section to reflect that documentation crawling is complete
3. WHEN the WebSocket_Handler receives a Backend_Message with `step` equal to `"analyze"` and `status` equal to `"COMPLETED"`, THE Frontend SHALL update the Progress_Section to reflect that property analysis is complete
4. WHEN the WebSocket_Handler receives a Backend_Message with `step` equal to `"complete"` and `status` equal to `"COMPLETED"`, THE Frontend SHALL treat the message as analysis completion and trigger result fetching
5. WHEN the WebSocket_Handler receives a message that has neither a recognized `type`/`action` field nor a recognized `step` field, THE WebSocket_Handler SHALL log the unrecognized message without crashing

### Requirement 2: Detailed Analysis Completion Flow

**User Story:** As a user who has completed a detailed analysis, I want to see the security findings displayed in the results UI, so that I can review the analysis output.

#### Acceptance Criteria

1. WHEN the detailed analysis completes (step `"complete"`), THE Frontend SHALL fetch the final results from `GET /analysis/{analysisId}`
2. WHEN the final results are fetched successfully, THE Frontend SHALL display the security properties as property cards in the Results_Section
3. WHEN the final results are displayed, THE Frontend SHALL hide the Progress_Section and re-enable the Analysis_Form submit button
4. IF the fetch of final results fails, THEN THE Frontend SHALL display an error message to the user and re-enable the Analysis_Form submit button

### Requirement 3: Analysis Type Selector

**User Story:** As a user, I want to choose between a quick scan and a detailed analysis from the UI, so that I can pick the appropriate depth of analysis for my needs.

#### Acceptance Criteria

1. THE Analysis_Form SHALL include an Analysis_Type_Selector that offers two options: Quick Scan and Detailed Analysis
2. THE Analysis_Type_Selector SHALL default to Detailed Analysis as the selected option
3. WHEN the Analysis_Type_Selector displays the Quick Scan option, THE Frontend SHALL show a description indicating it takes approximately 30 seconds and focuses on top 5-10 critical security properties
4. WHEN the Analysis_Type_Selector displays the Detailed Analysis option, THE Frontend SHALL show a description indicating it takes 2-5 minutes and performs a comprehensive review of all security properties
5. WHEN the user submits the Analysis_Form, THE Frontend SHALL pass the selected analysis type to the `startAnalysis()` function
6. THE Analysis_Type_Selector SHALL be visually consistent with the existing Tailwind CSS design of the Analysis_Form

### Requirement 4: Progress Display for Detailed Analysis Steps

**User Story:** As a user watching a detailed analysis in progress, I want to see meaningful progress updates for each workflow step, so that I understand what the system is doing.

#### Acceptance Criteria

1. WHEN the detailed analysis begins, THE Progress_Section SHALL display an initial progress state with 0% and a message indicating analysis has started
2. WHEN the crawl step completes, THE Frontend SHALL update the progress bar to approximately 20% and add an activity log entry indicating documentation crawling is complete
3. WHEN a `property_analyzed` step is received, THE Frontend SHALL update the progress bar proportionally based on the property index relative to the total number of properties (scaled between 20% and 90%) and add the property card to the Results_Section incrementally
4. WHEN the analyze step completes, THE Frontend SHALL update the progress bar to approximately 90% and add an activity log entry indicating all property analysis is complete
5. WHEN the complete step is received, THE Frontend SHALL update the progress bar to 100% and add an activity log entry indicating the analysis is complete

### Requirement 5: Per-Property Progress Notifications in Step Functions Workflow

**User Story:** As a user running a detailed analysis, I want to see each property result appear in real time as it is analyzed, so that I get incremental feedback similar to the quick scan experience.

#### Acceptance Criteria

1. WHEN a single property analysis completes within the Step Functions Map state, THE Progress_Notifier SHALL send a WebSocket message with `step` equal to `"property_analyzed"`, the property result data, the property index, and the total number of properties
2. THE Step Functions workflow SHALL invoke the Progress_Notifier Lambda after each individual property analysis within the Map iterator, before proceeding to the next property
3. IF the per-property progress notification fails, THEN THE Step Functions workflow SHALL continue processing the remaining properties without interruption
