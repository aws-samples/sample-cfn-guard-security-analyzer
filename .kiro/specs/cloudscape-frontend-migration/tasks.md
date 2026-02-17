# Implementation Plan: Cloudscape Frontend Migration

## Overview

Migrate the CloudFormation Security Analyzer frontend from vanilla HTML/JS/CSS to React 18 + TypeScript + Vite with Cloudscape Design System. Tasks are ordered to build foundational layers first (project setup, types, config, utilities), then hooks, then UI components, and finally wiring everything together.

## Tasks

- [x] 1. Scaffold React + Vite + TypeScript project
  - [x] 1.1 Create `frontend/package.json` with React 18, TypeScript, Vite, Cloudscape, vitest, @testing-library/react, fast-check, and jsdom dependencies
    - _Requirements: 1.2, 1.3, 1.4_
  - [x] 1.2 Create `frontend/vite.config.ts` with React plugin and `dist/` output directory
    - _Requirements: 1.1_
  - [x] 1.3 Create `frontend/tsconfig.json` with strict mode enabled, JSX react-jsx, and path aliases
    - _Requirements: 1.5_
  - [x] 1.4 Create `frontend/index.html` entry point that mounts the React app to a root div
    - _Requirements: 1.1_
  - [x] 1.5 Create `frontend/src/main.tsx` that renders the App component with Cloudscape global styles
    - _Requirements: 2.1_

- [x] 2. Define TypeScript types and configuration
  - [x] 2.1 Create `frontend/src/types.ts` with PropertyData, AnalysisState, ActivityLogEntry, SSEEvent, SSEPropertyEvent, WebSocketMessage, and AppConfig interfaces
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5_
  - [x] 2.2 Create `frontend/src/config.ts` with API_BASE_URL, WEBSOCKET_URL, localhost detection, EKS/Legacy toggle, timeouts, and feature flags
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5_

- [x] 3. Implement utility functions
  - [x] 3.1 Create `frontend/src/utils/normalizePropertyData.ts` — port the normalizePropertyData function from app.js with TypeScript types, handling DynamoDB Payload wrapper, WebSocket result wrapper, direct objects, and embedded JSON extraction
    - _Requirements: 10.1, 10.2, 10.3_
  - [x] 3.2 Create `frontend/src/utils/parseNumberedList.ts` — port the parseNumberedList function from app.js, returning an array of string items for numbered text or the original string for non-numbered text
    - _Requirements: 10.4, 10.5_
  - [x] 3.3 Write property tests for normalizePropertyData
    - **Property 8: Normalizer format handling**
    - **Property 9: Normalizer idempotence**
    - **Validates: Requirements 10.1, 10.2, 10.3**
  - [x] 3.4 Write property tests for parseNumberedList
    - **Property 10: Parser numbered list extraction**
    - **Validates: Requirements 10.4**

- [x] 4. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Implement custom hooks
  - [x] 5.1 Create `frontend/src/hooks/useSSE.ts` — implement SSE streaming via fetch ReadableStream, SSE buffer parsing (split on `\n\n`, extract `event:` and `data:` fields), event routing by type (status, property, complete, error), and fallback polling
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7_
  - [x] 5.2 Create `frontend/src/hooks/useWebSocket.ts` — implement WebSocket connection, message routing by step/type field (crawl, property_analyzed, complete, error), subscribe/disconnect functions, and reconnection with exponential backoff
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8_
  - [x] 5.3 Create `frontend/src/hooks/useAnalysis.ts` — implement analysis state management with useReducer, orchestrate useSSE for quick scan and useWebSocket for detailed analysis, fetch final results on completion, expose startAnalysis and resetAnalysis
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6_
  - [x] 5.4 Write property tests for SSE buffer parsing and event routing
    - **Property 4: SSE buffer parsing**
    - **Property 3: SSE event routing**
    - **Validates: Requirements 6.2, 6.3, 6.4, 6.5, 6.7**
  - [x] 5.5 Write property tests for WebSocket message routing
    - **Property 2: WebSocket message routing**
    - **Validates: Requirements 5.2, 5.3, 5.4, 5.5**

- [x] 6. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Implement UI components
  - [x] 7.1 Create `frontend/src/components/InputSection.tsx` — Cloudscape Container with Header, FormField + Input for URL, SegmentedControl for analysis type (Quick Scan / Detailed Analysis), Button to start analysis, URL validation on submit (empty/whitespace rejection), disabled state during in_progress
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7_
  - [x] 7.2 Create `frontend/src/components/ProgressSection.tsx` — Cloudscape Container with ProgressBar, Table for activity log (timestamp, title, details columns), elapsed time counter via useEffect setInterval
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_
  - [x] 7.3 Create `frontend/src/components/PropertyCard.tsx` — Cloudscape Container with Header showing property name, Badge for risk level (color-coded), security_impact text, conditional key_threat section, conditional recommendation section using parseNumberedList
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5_
  - [x] 7.4 Create `frontend/src/components/ResultsSection.tsx` — Cloudscape Container with KeyValuePairs for severity summary (counts with color-coded Badges), SegmentedControl for risk level filter, Grid layout of PropertyCard components, "Generate PDF Report" Button calling POST /reports/{analysisId}
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 9.6_
  - [x] 7.5 Write property tests for severity count and risk level filtering
    - **Property 5: Severity count accuracy**
    - **Property 6: Risk level filtering**
    - **Validates: Requirements 8.2, 8.4**
  - [x] 7.6 Write property tests for PropertyCard rendering
    - **Property 7: PropertyCard field rendering**
    - **Validates: Requirements 9.1, 9.2, 9.3, 9.4, 9.5**
  - [x] 7.7 Write property test for whitespace URL rejection
    - **Property 1: Whitespace URL rejection**
    - **Validates: Requirements 3.5**

- [x] 8. Wire up App component
  - [x] 8.1 Create `frontend/src/App.tsx` — Cloudscape AppLayout with header ("CloudFormation Security Analyzer"), BreadcrumbGroup, SpaceBetween composing InputSection, ProgressSection (visible when in_progress), ResultsSection (visible when results exist), using useAnalysis hook
    - _Requirements: 2.1, 2.2, 2.3_

- [x] 9. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Property tests use `fast-check` with minimum 100 iterations per property
- The backend (FastAPI on EKS) is unchanged — only the frontend is replaced
- After implementation, run `npm run build` in `frontend/` to produce `dist/` for S3 deployment
