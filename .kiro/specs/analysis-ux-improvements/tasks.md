# Implementation Plan: Analysis UX Improvements

## Overview

Implement SSE streaming for quick scan results, fix the progress section not hiding after completion, add elapsed timer and enhanced progress indicators, and add SSE connection resilience with polling fallback. Backend changes are in `service/routers/analysis.py`, frontend changes in `frontend/app.js`, `frontend/index.html`, and `frontend/styles.css`.

## Tasks

- [x] 1. Add SSE streaming endpoint to backend
  - [x] 1.1 Add `sse_event` helper and `parse_properties` helper to `service/routers/analysis.py`
    - `sse_event(event_type, data)` formats a dict as an SSE event string
    - `parse_properties(agent_result)` extracts the properties array from the agent response, handling JSON with `properties` key, raw text with embedded JSON, and empty responses
    - Extract the parsing logic currently in `frontend/app.js` `displayQuickScanResults` into this backend helper
    - _Requirements: 2.4_

  - [x] 1.2 Write property tests for SSE helpers
    - **Property 4: SSE event sequence for successful scan**
    - **Validates: Requirements 2.3, 2.4, 2.5**
    - **Property 8: Elapsed timer format**
    - **Validates: Requirements 3.1**

  - [x] 1.3 Add `POST /analysis/stream` SSE endpoint to `service/routers/analysis.py`
    - Reuse existing `create_analysis_record`, `invoke_quick_scan_agent`, `update_analysis_status`
    - Return `StreamingResponse` with `media_type="text/event-stream"` and `Cache-Control: no-cache`, `X-Accel-Buffering: no` headers
    - Emit `status` event with `phase: "started"` and `analysisId`
    - Call `invoke_quick_scan_agent`, parse properties, emit one `property` event per property with `index`, `total`, `name`, `riskLevel`, `securityImplication`, `recommendation`
    - Emit `complete` event with `analysisId` and `totalProperties`
    - On exception: emit `error` event, update DynamoDB to FAILED
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_

  - [x] 1.4 Write property tests for SSE endpoint
    - **Property 3: SSE endpoint returns correct content type and headers**
    - **Validates: Requirements 2.1, 2.2**
    - **Property 5: SSE error event on agent failure**
    - **Validates: Requirements 2.6**

- [x] 2. Checkpoint - Ensure all backend tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 3. Fix progress section hiding and add UI state management
  - [x] 3.1 Add `hideProgressSection` function to `frontend/app.js`
    - Adds `hidden` class to `progressSection`
    - Stops elapsed timer and message rotator
    - Re-enables submit button with original text
    - _Requirements: 1.1, 1.2, 1.3, 6.2, 6.3_

  - [x] 3.2 Update `startAnalysis` to reset UI state on new analysis
    - Call `hideAllSections` to hide both progress and results
    - Clear `resultsSection.innerHTML` to remove previous results
    - Show progress section
    - Disable submit button
    - _Requirements: 1.4, 6.1, 6.4_

  - [x] 3.3 Wire `hideProgressSection` into all completion paths
    - Call from `displayQuickScanResults` after rendering results
    - Call from `handleAnalysisComplete` after fetching detailed results
    - Call from `handleError` on WebSocket errors
    - Call from `showError` function
    - _Requirements: 1.1, 1.2, 1.3_

- [x] 4. Add elapsed timer and enhanced progress indicators
  - [x] 4.1 Add elapsed timer to `frontend/app.js`
    - Add `elapsedTimerInterval`, `elapsedSeconds` variables
    - Implement `startElapsedTimer()` that increments every second and updates display with format "Elapsed: Xs"
    - Implement `stopElapsedTimer()` that clears the interval
    - Call `startElapsedTimer()` when analysis starts
    - Call `stopElapsedTimer()` in `hideProgressSection`
    - _Requirements: 3.1, 3.2, 3.3_

  - [x] 4.2 Add elapsed timer display element to `frontend/index.html`
    - Add a `<span id="elapsedTimer">` element in the Progress_Section header area
    - _Requirements: 3.1_

  - [x] 4.3 Add pulsing animation and rotating status messages
    - Add `pulse-bg` CSS class to `frontend/styles.css` with keyframe animation
    - Add `QUICK_SCAN_MESSAGES` array and `startMessageRotator`/`stopMessageRotator` functions to `frontend/app.js`
    - Apply `pulse-bg` class to Progress_Section during quick scan, remove on completion
    - Start message rotator when quick scan begins, stop in `hideProgressSection`
    - _Requirements: 4.1, 4.2_

  - [x] 4.4 Write property test for progress bar calculation
    - **Property 7: Progress bar calculation from index and total**
    - **Validates: Requirements 4.3, 4.5**

- [x] 5. Implement SSE client and streaming display in frontend
  - [x] 5.1 Add SSE event parser to `frontend/app.js`
    - Implement `parseSSEEvents(buffer)` that splits a text buffer into parsed SSE events with `event` and `data` fields, returning parsed events and remaining buffer
    - _Requirements: 2.7_

  - [x] 5.2 Add `startQuickScanSSE` function to `frontend/app.js`
    - Use `fetch` with `response.body.getReader()` to read the SSE stream
    - Parse events using `parseSSEEvents`
    - Route events to `handleSSEEvent` which dispatches by event type:
      - `status`: add activity log entry, store `analysisId`
      - `property`: render property card via existing `createPropertyCard`, update progress bar using `Math.round(((index + 1) / total) * 100)`
      - `complete`: call `hideProgressSection`, add completion log entry
      - `error`: call `showError`, call `hideProgressSection`
    - _Requirements: 2.7, 2.8, 2.9, 4.3_

  - [x] 5.3 Update `startAnalysis` to use SSE for quick scan
    - When `analysisType` is `quick`, call `startQuickScanSSE` instead of the REST fetch
    - Keep existing WebSocket flow for detailed analysis
    - Show results section when first property event arrives
    - _Requirements: 2.7_

- [x] 6. Add SSE fallback polling
  - [x] 6.1 Implement `startFallbackPolling` in `frontend/app.js`
    - Add activity log entry "Connection interrupted, checking for results..."
    - Poll `GET /analysis/{analysisId}` every 2 seconds
    - On COMPLETED: call `displayQuickScanResults` with results, call `hideProgressSection`, stop polling
    - On FAILED: call `showError`, call `hideProgressSection`, stop polling
    - _Requirements: 5.1, 5.2, 5.3_

  - [x] 6.2 Wire fallback into SSE client
    - In `startQuickScanSSE`, if the reader finishes (`done` is true) but no `complete` or `error` event was received, call `startFallbackPolling` with the stored `analysisId`
    - Also trigger fallback on fetch errors after the stream has started
    - _Requirements: 5.1_

- [x] 7. Update detailed analysis WebSocket handling
  - [x] 7.1 Update `handleProgressUpdate` to display step name in progress text
    - Use `data.step` or `data.message` to update `progressText.textContent`
    - _Requirements: 4.4_

  - [x] 7.2 Update `handleAnalysisComplete` to call `hideProgressSection`
    - Replace inline button re-enable with `hideProgressSection` call
    - _Requirements: 1.2_

- [x] 8. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- The SSE endpoint reuses all existing backend helpers — no new AWS service calls
- Frontend changes are all in vanilla JS/CSS with no build step required
- Property tests validate the SSE streaming logic and progress calculations on the backend
