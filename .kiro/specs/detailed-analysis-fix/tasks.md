# Implementation Plan: Detailed Analysis Fix

## Overview

Fix the detailed analysis flow by updating the frontend WebSocket message handler to recognize backend message format, adding an analysis type selector to the UI, implementing the `displayResults()` function for detailed analysis output, and adding per-property progress notifications to the Step Functions workflow.

## Tasks

- [x] 1. Add analysis type selector to the UI
  - [x] 1.1 Add analysis type radio button cards to `frontend/index.html`
    - Insert a radio button group between the URL input and the submit button
    - Two options: "Quick Scan" (value `quick`) and "Detailed Analysis" (value `detailed`, checked by default)
    - Include icons (fa-bolt for quick, fa-microscope for detailed) and descriptions
    - _Requirements: 3.1, 3.2, 3.3, 3.4_
  - [x] 1.2 Add CSS styles for the analysis type selector in `frontend/styles.css`
    - Style the radio cards to match existing Tailwind design
    - Add selected/hover states
    - _Requirements: 3.6_
  - [x] 1.3 Update `handleFormSubmit()` in `frontend/app.js` to read the selected analysis type and pass it to `startAnalysis()`
    - Read `document.querySelector('input[name="analysisType"]:checked').value`
    - Pass as second argument to `startAnalysis(url, analysisType)`
    - _Requirements: 3.5_

- [x] 2. Fix WebSocket message handling for detailed analysis
  - [x] 2.1 Update `handleWebSocketMessage()` in `frontend/app.js` to recognize `step`-based messages
    - Add secondary routing on `data.step` when `data.type`/`data.action` is not recognized
    - Route `crawl` → `handleStepCrawlComplete`, `property_analyzed` → `handleStepPropertyAnalyzed`, `analyze` → `handleStepAnalyzeComplete`, `complete` → `handleStepWorkflowComplete`
    - Log unrecognized messages without crashing
    - _Requirements: 1.1, 1.5_
  - [x] 2.2 Implement `handleStepCrawlComplete(data)` in `frontend/app.js`
    - Update progress to ~20%, add activity log entry for crawl completion
    - _Requirements: 1.2, 4.2_
  - [x] 2.3 Implement `handleStepPropertyAnalyzed(data)` in `frontend/app.js`
    - Extract property data from `data.detail`
    - Render property card incrementally using `createPropertyCard()` and `addPropertyCardToUI()`
    - Calculate progress: `Math.round(20 + ((index + 1) / total) * 70)`
    - Update progress bar and add activity log entry
    - _Requirements: 4.3_
  - [x] 2.4 Implement `handleStepAnalyzeComplete(data)` in `frontend/app.js`
    - Update progress to ~90%, add activity log entry
    - _Requirements: 1.3, 4.4_
  - [x] 2.5 Implement `handleStepWorkflowComplete(data)` in `frontend/app.js`
    - Update progress to 100%, add activity log entry
    - Fetch final results via `fetchResults(currentSessionId)`
    - Hide progress section, re-enable form button
    - _Requirements: 1.4, 2.1, 2.3, 4.5_

- [x] 3. Implement displayResults() for detailed analysis
  - [x] 3.1 Implement `displayResults()` in `frontend/app.js`
    - Parse `results.S` JSON string from the DynamoDB response to extract properties array
    - Handle the `Payload` wrapper on each property result from the Lambda invoker
    - Create results container with header and property count
    - Render property cards using `createPropertyCard()`, skipping properties already rendered via WebSocket
    - Re-enable form button and hide progress section
    - _Requirements: 2.2, 2.3, 2.4_

- [x] 4. Checkpoint - Verify frontend changes
  - Ensure all tests pass, ask the user if questions arise.
  - Manually verify: analysis type selector renders, form submits with correct type, WebSocket messages are routed correctly

- [x] 5. Add per-property progress notifications to Step Functions workflow
  - [x] 5.1 Add a `Pass` state before the Map to compute `totalProperties` in `stacks/stepfunctions_stack.py`
    - Use `States.ArrayLength()` to compute the count of properties from the crawl result
    - Pass `totalProperties` into the Map state parameters
    - _Requirements: 5.1_
  - [x] 5.2 Add `NotifyPropertyAnalyzed` Lambda invoke step inside the Map iterator in `stacks/stepfunctions_stack.py`
    - Chain after `AnalyzeSingleProperty`: `AnalyzeSingleProperty → NotifyPropertyAnalyzed`
    - Invoke the existing `progress_notifier` Lambda with payload: `{analysisId, step: "property_analyzed", status: "COMPLETED", detail: {property, result, index, total}}`
    - Add catch handler for `States.ALL` to ignore notification failures
    - _Requirements: 5.1, 5.2, 5.3_
  - [x] 5.3 Write unit test for the updated Step Functions state machine definition
    - Verify the synthesized state machine includes `NotifyPropertyAnalyzed` inside the Map iterator
    - Verify the catch handler is present on the notification step
    - Verify the notification payload template contains the required fields
    - _Requirements: 5.1, 5.2, 5.3_

- [x] 6. Checkpoint - Verify infrastructure changes
  - Ensure all tests pass, ask the user if questions arise.
  - Run `cdk synth` to verify the updated state machine definition compiles

- [x] 7. Add property-based tests
  - [x] 7.1 Write property test for step-based message routing (Property 1)
    - **Property 1: Step-based message routing correctness**
    - Generate random step values from known set, verify correct handler is called
    - **Validates: Requirements 1.1**
  - [x] 7.2 Write property test for unrecognized message resilience (Property 2)
    - **Property 2: Unrecognized message resilience**
    - Generate arbitrary dicts, verify no exception from message handler
    - **Validates: Requirements 1.5**
  - [x] 7.3 Write property test for detailed results display completeness (Property 3)
    - **Property 3: Detailed results display completeness**
    - Generate random property arrays, verify output count matches and names are present
    - **Validates: Requirements 2.2**
  - [x] 7.4 Write property test for per-property progress calculation (Property 4)
    - **Property 4: Per-property progress calculation**
    - Generate random (index, total) pairs, verify progress formula and range [20, 90]
    - **Validates: Requirements 4.3**
  - [x] 7.5 Write property test for notification payload completeness (Property 5)
    - **Property 5: Per-property notification payload completeness**
    - Generate random property dicts and index/total pairs, verify all required fields present
    - **Validates: Requirements 5.1**

- [x] 8. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- The backend FastAPI service (callbacks router, WebSocket router, analysis router) is NOT modified
- The quick scan SSE streaming flow is NOT touched
- Frontend property-based tests are implemented in Python (hypothesis) mirroring the JS logic, since the frontend has no Node test runner
- Run `cdk synth` after task 5 to verify the state machine definition before deploying
